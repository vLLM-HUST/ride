import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('deployment_payload',
    Path(__file__).resolve().parents[1] / 'scripts/deployment_payload.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class PayloadTests(unittest.TestCase):
    def test_other_cluster_pod_rejected_before_exec(self):
        plan = dict(namespace='test', cluster='owned', cluster_uid='c', pod='p',
                    pod_uid='p-id', files=[], destination='/workspace/home/test')
        records = [{'metadata': {'uid': 'c'}}, {'metadata': {'uid': 'p-id',
                    'labels': {'ray.io/cluster': 'other'}}}]
        with patch.object(module.subprocess, 'check_output',
                          side_effect=[json.dumps(x) for x in records]) as calls:
            with self.assertRaisesRegex(ValueError, 'not a member'):
                module.prepare_payload(plan)
            self.assertEqual(calls.call_count, 2)

    def test_existing_conflict_and_traversal_preserve_content(self):
        with tempfile.TemporaryDirectory() as directory:
            code = module.REMOTE.replace('/workspace/home/', directory + '/')
            destination = directory + '/payload'
            def item(data, path='config.json'):
                return dict(path=path, data=base64.b64encode(data).decode(),
                            sha256=hashlib.sha256(data).hexdigest())
            def run(files):
                return subprocess.run([sys.executable, '-c', code],
                    input=json.dumps(dict(destination=destination, files=files)).encode(),
                    capture_output=True)
            self.assertEqual(run([item(b'original')]).returncode, 0)
            self.assertEqual(run([item(b'original')]).returncode, 0)
            self.assertNotEqual(run([item(b'changed')]).returncode, 0)
            self.assertNotEqual(run([item(b'escape', '../outside')]).returncode, 0)
            self.assertEqual(Path(destination, 'config.json').read_bytes(), b'original')
            self.assertFalse(Path(directory, 'outside').exists())
