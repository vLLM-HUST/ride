"""Workspace-owned processes deployed to Ray; never adopt unrecorded jobs."""
import os
import copy
import json
import re
import threading
import uuid
import fcntl
import tempfile
import weakref
from pathlib import Path
from datetime import datetime, timezone
from urllib.request import urlopen
from .registry import command, controller_adapter, model_service_adapter
from .job_submission import component_name, job_metadata, ray_entrypoint

_UNCONDITIONAL = object()

class Runtime:
    def __init__(self, config, client=None):
        self.config = copy.deepcopy(config)
        self.lock = threading.RLock()
        self.path = Path(config['state_file']).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._closed = False
        state_lock = self.path.with_name(self.path.name + '.lock').open('a')
        try:
            fcntl.flock(state_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            state_lock.close()
            raise RuntimeError('Management state already has a writer; state file locked') from error
        self._release_state_lock = weakref.finalize(self, state_lock.close)
        try:
            self._initialize(config, client)
        except BaseException:
            self.close()
            raise

    def _initialize(self, config, client):
        self.executor = config.get('deployment', 'ray')
        if self.executor not in ('ray', 'local'):
            raise ValueError('Unsupported process executor')
        if client is None:
            if self.executor == 'local':
                from .local_process import LocalProcessClient
                client = LocalProcessClient(self.path.parent / (self.path.stem + '-processes'))
            else:
                from ray.job_submission import JobSubmissionClient
                client = JobSubmissionClient(config['ray_address'])
        self.client = client
        self.state = json.loads(self.path.read_text()) if self.path.exists() else {'run_id': uuid.uuid4().hex, 'jobs': {}, 'operations': []}
        self.state.setdefault('specs', {'controllers': {}, 'model_services': {}})
        self.state.setdefault('submitted_specs', {})
        self.state.setdefault('start_operations', {})
        self.state.setdefault('executions', {})
        for kind in ('controllers', 'model_services'):
            self.state['specs'].setdefault(kind, {})
            for spec in config.get(kind, []):
                # Persisted specs are authoritative after CLI creation / restart.
                self.state['specs'][kind].setdefault(spec['id'], copy.deepcopy(spec))
        self.save()

    def close(self):
        """Release management ownership only; running Jobs remain untouched."""
        with self.lock:
            self._closed = True
            self._release_state_lock()

    def _ensure_open(self):
        if self._closed:
            raise RuntimeError('Management state writer is closed')

    def save(self):
        self._ensure_open()
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', dir=self.path.parent,
                    prefix=self.path.name + '.', delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(self.state, stream, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.path)
            descriptor = os.open(self.path.parent, os.O_RDONLY)
            try:os.fsync(descriptor)
            finally:os.close(descriptor)
        finally:
            if temporary is not None:temporary.unlink(missing_ok=True)

    def operation(self, action, target, result):
        self.state['operations'].append({'at': datetime.now(timezone.utc).isoformat(), 'action': action, 'target': target, 'result': result})
        self.save()

    @staticmethod
    def key(kind, identifier):
        return identifier if kind == 'controllers' else 'model-service/' + identifier

    def start_instance(self, kind, identifier, changes=None, *, operation_id=None, expected_job_id=_UNCONDITIONAL):
        if kind not in self.state['specs'] or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}', identifier):
            raise ValueError('Invalid resource kind or instance name')
        conditional = expected_job_id is not _UNCONDITIONAL
        if conditional != (operation_id is not None):
            raise ValueError('Conditional start requires operation_id and expected_job_id')
        if conditional:
            if not isinstance(operation_id,str) or not 0<len(operation_id)<=256:
                raise ValueError('Bounded operation identity required')
            if expected_job_id is not None and (not isinstance(expected_job_id,str) or not expected_job_id):
                raise ValueError('Prior Job identity required')
            requested=json.dumps(dict(kind=kind,identifier=identifier,changes=changes,
                expected_job_id=expected_job_id),sort_keys=True,separators=(',',':'),allow_nan=False)
        with self.lock:
            self._ensure_open()
            key=self.key(kind,identifier)
            if conditional:
                previous=self.state['start_operations'].get(operation_id)
                if previous:
                    if previous['request']!=requested:raise ValueError('Start operation payload conflict')
                    if previous['status']!='COMPLETED':raise ValueError('Start outcome unknown; inspect original Job, do not resubmit')
                    return copy.deepcopy(previous['result'])
                if self.state['jobs'].get(key)!=expected_job_id:
                    raise ValueError('Start precondition Job identity changed')
            old = self.state['specs'][kind].get(identifier)
            if old is None and not changes:
                raise ValueError('Unknown instance; provide type and configuration')
            spec = copy.deepcopy(old or {'id': identifier})
            spec.update(changes or {})
            spec['id'] = identifier
            start_deadline = None
            if 'start_not_after' in spec:
                value = spec['start_not_after']
                try:
                    if not isinstance(value,str):raise ValueError()
                    start_deadline = datetime.fromisoformat(value.replace('Z','+00:00'))
                    if start_deadline.utcoffset() is None:raise ValueError()
                except ValueError:raise ValueError('Timezone-aware model start deadline required')
            prefix = spec.get('job_name_prefix')
            if 'job_name_prefix' in spec and (not isinstance(prefix, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}', prefix)):
                raise ValueError('Invalid Ray Job name prefix')
            if prefix:
                for other_kind, specifications in self.state['specs'].items():
                    for other_identifier, other_spec in specifications.items():
                        if ((other_kind, other_identifier) != (kind, identifier)
                                and other_spec.get('job_name_prefix') == prefix):
                            raise ValueError('Each component requires a distinct job_name_prefix')
            if spec.get('executor', self.executor) != self.executor:
                raise ValueError('Instance executor must match management deployment')
            if self.executor == 'local':
                if kind != 'controllers':
                    raise ValueError('Local execution supports Controller only; model lifecycle stays external')
                if spec.get('resources') or spec.get('num_gpus', 0) or spec.get('num_cpus', 0):
                    raise ValueError('Local Controller resources are provided by the devbox, not Ray reservations')
                if set(spec.get('runtime_env', {})) - {'env_vars'}:
                    raise ValueError('Local runtime_env supports env_vars only')
            if old and changes and spec != old:
                raise ValueError('Instance configuration conflict; use a different instance name')
            component_command = command(kind, spec)
            display_name = component_name(kind, spec)
            key = self.key(kind, identifier)
            prior = self.state['jobs'].get(key)
            if prior:
                # Unknown outcome/query failure propagates: no duplicate submission.
                if self.client.get_job_status(prior).value in ('RUNNING', 'PENDING'):
                    if self.state['submitted_specs'].get(key, spec) != spec:
                        raise ValueError('Running instance configuration conflict')
                    result={'job_id': prior, 'unchanged': True, 'id': identifier}
                    if conditional:
                        self.state['start_operations'][operation_id]=dict(request=requested,status='COMPLETED',result=result,job_id=prior)
                        self.save()
                    return result
            if kind == 'controllers' and spec.get('model_service'):
                model = self.describe('model_services', spec['model_service'])
                if not model['ready']:
                    raise ValueError('Dependent model service is not Ready')
                if spec['backend'] != model['endpoint']:
                    raise ValueError('Controller backend does not match model service')
            if start_deadline is not None and datetime.now(timezone.utc) >= start_deadline:
                raise ValueError('Model start deadline expired; no new Job submitted')
            execution = self.state['executions'].get(key, 0) + 1
            workspace = self.config.get('workspace', self.state['run_id'])
            if not prefix:
                if not isinstance(workspace, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}', workspace):
                    raise ValueError('Set an explicit job_name_prefix for a workspace without a portable identifier')
                prefix = workspace + '-' + ('controller' if kind == 'controllers' else 'model-service') + '-' + identifier
            submission_id = prefix + '-execution-' + str(execution)
            if len(submission_id) > 200:
                raise ValueError('Submission identity too long; configure a shorter job_name_prefix')
            self.state['specs'][kind][identifier] = spec
            self.state['executions'][key] = execution
            self.state['jobs'][key] = submission_id
            self.state['submitted_specs'][key] = copy.deepcopy(spec)
            if conditional:
                self.state['start_operations'][operation_id]=dict(request=requested,status='UNKNOWN',job_id=submission_id,
                    kind=kind,identifier=identifier)
            self.operation('start-intent', key, submission_id)
            kwargs = dict(submission_id=submission_id, entrypoint=component_command,
                runtime_env=spec.get('runtime_env', {}), entrypoint_resources=spec.get('resources', {}))
            if self.executor == 'ray':
                kwargs.update(entrypoint=ray_entrypoint(component_command, display_name),
                              metadata=job_metadata(display_name, identifier, workspace, execution))
            for option, field in [('entrypoint_num_cpus', 'num_cpus'), ('entrypoint_num_gpus', 'num_gpus')]:
                if field in spec: kwargs[option] = spec[field]
            try:
                self.client.submit_job(**kwargs)
            except Exception:
                self.operation('start', key, 'UNKNOWN_OUTCOME')
                raise
            self.operation('start', key, 'SUBMITTED')
            result={'job_id': submission_id, 'id': identifier, 'endpoint': spec['endpoint']}
            if conditional:
                self.state['start_operations'][operation_id].update(status='COMPLETED',result=result)
                self.save()
            return result

    def start(self, identifier): return self.start_instance('controllers', identifier)
    def start_model_service(self, identifier): return self.start_instance('model_services', identifier)
    def stop_model_service(self, identifier): return self.stop_instance('model_services', identifier)

    def stop(self, identifier, *, expected_job_id=_UNCONDITIONAL):
        with self.lock:
            self._ensure_open()
            submission_id = self.state['jobs'].get(identifier)
            if not submission_id: raise ValueError('No owned job for instance')
            if expected_job_id is not _UNCONDITIONAL and (not isinstance(expected_job_id,str) or not expected_job_id or submission_id!=expected_job_id):
                raise ValueError('Stop precondition Job identity changed')
            result = self.client.stop_job(submission_id)
            self.operation('stop', identifier, str(result))
            return {'job_id': submission_id, 'stop_requested': result}

    def stop_instance(self, kind, identifier, *, expected_job_id=_UNCONDITIONAL):
        return self.stop(self.key(kind, identifier),expected_job_id=expected_job_id)

    def describe_operation(self, identifier):
        with self.lock:
            row=self.state['start_operations'].get(identifier)
            if row is None:raise ValueError('Unknown operation')
            return {key:copy.deepcopy(value) for key,value in row.items() if key not in ('request','result')}

    def logs(self, kind, identifier):
        key = self.key(kind, identifier)
        with self.lock:
            submission_id = self.state['jobs'].get(key)
            if not submission_id: raise ValueError('No owned job for instance')
        return {'job_id': submission_id, 'logs': self.client.get_job_logs(submission_id)}

    @staticmethod
    def health(endpoint):
        try:
            with urlopen(endpoint.rstrip('/') + '/health', timeout=2) as response:
                return response.status == 200
        except Exception:
            return False

    def describe(self, kind, identifier):
        with self.lock:
            spec = copy.deepcopy(self.state['specs'][kind].get(identifier))
            if not spec: raise ValueError('Unknown instance')
            submission_id = self.state['jobs'].get(self.key(kind, identifier))
        record = {'id': identifier, 'type': spec.get('type', spec.get('entrypoint')), 'kind': kind,
            'executor': self.executor, 'endpoint': spec['endpoint'], 'job_id': submission_id, 'job_status': 'NOT_STARTED', 'ready': False}
        # job_id is the historical RIDE lifecycle token (a submission ID).
        # Keep it for existing Controller CAS protocols; never label it native.
        record.update(display_name=component_name(kind, spec),
                      submission_id=submission_id if self.executor == 'ray' else None,
                      ray_job_id=None)
        if submission_id:
            try: record['job_status'] = self.client.get_job_status(submission_id).value
            except Exception as error: record['job_status'] = 'UNKNOWN'; record['job_error'] = type(error).__name__
            if self.executor == 'ray' and hasattr(self.client, 'get_job_info'):
                try:
                    information = self.client.get_job_info(submission_id)
                    record['ray_job_id'] = information.job_id
                except Exception as error:
                    record['ray_identity_error'] = type(error).__name__
        if kind == 'model_services':
            record['model'] = spec['model']
            record['evidence_type'] = 'mock' if spec.get('type')=='mock-vllm' else 'hardware'
            if record['type']not in ('vllm','mock-vllm'):
                adapter=model_service_adapter(record['type'])
                if adapter is None:
                    record['probe_error']='ModelServiceAdapterUnavailable'
                    return record
                if record['job_status']=='RUNNING':
                    try:
                        observed=adapter.probe(spec)
                        record['model_ready']=observed.get('model_ready')is True
                        for field in ('health','identity','status'):
                            if field in observed:record[field]=observed[field]
                        record['ready']=record['model_ready']
                    except Exception as error:record['probe_error']=type(error).__name__
                return record
            record['ready'] = record['job_status'] == 'RUNNING' and self.health(spec['endpoint'])
        else:
            if spec.get('backend') is not None:
                record['backend'] = spec['backend']
            adapter=controller_adapter(record['type']) if record['type']!='request-throttling' else None
            if adapter is not None:
                if record['job_status']=='RUNNING':
                    try:
                        observed=adapter.probe(spec)
                        record['controller_ready']=observed.get('controller_ready') is True
                        for field in ('health','identity','status'):
                            if field in observed:record[field]=observed[field]
                        record['ready']=record['controller_ready']
                    except Exception as error:record['probe_error']=type(error).__name__
                return record
            record['backend'] = spec['backend']
            record['engine_ready'] = self.health(spec['backend'])
            if record['job_status'] == 'RUNNING':
                try:
                    for route, key in [('/migration-identity', 'identity'), ('/health', 'health'), ('/programs', 'programs')]:
                        with urlopen(spec['endpoint'].rstrip('/') + route, timeout=2) as response: record[key] = json.load(response)
                    record['controller_ready'] = record['identity'].get('backends') == [spec['backend']] and record['identity'].get('scheduling_enabled') is True
                    record['ready'] = record['controller_ready'] and record['engine_ready']
                except Exception as error: record['probe_error'] = type(error).__name__
        return record

    def capabilities(self):
        return {'protocol_version':'1','conditional_start':True,'conditional_stop':True,'single_writer':True,'start_deadline':True,'inspect':True,'start_controller':True,'start_model_service':self.executor != 'local','mutate':True}

    def snapshot(self):
        with self.lock:
            names = {k: list(v) for k,v in self.state['specs'].items()}
            operations = copy.deepcopy(self.state['operations'][-30:])
        return {'name': self.config.get('name', 'RIDE'), 'workspace': self.config['workspace'],
            'run_id': self.state['run_id'], 'management_pid': os.getpid(), 'build_revision': os.environ.get('RIDE_BUILD_REVISION'), 'observed_at': datetime.now(timezone.utc).isoformat(),
            **{kind: [self.describe(kind, n) for n in ids] for kind,ids in names.items()},
            'operations': operations, 'capabilities': self.capabilities()}
