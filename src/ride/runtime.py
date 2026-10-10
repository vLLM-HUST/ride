"""Workspace-owned processes deployed to Ray; never adopt unrecorded jobs."""
import os
import copy
import json
import re
import threading
import uuid
from pathlib import Path
from datetime import datetime, timezone
from urllib.request import urlopen
from .registry import command, controller_adapter

class Runtime:
    def __init__(self, config, client=None):
        self.config = copy.deepcopy(config)
        self.lock = threading.RLock()
        self.path = Path(config['state_file'])
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if client is None:
            from ray.job_submission import JobSubmissionClient
            client = JobSubmissionClient(config['ray_address'])
        self.client = client
        self.state = json.loads(self.path.read_text()) if self.path.exists() else {'run_id': uuid.uuid4().hex, 'jobs': {}, 'operations': []}
        self.state.setdefault('specs', {'controllers': {}, 'model_services': {}})
        self.state.setdefault('submitted_specs', {})
        for kind in ('controllers', 'model_services'):
            self.state['specs'].setdefault(kind, {})
            for spec in config.get(kind, []):
                # Persisted specs are authoritative after CLI creation / restart.
                self.state['specs'][kind].setdefault(spec['id'], copy.deepcopy(spec))
        self.save()

    def save(self):
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.state, indent=2))
        temporary.replace(self.path)

    def operation(self, action, target, result):
        self.state['operations'].append({'at': datetime.now(timezone.utc).isoformat(), 'action': action, 'target': target, 'result': result})
        self.save()

    @staticmethod
    def key(kind, identifier):
        return identifier if kind == 'controllers' else 'model-service/' + identifier

    def start_instance(self, kind, identifier, changes=None):
        if kind not in self.state['specs'] or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}', identifier):
            raise ValueError('Invalid resource kind or instance name')
        with self.lock:
            old = self.state['specs'][kind].get(identifier)
            if old is None and not changes:
                raise ValueError('Unknown instance; provide type and configuration')
            spec = copy.deepcopy(old or {'id': identifier})
            spec.update(changes or {})
            spec['id'] = identifier
            if spec.get('executor', 'ray') != 'ray':
                raise ValueError('Only Ray execution is implemented')
            if old and changes and spec != old:
                raise ValueError('Instance configuration conflict; use a different instance name')
            cmd = command(kind, spec)
            key = self.key(kind, identifier)
            prior = self.state['jobs'].get(key)
            if prior:
                # Unknown outcome/query failure propagates: no duplicate submission.
                if self.client.get_job_status(prior).value in ('RUNNING', 'PENDING'):
                    if self.state['submitted_specs'].get(key, spec) != spec:
                        raise ValueError('Running instance configuration conflict')
                    return {'job_id': prior, 'unchanged': True, 'id': identifier}
            if kind == 'controllers' and spec.get('model_service'):
                model = self.describe('model_services', spec['model_service'])
                if not model['ready']:
                    raise ValueError('Dependent model service is not Ready')
                if spec['backend'] != model['endpoint']:
                    raise ValueError('Controller backend does not match model service')
            self.state['specs'][kind][identifier] = spec
            job_id = 'ride-' + ('controller-' if kind == 'controllers' else 'model-') + self.state['run_id'] + '-' + uuid.uuid4().hex[:8]
            self.state['jobs'][key] = job_id
            self.state['submitted_specs'][key] = copy.deepcopy(spec)
            self.operation('start-intent', key, job_id)
            kwargs = dict(submission_id=job_id, entrypoint=cmd,
                runtime_env=spec.get('runtime_env', {}), entrypoint_resources=spec.get('resources', {}))
            for option, field in [('entrypoint_num_cpus', 'num_cpus'), ('entrypoint_num_gpus', 'num_gpus')]:
                if field in spec: kwargs[option] = spec[field]
            try:
                self.client.submit_job(**kwargs)
            except Exception:
                self.operation('start', key, 'UNKNOWN_OUTCOME')
                raise
            self.operation('start', key, 'SUBMITTED')
            return {'job_id': job_id, 'id': identifier, 'endpoint': spec['endpoint']}

    def start(self, identifier): return self.start_instance('controllers', identifier)
    def start_model_service(self, identifier): return self.start_instance('model_services', identifier)
    def stop_model_service(self, identifier): return self.stop_instance('model_services', identifier)

    def stop(self, identifier):
        with self.lock:
            job_id = self.state['jobs'].get(identifier)
            if not job_id: raise ValueError('No owned job for instance')
            result = self.client.stop_job(job_id)
            self.operation('stop', identifier, str(result))
            return {'job_id': job_id, 'stop_requested': result}

    def stop_instance(self, kind, identifier): return self.stop(self.key(kind, identifier))

    def logs(self, kind, identifier):
        key = self.key(kind, identifier)
        with self.lock:
            job_id = self.state['jobs'].get(key)
            if not job_id: raise ValueError('No owned job for instance')
        return {'job_id': job_id, 'logs': self.client.get_job_logs(job_id)}

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
            job_id = self.state['jobs'].get(self.key(kind, identifier))
        record = {'id': identifier, 'type': spec.get('type', spec.get('entrypoint')), 'kind': kind,
            'endpoint': spec['endpoint'], 'job_id': job_id, 'job_status': 'NOT_STARTED', 'ready': False}
        if job_id:
            try: record['job_status'] = self.client.get_job_status(job_id).value
            except Exception as error: record['job_status'] = 'UNKNOWN'; record['job_error'] = type(error).__name__
        if kind == 'model_services':
            record['model'] = spec['model']
            record['evidence_type'] = 'mock' if spec.get('type')=='mock-vllm' else 'hardware'
            record['ready'] = record['job_status'] == 'RUNNING' and self.health(spec['endpoint'])
        else:
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

    def snapshot(self):
        with self.lock:
            names = {k: list(v) for k,v in self.state['specs'].items()}
            operations = copy.deepcopy(self.state['operations'][-30:])
        return {'name': self.config.get('name', 'RIDE'), 'workspace': self.config['workspace'],
            'run_id': self.state['run_id'], 'management_pid': os.getpid(), 'build_revision': os.environ.get('RIDE_BUILD_REVISION'), 'observed_at': datetime.now(timezone.utc).isoformat(),
            **{kind: [self.describe(kind, n) for n in ids] for kind,ids in names.items()},
            'operations': operations, 'capabilities': {'inspect': True, 'start_controller': True, 'start_model_service': True, 'mutate': True}}
