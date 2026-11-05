"""Devbox process ownership: no Ray import, restart adoption, stop isolation."""
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from ride.runtime import Runtime


class LocalController(unittest.TestCase):
    def config(self, root):
        return {'deployment': 'local', 'workspace': 'test-devbox',
                'state_file': str(root / 'state.json'), 'controllers': []}

    def spec(self):
        return {'type': 'request-throttling', 'executor': 'local',
                'backend': 'http://127.0.0.1:8000', 'endpoint': 'http://127.0.0.1:9000'}

    def test_no_ray_required_and_reject_local_model_or_ray_resources(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Runtime(self.config(Path(directory)))
            with self.assertRaisesRegex(ValueError, 'Controller'):
                runtime.start_instance('model_services', 'model', {'type':'vllm','model':'x','endpoint':'http://x'})
            with self.assertRaises(ValueError):
                runtime.start_instance('controllers', 'bad', dict(self.spec(), resources={'NPU':1}))
            self.assertEqual(runtime.state['jobs'], {})

    def test_actual_process_restart_adoption_idempotence_logs_and_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = self.config(root)
            runtime = Runtime(config)
            command = shlex.join([sys.executable, '-u', '-c',
                'import time; print("controller-fixture-started", flush=True); time.sleep(60)'])
            try:
                with patch('ride.runtime.command', return_value=command):
                    first = runtime.start_instance('controllers', 'mine', self.spec())
                    again = runtime.start_instance('controllers', 'mine')
                self.assertEqual(first['job_id'], again['job_id'])
                restored = Runtime(config)
                for _ in range(100):
                    if 'controller-fixture-started' in restored.logs('controllers','mine')['logs']:
                        break
                    time.sleep(.02)
                self.assertIn('controller-fixture-started', restored.logs('controllers','mine')['logs'])
                self.assertEqual(restored.client.get_job_status(first['job_id']).value, 'RUNNING')
                with self.assertRaises(ValueError): restored.stop('unowned')
                restored.stop('mine')
                self.assertEqual(restored.client.get_job_status(first['job_id']).value, 'STOPPED')
                self.assertFalse(restored.health('http://127.0.0.1:1'))
            finally:
                if runtime.state['jobs'].get('mine'):
                    runtime.stop('mine')

    def test_pid_identity_mismatch_refuses_signal_and_duplicate_submit(self):
        from ride.local_process import LocalProcessClient
        with tempfile.TemporaryDirectory() as directory:
            client = LocalProcessClient(Path(directory))
            record = Path(directory)/'owned'
            record.mkdir()
            (record/'process.json').write_text(json.dumps({'pid':os.getpid(),'token':'foreign','status':'RUNNING','birth':'invalid'}))
            with patch('ride.local_process.os.killpg') as signal:
                with self.assertRaises(RuntimeError): client.stop_job('owned')
                signal.assert_not_called()
            with self.assertRaises((ValueError,FileExistsError)):
                client.submit_job(submission_id='owned',entrypoint='python -V',runtime_env={},entrypoint_resources={})

    def test_failed_child_is_not_reported_running(self):
        from ride.local_process import LocalProcessClient
        with tempfile.TemporaryDirectory() as directory:
            client = LocalProcessClient(Path(directory))
            client.submit_job(submission_id='failure', entrypoint=shlex.join([sys.executable,'-c','raise SystemExit(7)']), runtime_env={}, entrypoint_resources={})
            for _ in range(100):
                if client.get_job_status('failure').value == 'FAILED': break
                time.sleep(.02)
            self.assertEqual(client.get_job_status('failure').value,'FAILED')
            self.assertFalse(client.stop_job('failure'))
            client.children['failure'].wait(timeout=5)

    def test_reject_runtime_installation_and_preserve_external_process(self):
        import subprocess
        from ride.local_process import LocalProcessClient
        with tempfile.TemporaryDirectory() as directory:
            client=LocalProcessClient(Path(directory))
            with self.assertRaises(ValueError):
                client.submit_job(submission_id='bad',entrypoint='python -V',runtime_env={'pip':['ray']},entrypoint_resources={})
            self.assertFalse((Path(directory)/'bad').exists())
            other=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])
            try:
                client.submit_job(submission_id='mine',entrypoint=shlex.join([sys.executable,'-c','import time; time.sleep(30)']),runtime_env={},entrypoint_resources={})
                client.stop_job('mine')
                self.assertIsNone(other.poll())
            finally:
                other.terminate();other.wait(timeout=5)

    def test_cli_accepts_local_executor(self):
        from ride.__main__ import parser
        self.assertEqual(parser().parse_args(['serve','--executor','local']).executor,'local')

    def test_local_snapshot_discloses_external_model_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime=Runtime(self.config(Path(directory)))
            self.assertFalse(runtime.snapshot()['capabilities']['start_model_service'])

    def test_process_identity_ignores_terminal_width(self):
        from ride.local_process import LocalProcessClient
        with tempfile.TemporaryDirectory() as directory:
            client = LocalProcessClient(Path(directory))
            client.submit_job(submission_id='long-process-identity', entrypoint=shlex.join([sys.executable,'-c','import time;time.sleep(5)']),runtime_env={},entrypoint_resources={})
            try:
                with patch.dict(os.environ, {'COLUMNS':'80'}):
                    self.assertEqual(client.get_job_status('long-process-identity').value, 'RUNNING')
                    client.stop_job('long-process-identity')
            finally:
                client.children['long-process-identity'].wait(timeout=10)
