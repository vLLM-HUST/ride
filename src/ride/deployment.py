"""Compose the Ray launcher and public RIDE SDK; never implement policy here.

The deployment process may exit after readiness. Ray owns the management,
model and Controller Jobs. The journal is on the operator side; management
state lives on the explicitly pinned node's persistent filesystem.
"""
import argparse
from contextlib import contextmanager
import copy
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import subprocess
import time
from urllib.error import URLError
from urllib.parse import urlsplit

from .sdk import Journal, PeerClient, RideClient, UnknownOutcome
from .sdk.journal import canonical


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def validate_resources(spec):
    resources = spec.get('resources', {})
    if not isinstance(resources, dict) or any(
            not isinstance(key, str) or isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value < 0 for key, value in resources.items()):
        raise ValueError('Finite nonnegative Ray resources required')
    hostname = urlsplit(spec['endpoint']).hostname
    if resources.get('node:' + hostname, 0) <= 0:
        raise ValueError('Explicit endpoint must match its pinned Ray node address')


def validate_plan(plan):
    if not isinstance(plan, dict) or plan.get('schema') != 'ride.deployment/v1':
        raise ValueError('Expected ride.deployment/v1')
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,62}', plan.get('name', '')):
        raise ValueError('Bounded deployment name required')
    timeout = plan.get('readiness_timeout_seconds', 600)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('Positive operational readiness deadline required')
    ray = plan['ray']; management = plan['management']
    if ray.get('mode') not in ('existing', 'bootstrap'):
        raise ValueError('Explicit Ray mode required')
    RideClient(ray['address']); RideClient(management['endpoint'])
    validate_resources(management)
    if not Path(management['state_file']).is_absolute():
        raise ValueError('Management state_file must be persistent absolute path')
    if not management.get('resources') or not any(
            key.startswith('node:') and value > 0 for key, value in management['resources'].items()):
        raise ValueError('Pin management state to an explicit Ray node resource')
    if 'working_dir' in management.get('runtime_env', {}):
        raise ValueError('Management working_dir is reserved for frozen deployment configuration')
    if not isinstance(management.get('listen'), str) or ':' not in management['listen']:
        raise ValueError('Explicit management listen address required')
    models = {}; endpoints = {management['endpoint']}
    for kind in ('model_services', 'controllers'):
        specs = plan.get(kind, [])
        if not isinstance(specs, list):
            raise ValueError('Service specifications must be lists')
        names = set()
        for spec in specs:
            name = spec.get('id', '')
            if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,62}', name) or name in names:
                raise ValueError('Duplicate or invalid instance identity')
            names.add(name)
            if not spec.get('type') or spec.get('autostart'):
                raise ValueError('Explicit type required; deployment controls startup order')
            RideClient(spec['endpoint'])
            validate_resources(spec)
            if spec['endpoint'] in endpoints:
                raise ValueError('Service endpoints must be distinct')
            endpoints.add(spec['endpoint'])
            if kind == 'model_services':
                if not spec.get('model'):
                    raise ValueError('Explicit model path or identifier required')
                models[name] = spec
            elif spec.get('model_service'):
                model = models.get(spec['model_service'])
                if model is None or spec.get('backend') != model['endpoint']:
                    raise ValueError('Controller model dependency and backend must match')
    if not models:
        raise ValueError('At least one explicit model service required')
    controllers = {spec['id'] for spec in plan.get('controllers', [])}
    bound = set()
    for binding in plan.get('model_bindings', []):
        name = binding.get('controller')
        members = binding.get('model_services')
        if (name not in controllers or name in bound or not isinstance(members, list) or not members
                or any(member not in models for member in members) or len(set(members)) != len(members)
                or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', binding.get('token_env', ''))):
            raise ValueError('Explicit unique Controller/model binding and token environment name required')
        bound.add(name)
    if ray['mode'] == 'bootstrap':
        config = Path(ray['cluster_config'])
        if not config.is_absolute():
            raise ValueError('Absolute Ray cluster config path required')
        # JSON is also valid YAML and allows validation without a new dependency.
        cluster = json.loads(config.read_text())
        provider = cluster.get('provider', {})
        if cluster.get('cluster_name') != plan['name'] or provider.get('type') != 'local':
            raise ValueError('Bootstrap supports an explicitly named on-premise local provider only')
        if not provider.get('head_ip') or not isinstance(provider.get('worker_ips'), list):
            raise ValueError('Explicit head and worker inventory required')
        nodes = [provider['head_ip'], *provider['worker_ips']]
        if len(set(nodes)) != len(nodes):
            raise ValueError('Duplicate cluster node')
    canonical(plan)  # Reject non-JSON values and NaN before any effect.
    return plan


class Deployment:
    def __init__(self, plan, directory, *, ray_factory=None, management_factory=RideClient,
                 run=None):
        self.plan = copy.deepcopy(validate_plan(plan))
        self.root = Path(directory).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.journal = Journal(self.root / 'deployment.sqlite', 'ride-deployment')
        frozen = copy.deepcopy(self.plan)
        if self.plan['ray']['mode'] == 'bootstrap':
            frozen['cluster_config_sha256'] = hashlib.sha256(
                Path(self.plan['ray']['cluster_config']).read_bytes()).hexdigest()
        self.fingerprint = digest(frozen)
        self.cluster_sha256 = frozen.get('cluster_config_sha256')
        self.identity = 'ride-deployment-' + self.fingerprint
        def bind(state):
            if state and state.get('fingerprint') != self.fingerprint:
                raise ValueError('Deployment configuration conflict; use a new directory')
            state.update(fingerprint=self.fingerprint, plan=frozen)
        try:
            self.journal.mutate(bind)
        except BaseException:
            self.journal.close()
            raise
        self.run = run or (lambda args: subprocess.run(args, check=True))
        self.ray_factory = ray_factory
        self.management_factory = management_factory
        self.peer_factory = PeerClient
        self.timeout = self.plan.get('readiness_timeout_seconds', 600)

    def close(self):
        self.journal.close()

    @contextmanager
    def locked(self):
        with (self.root / 'deployment.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise ValueError('Another deployment operation is running') from error
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def ray(self):
        if self.ray_factory is None:
            from ray.job_submission import JobSubmissionClient
            return JobSubmissionClient(self.plan['ray']['address'])
        return self.ray_factory(self.plan['ray']['address'])

    def management(self):
        return self.management_factory(self.plan['management']['endpoint'])

    def wait(self, observe, expected, label):
        deadline = time.monotonic() + self.timeout
        last = None
        while True:
            try:
                last = observe()
            except (URLError, ConnectionError, TimeoutError, OSError) as error:
                last = {'observation_error': type(error).__name__}
            if expected(last):
                return last
            if isinstance(last, dict) and last.get('job_status') in ('FAILED', 'STOPPED', 'SUCCEEDED'):
                raise RuntimeError(label + ' terminated before readiness: ' + canonical(last))
            if time.monotonic() >= deadline:
                raise TimeoutError(label + ' not Ready: ' + canonical(last))
            time.sleep(min(0.25, max(0, deadline - time.monotonic())))

    def verify_management(self, status):
        if isinstance(status, dict) and 'workspace' in status:
            if status.get('workspace') != self.plan['name'] or status.get('name') != self.identity:
                raise ValueError('Management identity conflict; do not adopt foreign service')
            return True
        return False

    def management_submission(self):
        config = dict(name=self.identity, workspace=self.plan['name'], deployment='ray',
                      ray_address=self.plan['ray']['address'],
                      state_file=self.plan['management']['state_file'],
                      model_services=[], controllers=[])
        staging = self.root / 'management'
        staging.mkdir(exist_ok=True)
        path = staging / 'ride-deployment.json'
        content = canonical(config)
        if path.exists() and path.read_text() != content:
            raise ValueError('Staged management configuration changed')
        path.write_text(content)
        environment = dict(self.plan['management'].get('runtime_env', {}), working_dir=str(staging))
        return dict(submission_id=self.plan['name'] + '-management-' + self.fingerprint[:12],
                    entrypoint=shlex.join(['python', '-m', 'ride', 'serve', '--config',
                                          'ride-deployment.json', '--listen', self.plan['management']['listen']]),
                    runtime_env=environment, entrypoint_num_cpus=0.1, entrypoint_num_gpus=0,
                    entrypoint_resources=self.plan['management']['resources'],
                    metadata={'ride_deployment': self.fingerprint})

    def up(self):
        with self.locked():
            for binding in self.plan.get('model_bindings', []):
                if not os.environ.get(binding['token_env']):
                    raise ValueError('Missing peer token environment: ' + binding['token_env'])
            if self.journal.snapshot().get('stopping'):
                raise ValueError('Deployment is stopping or stopped; use a new deployment directory')
            if self.plan['ray']['mode'] == 'bootstrap':
                current = hashlib.sha256(Path(self.plan['ray']['cluster_config']).read_bytes()).hexdigest()
                if current != self.cluster_sha256:
                    raise ValueError('Ray cluster configuration changed after validation')
                args = ['ray', 'up', '-y', '--no-restart', self.plan['ray']['cluster_config']]
                self.journal.execute('bootstrap-ray', {'args': args}, lambda: self._bootstrap(args))
            ray = self.ray()
            submission = self.management_submission()
            result = self.journal.execute('start-management', submission,
                                          lambda: {'job_id': ray.submit_job(**submission)})
            if result.get('job_id') != submission['submission_id']:
                raise ValueError('Management submission identity mismatch')
            self.check_management_job(ray, submission)
            client = self.management()
            self.wait(client.status, self.verify_management, 'management')
            client.require_capabilities('conditional_start', 'conditional_stop')
            for kind, api in [('model_services', client.models), ('controllers', client.controllers)]:
                for spec in self.plan.get(kind, []):
                    operation = 'start-' + kind + '-' + spec['id']
                    started = self.journal.execute(operation, spec, lambda api=api, spec=spec, operation=operation:
                        api.start(spec['id'], spec, operation_id=self.fingerprint + ':' + operation,
                                  expected_job_id=None))
                    if not isinstance(started, dict) or not started.get('job_id'):
                        raise ValueError('Service submission identity missing')
                    def ready(observed):
                        if observed.get('job_id') and observed['job_id'] != started['job_id']:
                            raise ValueError('Service Job identity conflict')
                        return observed.get('ready') is True and observed.get('job_id') == started['job_id']
                    self.wait(lambda: api.describe(spec['id']), ready, kind + '/' + spec['id'])
            self.activate_bindings(client)
            result = dict(status='PASS', scope='deployment readiness only',
                          model_request='NOT_RUN', controller_action='NOT_RUN', performance='NOT_RUN',
                          endpoint=self.plan['management']['endpoint'], deployment=self.fingerprint)
            (self.root / 'readiness.json').write_text(json.dumps(result, indent=2) + '\n')
            return result

    def activate_bindings(self, client):
        models = {spec['id']: spec for spec in self.plan['model_services']}
        controllers = {spec['id']: spec for spec in self.plan.get('controllers', [])}
        for binding in self.plan.get('model_bindings', []):
            peer = self.peer_factory(controllers[binding['controller']]['endpoint'],
                                     token=os.environ[binding['token_env']], timeout=10)
            capabilities = peer.get('/control/capabilities')
            if capabilities.get('protocol_version') != '1' or capabilities.get('predeclared_pool_membership') is not True:
                raise ValueError('Controller does not support predeclared model membership')
            for name in binding['model_services']:
                record = client.models.describe(name)
                start = self.journal.execute('start-model_services-' + name, models[name], lambda: None)
                if record.get('ready') is not True or record.get('job_id') != start['job_id']:
                    raise ValueError('Model binding requires Ready exact owned Job identity')
                body = dict(replica=name, job_id=start['job_id'], endpoint=models[name]['endpoint'])
                def activate(body=body, peer=peer):
                    result = peer.post('/control/activate', body)
                    if (result.get('activated') is not True or result.get('replica') != body['replica']
                            or result.get('job_id') != body['job_id']):
                        raise ValueError('Controller membership acknowledgement differs')
                    return result
                self.journal.execute('bind-' + binding['controller'] + '-' + name, body, activate)

    def _bootstrap(self, args):
        self.run(args)
        return {'command': args, 'status': 'PASS'}

    def check_management_job(self, ray, submission):
        info = ray.get_job_info(submission['submission_id'])
        if info.entrypoint != submission['entrypoint'] or info.metadata.get('ride_deployment') != self.fingerprint:
            raise ValueError('Management Job identity conflict')
        if info.status.value in ('FAILED', 'STOPPED', 'SUCCEEDED'):
            raise RuntimeError('Management Job terminated; inspect logs and recover explicitly')

    def status(self):
        return dict(deployment=self.fingerprint, operations=self.journal.operations(),
                    management=self.management().status())

    def stop(self):
        """Explicit destructive service stop; preserve Ray and all platform objects."""
        with self.locked():
            self.journal.mutate(lambda state: state.update(stopping=True))
            ray = self.ray(); client = self.management()
            operations = {item['operation_id']: item['status'] for item in self.journal.operations()}
            if operations.get('stop-management') == 'COMPLETED':
                job = self.management_submission()['submission_id']
                status = ray.get_job_info(job).status.value
                return {'status': 'PASS' if status in ('STOPPED', 'SUCCEEDED', 'FAILED') else 'NOT_RUN',
                        'scope': 'management stop terminal check', 'job_status': status,
                        'cluster_preserved': True}
            if 'start-management' not in operations:
                return {'status': 'PASS', 'scope': 'no management Job submitted', 'cluster_preserved': True}
            if any(value != 'COMPLETED' for key, value in operations.items() if key.startswith('start-')):
                raise UnknownOutcome('Inspect unknown start outcomes before stopping')
            self.check_management_job(ray, self.management_submission())
            if not self.verify_management(client.status()):
                raise ValueError('Management identity unavailable')
            for kind, api in [('controllers', client.controllers), ('model_services', client.models)]:
                for spec in reversed(self.plan.get(kind, [])):
                    start_operation = 'start-' + kind + '-' + spec['id']
                    if start_operation not in operations:
                        continue
                    # Cached journal result; the effect cannot be called again.
                    started = self.journal.execute(start_operation, spec, lambda: None)
                    stop_operation = 'stop-' + kind + '-' + spec['id']
                    self.journal.execute(stop_operation, started, lambda api=api, spec=spec, started=started:
                        api.stop(spec['id'], expected_job_id=started['job_id']))
            submission = self.management_submission()
            job = submission['submission_id']
            self.journal.execute('stop-management', {'job_id': job}, lambda: {'stopped': ray.stop_job(job)})
            return {'status': 'PASS', 'scope': 'stop submitted; inspect Job terminal states', 'cluster_preserved': True}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Deploy a complete RIDE service onto explicit machines / existing Ray')
    parser.add_argument('action', choices=['validate', 'up', 'status', 'stop'])
    parser.add_argument('plan', type=Path)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args(argv)
    deployment = None
    try:
        plan = json.loads(args.plan.read_text())
        validate_plan(plan)
        if args.action == 'validate':
            print(json.dumps({'status': 'PASS', 'scope': 'configuration only; no remote checks'}))
            return
        deployment = Deployment(plan, args.directory)
        print(json.dumps(getattr(deployment, args.action)(), indent=2))
    except (ValueError, KeyError, TypeError, OSError, RuntimeError) as error:
        print(json.dumps({'status': 'FAIL', 'error': str(error), 'type': type(error).__name__}))
        raise SystemExit(1) from error
    finally:
        if deployment is not None:
            deployment.close()


if __name__ == '__main__':
    main()
