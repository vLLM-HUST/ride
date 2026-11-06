import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest


class MachineSourceTests(unittest.TestCase):
    def test_complete_committed_source_and_manifest_exclude_uncommitted_changes(self):
        path = Path(__file__).resolve().parents[1] / 'scripts/prepare_machine_source.py'
        spec = importlib.util.spec_from_file_location('prepare_machine_source', path)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); repo = root / 'repo'; repo.mkdir()
            def git(*args):
                return subprocess.check_output(['git', '-C', str(repo), *args], stderr=subprocess.DEVNULL).decode().strip()
            git('init'); (repo / 'scripts').mkdir(); (repo / 'tests').mkdir()
            (repo / 'scripts/fixture.py').write_text('committed')
            (repo / 'tests/example.py').write_text('test fixture')
            git('add', '.'); git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-m', 'fixture')
            revision = git('rev-parse', 'HEAD')
            (repo / 'scripts/fixture.py').write_text('dirty')
            (repo / 'private-token').write_text('must not export')
            output = root / 'payload'
            result = module.prepare(repo, revision, output)
            self.assertEqual(result['revision'], revision)
            self.assertEqual((output / 'repository/scripts/fixture.py').read_text(), 'committed')
            self.assertTrue((output / 'repository/tests/example.py').is_file())
            self.assertFalse((output / 'repository/private-token').exists())
            manifest = json.loads((output / 'source-manifest.json').read_text())
            self.assertIn('scripts/fixture.py', manifest['files'])
            with self.assertRaises(FileExistsError): module.prepare(repo, revision, output)
