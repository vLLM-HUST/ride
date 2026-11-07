"""Readable component identities and native Ray driver registration."""
import json
from pathlib import Path
import shlex
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from ride.runtime import Runtime
from ride.job_submission import component_name, ray_entrypoint, next_execution_submission_id


class Client:
    def __init__(self):
        self.submissions = []
        self.status = 'RUNNING'
    def submit_job(self, **options):
        self.submissions.append(options)
    def get_job_status(self, submission_id):
        return SimpleNamespace(value=self.status)
    def get_job_info(self, submission_id):
        return SimpleNamespace(job_id='02000000', submission_id=submission_id)


class JobIdentityTests(unittest.TestCase):
    def test_full_component_names_and_explicit_override(self):
        for controller_type, expected in [
            ('request-throttling-managed', 'Request Throttling Controller'),
            ('kv-control', 'Key Value Cache Controller'),
            ('instance-scaling', 'Instance Autoscaling Controller'),
        ]:
            self.assertEqual(component_name('controllers', {'type': controller_type, 'id': 'primary'}), expected)
        self.assertEqual(component_name('model_services', {'id': 'replica-1', 'display_name': 'Inference Model Replica 1'}), 'Inference Model Replica 1')

    def test_execution_number_persists_but_idempotence_does_not_increment(self):
        with tempfile.TemporaryDirectory() as directory:
            config = {'workspace': 'myc-study', 'state_file': str(Path(directory) / 'state.json')}
            client = Client()
            runtime = Runtime(config, client)
            spec = {'type': 'vllm', 'model': '/models/model', 'endpoint': 'http://model.invalid',
                    'display_name': 'Inference Model Replica 1'}
            first = runtime.start_instance('model_services', 'inference-model-replica-1', spec)
            runtime.start_model_service('inference-model-replica-1')
            self.assertEqual(len(client.submissions), 1)
            submitted = client.submissions[0]
            self.assertEqual(submitted['submission_id'], 'myc-study-model-service-inference-model-replica-1-execution-1')
            self.assertEqual(submitted['metadata']['job_name'], 'Inference Model Replica 1')
            self.assertEqual(submitted['metadata']['ride.execution'], '1')
            self.assertIn('ride.ray_job', submitted['entrypoint'])
            record = runtime.describe('model_services', 'inference-model-replica-1')
            self.assertEqual(record['submission_id'], first['job_id'])  # legacy compatibility alias
            self.assertEqual(record['ray_job_id'], '02000000')
            self.assertEqual(record['display_name'], 'Inference Model Replica 1')
            runtime.close()
            client.status = 'STOPPED'
            restored = Runtime(config, client)
            try:
                second = restored.start_model_service('inference-model-replica-1')
                self.assertTrue(second['job_id'].endswith('-execution-2'))
                self.assertEqual(client.submissions[-1]['metadata']['job_name'], submitted['metadata']['job_name'])
            finally:
                restored.close()

    def test_no_native_id_is_never_fabricated_from_submission(self):
        with tempfile.TemporaryDirectory() as directory:
            client = Client()
            client.get_job_info = lambda _: SimpleNamespace(job_id=None)
            runtime = Runtime({'workspace': 'myc-study', 'state_file': str(Path(directory) / 'state.json')}, client)
            try:
                runtime.start_instance('model_services', 'model', {'type': 'vllm', 'model': 'fixture', 'endpoint': 'http://model.invalid'})
                record = runtime.describe('model_services', 'model')
                self.assertIsNone(record['ray_job_id'])
                self.assertIsNotNone(record['submission_id'])
            finally:
                runtime.close()

    def test_invalid_display_name_rejected_before_submission(self):
        with tempfile.TemporaryDirectory() as directory:
            client = Client()
            runtime = Runtime({'state_file': str(Path(directory) / 'state.json')}, client)
            try:
                for value in ['', 'bad\nname', 3, 'x' * 161]:
                    with self.assertRaises(ValueError):
                        runtime.start_instance('model_services', 'model', {'type': 'vllm', 'model': 'fixture', 'endpoint': 'http://model.invalid', 'display_name': value})
                self.assertFalse(client.submissions)
                self.assertFalse(runtime.state['jobs'])
            finally:
                runtime.close()

    def test_recovery_is_next_execution_of_same_component(self):
        self.assertEqual(next_execution_submission_id('myc-ride-control-plane-execution-1'), 'myc-ride-control-plane-execution-2')
        with self.assertRaises(ValueError):
            next_execution_submission_id('myc-management-adopt')

    def test_shared_submission_prefix_is_rejected_before_intent(self):
        with tempfile.TemporaryDirectory() as directory:
            client = Client()
            runtime = Runtime({'state_file': str(Path(directory) / 'state.json')}, client)
            specification = {'type': 'vllm', 'model': 'fixture', 'endpoint': 'http://model.invalid', 'job_name_prefix': 'myc-inference-model'}
            try:
                runtime.start_instance('model_services', 'replica-1', specification)
                with self.assertRaisesRegex(ValueError, 'distinct'):
                    runtime.start_instance('model_services', 'replica-2', specification)
                self.assertEqual(len(client.submissions), 1)
                self.assertNotIn('model-service/replica-2', runtime.state['jobs'])
            finally:
                runtime.close()

    def test_wrapper_preserves_argument_boundaries(self):
        original = ['bash', '-c', 'source "/environment path/setup.sh"; exec "$@"', 'ride-model', 'vllm', 'serve', '/models/model name']
        wrapped = shlex.split(ray_entrypoint(shlex.join(original), 'Inference Model Replica 1'))
        self.assertEqual(wrapped[wrapped.index('--') + 1:], original)

    def test_driver_connects_before_child_preserves_exit_and_shuts_down(self):
        from ride.ray_job import run
        ray = Mock()
        ray.get_runtime_context.return_value.get_job_id.return_value = '02000000'
        process = Mock(); process.pid = 123; process.wait.return_value = 7; process.poll.return_value = 7
        child = Mock(return_value=process)
        with patch('ride.ray_job.subprocess.Popen', child), patch.dict('os.environ', {'RAY_ADDRESS': '10.0.0.1:6379'}):
            self.assertEqual(run(['python', '-V'], 'Instance Autoscaling Controller', ray_module=ray), 7)
        ray.init.assert_called_once_with(address='10.0.0.1:6379')
        child.assert_called_once_with(['python', '-V'])
        ray.shutdown.assert_called_once()

    def test_driver_connection_failure_never_starts_unmanaged_child(self):
        from ride.ray_job import run
        ray = Mock()
        ray.init.side_effect = RuntimeError('connection failed')
        with patch('ride.ray_job.subprocess.Popen') as child:
            with self.assertRaises(RuntimeError):
                run(['python', '-V'], 'RIDE Control Plane', ray_module=ray)
            child.assert_not_called()

    def test_child_spawn_failure_shuts_down_driver(self):
        from ride.ray_job import run
        ray = Mock()
        ray.get_runtime_context.return_value.get_job_id.return_value = '02000000'
        with patch('ride.ray_job.subprocess.Popen', side_effect=FileNotFoundError):
            with self.assertRaises(FileNotFoundError):
                run(['missing-command'], 'RIDE Control Plane', ray_module=ray)
        ray.shutdown.assert_called_once()


