"""Deployment contracts; fake Ray/management effects, no accelerator claims."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from ride.deployment import Deployment, validate_plan
from ride.sdk import UnknownOutcome


def plan():
    return {
        'schema': 'ride.deployment/v1', 'name': 'myc-test',
        'ray': {'address': 'http://head:8265', 'mode': 'existing'},
        'management': {'endpoint': 'http://head:19100', 'listen': '0.0.0.0:19100',
                       'state_file': '/persistent/myc-test/state.json',
                       'resources': {'node:head': 0.001}, 'runtime_env': {}},
        'model_services': [dict(id='model-a', type='vllm', model='/models/example',
                                endpoint='http://worker:8000', resources={'NPU': 1, 'node:worker': 0.001})],
        'controllers': [dict(id='controller-a', type='fixture', model_service='model-a',
                            backend='http://worker:8000', endpoint='http://head:9000',
                            resources={'node:head': 0.001})],
        'readiness_timeout_seconds': 1,
    }


class Ray:
    def __init__(self):
        self.jobs = {}; self.submitted = []; self.stopped = []; self.fail = False

    def submit_job(self, **kwargs):
        self.submitted.append(kwargs)
        self.jobs[kwargs['submission_id']] = kwargs
        if self.fail:
            raise OSError('lost submission response')
        return kwargs['submission_id']

    def get_job_info(self, job):
        from types import SimpleNamespace
        item = self.jobs[job]
        return SimpleNamespace(status=SimpleNamespace(value='STOPPED' if job in self.stopped else 'RUNNING'),
                               entrypoint=item['entrypoint'], metadata=item['metadata'])

    def stop_job(self, job):
        self.stopped.append(job)
        return True

    def get_job_logs(self, job):
        return 'fixture log'


class Resources:
    def __init__(self, owner, kind):
        self.owner, self.kind = owner, kind

    def start(self, name, spec, **kwargs):
        self.owner.calls.append((self.kind, name, kwargs))
        job = self.kind + '-' + name
        self.owner.records[(self.kind, name)] = dict(job_id=job, ready=True, job_status='RUNNING')
        return {'job_id': job}

    def describe(self, name):
        return self.owner.records[(self.kind, name)]

    def stop(self, name, *, expected_job_id):
        actual = self.describe(name)['job_id']
        if actual != expected_job_id:
            raise ValueError('Job identity conflict')
        self.owner.stopped.append((self.kind, name, expected_job_id))
        return {'job_id': actual}


class Management:
    def __init__(self):
        self.calls = []; self.records = {}; self.stopped = []; self.identity = None
        self.models = Resources(self, 'models')
        self.controllers = Resources(self, 'controllers')

    def status(self):
        return self.identity

    def require_capabilities(self, *names):
        pass


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.ray = Ray(); self.management = Management(); self.commands = []

    def tearDown(self):
        self.temp.cleanup()

    def deployment(self, config=None):
        result = Deployment(config or plan(), self.root,
                            ray_factory=lambda address: self.ray,
                            management_factory=lambda address: self.management,
                            run=lambda args: self.commands.append(args))
        self.management.identity = {'workspace': 'myc-test', 'name': result.identity}
        return result

    def test_order_and_idempotence_survive_launcher_restart(self):
        first = self.deployment()
        first.up(); first.close()
        second = self.deployment()
        second.up(); second.close()
        self.assertEqual(len(self.ray.submitted), 1)
        self.assertEqual([c[:2] for c in self.management.calls],
                         [('models', 'model-a'), ('controllers', 'controller-a')])
        self.assertEqual(self.management.calls[0][2]['expected_job_id'], None)
        self.assertIn('python -m ride serve', self.ray.submitted[0]['entrypoint'])
        self.assertEqual(self.ray.submitted[0]['entrypoint_num_gpus'], 0)

    def test_changed_plan_rejected_before_any_effect(self):
        item = self.deployment(); item.close()
        changed = plan(); changed['model_services'][0]['model'] = '/other'
        with self.assertRaisesRegex(ValueError, 'conflict'):
            self.deployment(changed)
        self.assertEqual(self.ray.submitted, [])

    def test_unknown_management_submission_is_not_retried(self):
        item = self.deployment(); self.ray.fail = True
        with self.assertRaises(OSError):
            item.up()
        item.close(); item = self.deployment()
        with self.assertRaises(UnknownOutcome):
            item.up()
        item.close()
        self.assertEqual(len(self.ray.submitted), 1)
        self.assertEqual(self.management.calls, [])

    def test_wrong_management_identity_blocks_models(self):
        item = self.deployment()
        self.management.identity['workspace'] = 'foreign'
        with self.assertRaisesRegex(ValueError, 'identity'):
            item.up()
        item.close()
        self.assertEqual(self.management.calls, [])

    def test_unready_model_blocks_controller_but_can_resume_waiting(self):
        item = self.deployment()
        original = self.management.models.describe
        self.management.models.describe = lambda name: dict(original(name), ready=False)
        with self.assertRaises(TimeoutError):
            item.up()
        self.assertEqual([c[0] for c in self.management.calls], ['models'])
        self.management.models.describe = original
        item.up(); item.close()
        self.assertEqual(len(self.management.calls), 2)

    def test_stop_only_recorded_jobs_in_reverse_dependency_order(self):
        item = self.deployment(); item.up(); item.stop(); item.close()
        self.assertEqual([r[0] for r in self.management.stopped], ['controllers', 'models'])
        self.assertEqual(self.ray.stopped, [self.ray.submitted[0]['submission_id']])
        self.assertEqual(self.commands, [])  # Never ray down / ray stop.

    def test_foreign_replacement_is_not_stopped(self):
        item = self.deployment(); item.up()
        self.management.records[('controllers', 'controller-a')]['job_id'] = 'foreign'
        with self.assertRaisesRegex(ValueError, 'identity'):
            item.stop()
        item.close()
        self.assertEqual(self.management.stopped, [])
        self.assertEqual(self.ray.stopped, [])

    def test_repeated_stop_and_up_after_stop_are_safe(self):
        item = self.deployment(); item.up(); item.stop(); item.stop()
        with self.assertRaisesRegex(ValueError, 'stopp'):
            item.up()
        item.close()
        self.assertEqual(len(self.ray.stopped), 1)

    def test_cluster_config_changed_after_validation_never_runs(self):
        path = self.root / 'cluster.json'
        path.write_text(json.dumps({'cluster_name': 'myc-test',
            'provider': {'type': 'local', 'head_ip': 'head', 'worker_ips': []}}))
        config = plan(); config['ray'].update(mode='bootstrap', cluster_config=str(path))
        item = self.deployment(config)
        path.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'changed'):
            item.up()
        item.close()
        self.assertEqual(self.commands, [])
        self.assertEqual(self.ray.submitted, [])

    def test_cluster_bootstrap_uses_official_launcher_and_frozen_config(self):
        path = self.root / 'cluster.json'
        path.write_text(json.dumps({'cluster_name': 'myc-test',
            'provider': {'type': 'local', 'head_ip': 'head', 'worker_ips': ['worker']}}))
        config = plan(); config['ray'].update(mode='bootstrap', cluster_config=str(path))
        item = self.deployment(config); item.up(); item.up(); item.close()
        self.assertEqual(self.commands, [['ray', 'up', '-y', '--no-restart', str(path)]])
        cluster = json.loads(path.read_text()); cluster['provider']['worker_ips'] = ['other']
        path.write_text(json.dumps(cluster))
        with self.assertRaisesRegex(ValueError, 'conflict|changed'):
            self.deployment(config)

    def test_failed_bootstrap_does_not_submit_any_job_or_blindly_retry(self):
        path = self.root / 'cluster.json'
        path.write_text(json.dumps({'cluster_name': 'myc-test',
            'provider': {'type': 'local', 'head_ip': 'head', 'worker_ips': []}}))
        config = plan(); config['ray'].update(mode='bootstrap', cluster_config=str(path))
        item = self.deployment(config)
        def fail(args):
            raise OSError('SSH failure')
        item.run = fail
        with self.assertRaises(OSError): item.up()
        with self.assertRaises(UnknownOutcome): item.up()
        item.close()
        self.assertEqual(self.ray.submitted, [])

    def test_validation_before_effects(self):
        invalid = []
        for field, value in [('name', '../bad'), ('readiness_timeout_seconds', -1)]:
            item = plan(); item[field] = value; invalid.append(item)
        item = plan(); item['management']['state_file'] = 'relative'; invalid.append(item)
        item = plan(); item['controllers'][0]['model_service'] = 'unknown'; invalid.append(item)
        item = plan(); item['controllers'][0]['backend'] = 'http://wrong:8000'; invalid.append(item)
        item = plan(); item['model_services'].append(copy.deepcopy(item['model_services'][0])); invalid.append(item)
        item = plan(); item['management']['runtime_env']['working_dir'] = '/other'; invalid.append(item)
        item = plan(); item['model_services'][0]['resources'] = {'NPU': 1}; invalid.append(item)
        item = plan(); item['model_services'][0]['resources']['NPU'] = -1; invalid.append(item)
        for config in invalid:
            with self.subTest(config=config), self.assertRaises(ValueError):
                validate_plan(config)

    def test_explicit_model_binding_uses_public_peer_api_once(self):
        from unittest.mock import patch
        config = plan()
        config['model_bindings'] = [{'controller': 'controller-a', 'model_services': ['model-a'],
                                     'token_env': 'TEST_BINDING_TOKEN'}]
        calls = []
        class Peer:
            def get(self, path):
                return {'protocol_version': '1', 'predeclared_pool_membership': True}
            def post(self, path, body):
                calls.append((path, body))
                return dict(body, activated=True)
        with patch.dict('os.environ', TEST_BINDING_TOKEN='fixture-peer-token'):
            item = self.deployment(config)
            item.peer_factory = lambda *args, **kwargs: Peer()
            item.up(); item.up(); item.close()
        self.assertEqual(calls, [('/control/activate', {'replica': 'model-a',
                            'job_id': 'models-model-a', 'endpoint': 'http://worker:8000'})])

    def test_missing_binding_credentials_blocks_all_remote_effects(self):
        config = plan()
        config['model_bindings'] = [{'controller': 'controller-a', 'model_services': ['model-a'],
                                     'token_env': 'MISSING_DEPLOYMENT_TOKEN'}]
        item = self.deployment(config)
        with self.assertRaisesRegex(ValueError, 'token'):
            item.up()
        item.close()
        self.assertEqual(self.ray.submitted, [])

    def test_public_sdk_real_http_and_runtime_keep_model_job_identity(self):
        import threading
        from http.server import ThreadingHTTPServer
        from ride.runtime import Runtime
        from ride.server import handler
        from ride.sdk import RideClient

        server = ThreadingHTTPServer(('127.0.0.1', 0), lambda *args: None)
        config = plan(); config['controllers'] = []
        config['management']['endpoint'] = 'http://127.0.0.1:' + str(server.server_port)
        config['management']['resources'] = {'node:127.0.0.1': 0.001}
        item = Deployment(config, self.root, ray_factory=lambda address: self.ray)
        runtime_config = {'name': item.identity, 'workspace': config['name'],
                          'state_file': str(self.root / 'runtime.json')}
        runtime = Runtime(runtime_config, self.ray)
        self.ray.get_job_status = lambda job: self.ray.get_job_info(job).status
        # Runtime's Ray client also submits models without deployment metadata.
        original_info = self.ray.get_job_info
        def info(job):
            self.ray.jobs[job].setdefault('metadata', {})
            return original_info(job)
        self.ray.get_job_info = info
        runtime.health = lambda endpoint: True
        server.RequestHandlerClass = handler(runtime_config, runtime)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            item.up(); item.up()
            client = RideClient(config['management']['endpoint'])
            job = client.models.describe('model-a')['job_id']
            self.assertEqual(len(self.ray.submitted), 2)  # management + model
            restored = Runtime(runtime_config, self.ray); restored.health = runtime.health
            server.RequestHandlerClass = handler(runtime_config, restored)
            item.up()
            self.assertEqual(client.models.describe('model-a')['job_id'], job)
            item.stop()
            self.assertEqual(self.ray.stopped[0], job)
        finally:
            item.close(); server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__':
    unittest.main()
