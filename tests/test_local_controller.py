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
                runtime.close()
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
                owner = locals().get('restored', runtime)
                if owner.state['jobs'].get('mine') and not owner._closed:
                    owner.stop('mine')
                owner.close()

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

class ProcessIdentityWidthTests(unittest.TestCase):
    def test_full_command_is_required_for_long_owned_worker_identity(self):
        from ride.local_process import _matches
        from types import SimpleNamespace
        directory=Path('/tmp')/('owned-controller-'+('x'*120))
        record={'pid':321,'birth':'fixture-birth','token':'fixture-ownership-token'}
        full='python -m ride.local_process --worker '+str(directory)+' --token '+record['token']
        def ps(command,**kwargs):
            if 'lstart=' in command:return SimpleNamespace(stdout='fixture-birth\n')
            return SimpleNamespace(stdout=full if '-ww' in command else full[:80])
        with patch('ride.local_process.os.getpgid',return_value=321),patch('ride.local_process.subprocess.run',side_effect=ps):
            self.assertTrue(_matches(record,directory))

class ProcessExitRaceTests(unittest.TestCase):
    def _client(self,directory):
        from ride.local_process import LocalProcessClient
        client=LocalProcessClient(directory);root=Path(directory)/'owned';root.mkdir()
        record={'status':'RUNNING','pid':321,'birth':'fixture-birth','token':'fixture-token'}
        (root/'process.json').write_text(json.dumps(record))
        return client,root,record

    def test_completed_worker_between_snapshot_and_identity_check_is_terminal(self):
        with tempfile.TemporaryDirectory() as directory:
            client,root,record=self._client(directory)
            def exited(*args):
                (root/'process.json').write_text(json.dumps(dict(record,status='FAILED',exit_code=7)))
                return False
            with patch('ride.local_process._matches',side_effect=exited):
                self.assertEqual(client.get_job_status('owned').value,'FAILED')

    def test_completed_worker_during_stop_is_not_signalled(self):
        with tempfile.TemporaryDirectory() as directory:
            client,root,record=self._client(directory)
            def exited(*args):
                (root/'process.json').write_text(json.dumps(dict(record,status='SUCCEEDED',exit_code=0)))
                return False
            with patch('ride.local_process._matches',side_effect=exited),patch('ride.local_process.os.killpg') as signal:
                self.assertFalse(client.stop_job('owned'));signal.assert_not_called()

    def test_replaced_terminal_identity_is_still_unknown_and_never_signalled(self):
        with tempfile.TemporaryDirectory() as directory:
            client,root,record=self._client(directory)
            def replaced(*args):
                (root/'process.json').write_text(json.dumps(dict(record,status='FAILED',token='foreign')))
                return False
            with patch('ride.local_process._matches',side_effect=replaced),patch('ride.local_process.os.killpg') as signal:
                with self.assertRaises(RuntimeError):client.stop_job('owned')
                signal.assert_not_called()