class RealSignalTests(unittest.TestCase):
    def test_group_termination_is_forwarded_and_child_is_reaped(self):
        import os
        import signal
        import subprocess
        import sys
        import time
        child_code = 'import os,time; print("CHILD_PID="+str(os.getpid()), flush=True); time.sleep(60)'
        driver_code = ('from types import SimpleNamespace; from ride.ray_job import run; '
                       'ray=SimpleNamespace(init=lambda **k:None,shutdown=lambda:None,'
                       'get_runtime_context=lambda:SimpleNamespace(get_job_id=lambda:"fixture")); '
                       'raise SystemExit(run(' + repr([sys.executable, '-u', '-c', child_code]) + ', "Signal Test", ray_module=ray))')
        process = subprocess.Popen([sys.executable, '-u', '-c', driver_code],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, start_new_session=True)
        child_pid = None
        try:
            line = ''
            for _ in range(4):
                line = process.stdout.readline()
                if line.startswith('CHILD_PID='):break
            self.assertTrue(line.startswith('CHILD_PID='), line)
            child_pid = int(line.split('=')[1])
            os.killpg(process.pid, signal.SIGTERM)
            self.assertEqual(process.wait(timeout=5), 143)
            with self.assertRaises(ProcessLookupError):
                os.kill(child_pid, 0)
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
            process.stdout.close(); process.stderr.close()
