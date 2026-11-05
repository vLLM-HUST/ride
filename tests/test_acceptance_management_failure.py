"""A terminated management Job must fail before the readiness deadline."""
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


class ManagementFailureTests(unittest.TestCase):
    def test_failed_job_aborts_without_waiting_for_http_timeout(self):
        path = Path(__file__).resolve().parents[1] / 'scripts/acceptance_entry.py'
        spec = importlib.util.spec_from_file_location('acceptance_entry_under_test', path)
        entry = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(entry)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / 'config.json'
            config.write_text(json.dumps({'controllers': [], 'model_services': []}))
            plan = root / 'plan.json'
            plan.write_text(json.dumps({'ray_address': 'http://ray:8265',
                'address': 'http://ride:19100', 'config': str(config),
                'management_job_id': 'owned-management', 'listen': '0.0.0.0:19100'}))
            def unavailable(*args, **kwargs):
                raise OSError('management API never started')
            def response(request, **kwargs):
                status = {'status': 'FAILED'} if request.full_url.endswith('/owned-management') else {}
                return io.BytesIO(json.dumps(status).encode())
            with patch.dict(sys.modules, {'ride.__main__': types.SimpleNamespace(request=unavailable),
                    'deployment_identity': types.SimpleNamespace(verify_live=lambda p: {'verified': True})}), \
                    patch.object(sys, 'argv', ['acceptance_entry.py', 'deploy', '--plan', str(plan), '--output', str(root / 'evidence')]), \
                    patch.object(entry, 'urlopen', side_effect=response), \
                    patch.object(entry.time, 'sleep', side_effect=AssertionError('must not wait on a failed job')):
                with self.assertRaisesRegex(RuntimeError, 'Management Job terminated'):
                    entry.main()
            ledger = json.loads((root / 'evidence/deploy.json').read_text())
            self.assertEqual(ledger['status'], 'FAIL')
            self.assertEqual(ledger['actions'][-1]['status'], 'FAIL')


if __name__ == '__main__':
    unittest.main()
