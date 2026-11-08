import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import io
import os
import tarfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('deployment_payload',
    Path(__file__).resolve().parents[1] / 'scripts/deployment_payload.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class PayloadTests(unittest.TestCase):
    def test_private_payload_mode_through_public_prepare_and_remote_readback(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();source=root/'source';source.write_bytes(b'private-configuration')
            plan=dict(namespace='tenant',cluster='owned',cluster_uid='cluster-id',pod='head',pod_uid='pod-id',
                workspace_root=str(root),destination=str(root/'payload'),files=[dict(path='token',
                source=str(source),sha256=hashlib.sha256(source.read_bytes()).hexdigest(),mode=0o600)])
            def command(argv,**kwargs):
                if 'get' in argv:
                    if 'raycluster' in argv:return json.dumps({'metadata':{'uid':'cluster-id'}})
                    return json.dumps({'metadata':{'uid':'pod-id','labels':{'ray.io/cluster':'owned'}}})
                result=subprocess.run([sys.executable,'-c',module.REMOTE],input=kwargs['input'],capture_output=True,check=True)
                return result.stdout
            with patch.object(module.subprocess,'check_output',side_effect=command):
                receipt=module.prepare_payload(plan)
                repeated=module.prepare_payload(plan)
            self.assertEqual((root/'payload/token').stat().st_mode & 0o777,0o600)
            self.assertEqual(receipt['files'][0]['mode'],0o600)
            self.assertEqual(repeated,receipt)

    def test_public_prepare_forwards_explicit_workspace_root(self):
        plan=dict(namespace='tenant-b',cluster='owned',cluster_uid='cluster-id',pod='head',pod_uid='pod-id',files=[],workspace_root='/mnt/tenant-b',destination='/mnt/tenant-b/deployment')
        records=[json.dumps({'metadata':{'uid':'cluster-id'}}),json.dumps({'metadata':{'uid':'pod-id','labels':{'ray.io/cluster':'owned'}}}),b'{"files":[]}']
        with patch.object(module.subprocess,'check_output',side_effect=records) as calls:
            module.prepare_payload(plan)
            submitted=json.loads(calls.call_args.kwargs['input'])
            self.assertEqual(submitted['workspace_root'],plan['workspace_root'])

    def test_same_remote_code_supports_configured_workspace_roots(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory).resolve()
            for relative in ['workspace/home', 'home/inference', 'mnt/persistent']:
                with self.subTest(root=relative):
                    workspace=base/relative;workspace.mkdir(parents=True)
                    payload={'workspace_root':str(workspace),'destination':str(workspace/'deployment'), 'files':[{'path':'config.json','data':base64.b64encode(b'frozen').decode(),'sha256':hashlib.sha256(b'frozen').hexdigest(),'mode':0o644}]}
                    result=subprocess.run([sys.executable,'-c',module.REMOTE],input=json.dumps(payload).encode(),capture_output=True)
                    self.assertEqual(result.returncode,0,result.stderr)
                    self.assertEqual((workspace/'deployment/config.json').read_bytes(),b'frozen')

    def test_configured_workspace_root_keeps_containment_and_symlink_guards(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory).resolve();workspace=base/'workspace';workspace.mkdir()
            item={'path':'config.json','data':base64.b64encode(b'frozen').decode(),'sha256':hashlib.sha256(b'frozen').hexdigest(),'mode':0o644}
            cases=[('root-filesystem','/',str(workspace/'deployment')),('relative','relative',str(workspace/'deployment')),('sibling-prefix',str(workspace),str(base/'workspace-other/deployment')),('traversal',str(workspace),str(workspace/'../escaped'))]
            (workspace/'link').symlink_to(base,target_is_directory=True)
            cases.append(('symlink',str(workspace),str(workspace/'link/deployment')))
            for name,root,destination in cases:
                with self.subTest(case=name):
                    result=subprocess.run([sys.executable,'-c',module.REMOTE],input=json.dumps({'workspace_root':root,'destination':destination,'files':[item]}).encode(),capture_output=True)
                    self.assertNotEqual(result.returncode,0)
            self.assertFalse((base/'escaped').exists());self.assertFalse((base/'workspace-other').exists());self.assertFalse((base/'deployment').exists())

    def test_remote_partial_publication_never_leaves_a_partial_final_file(self):
        with tempfile.TemporaryDirectory() as directory:
            directory=str(Path(directory).resolve());root=directory+'/payload'
            code=module.REMOTE
            raw=b'frozen-data';item=dict(path='config.json',data=base64.b64encode(raw).decode(),sha256=hashlib.sha256(raw).hexdigest(),mode=0o644)
            payload=json.dumps(dict(workspace_root=directory,destination=root,files=[item])).encode()
            interrupted='import os\ndef stopped(*args,**kwargs):raise OSError("publication interrupted")\nos.link=stopped\n'+code
            first=subprocess.run([sys.executable,'-c',interrupted],input=payload,capture_output=True)
            self.assertNotEqual(first.returncode,0)
            self.assertFalse(Path(root,'config.json').exists())
            second=subprocess.run([sys.executable,'-c',code],input=payload,capture_output=True)
            self.assertEqual(second.returncode,0,second.stderr)
            self.assertEqual(Path(root,'config.json').read_bytes(),raw)

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
            # macOS /var is a symlink; test an ordinary directory, not the
            # separately forbidden symlink-destination case.
            directory = str(Path(directory).resolve())
            code = module.REMOTE
            destination = directory + '/payload'
            def item(data, path='config.json'):
                return dict(path=path, data=base64.b64encode(data).decode(),
                            sha256=hashlib.sha256(data).hexdigest())
            def run(files):
                return subprocess.run([sys.executable, '-c', code],
                    input=json.dumps(dict(workspace_root=directory,destination=destination, files=files)).encode(),
                    capture_output=True)
            self.assertEqual(run([item(b'original')]).returncode, 0)
            self.assertEqual(run([item(b'original')]).returncode, 0)
            self.assertNotEqual(run([item(b'changed')]).returncode, 0)
            self.assertNotEqual(run([item(b'escape', '../outside')]).returncode, 0)
            self.assertEqual(Path(destination, 'config.json').read_bytes(), b'original')
            self.assertFalse(Path(directory, 'outside').exists())

    def test_explicit_executable_mode_and_invalid_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            directory=str(Path(directory).resolve())
            code=module.REMOTE
            root=directory+'/payload'
            def run(mode):
                data=b'#!/bin/sh\nexit 0\n'
                item=dict(path='service',data=base64.b64encode(data).decode(),
                          sha256=hashlib.sha256(data).hexdigest(),mode=mode)
                return subprocess.run([sys.executable,'-c',code],input=json.dumps(
                    dict(workspace_root=directory,destination=root,files=[item])).encode(),capture_output=True)
            self.assertEqual(run(0o755).returncode,0)
            self.assertEqual(Path(root,'service').stat().st_mode & 0o777,0o755)
            self.assertEqual(run(0o755).returncode,0)
            for mode in (0o4755,0o777,True,'755'):
                with self.subTest(mode=mode):self.assertNotEqual(run(mode).returncode,0)
            self.assertEqual(Path(root,'service').stat().st_mode & 0o777,0o755)


class StagingTests(unittest.TestCase):
    identity = {'run_id': 'myc-stage', 'workspace_id': 'software-workspace', 'plan_sha256': 'a'*64}

    def archive(self, root, members=None):
        path = root/'source.tar.gz'
        with tarfile.open(path, 'w:gz') as archive:
            for name, data, kind in members or [('payload/a', b'first', 'file'), ('payload/b', b'second', 'file')]:
                info = tarfile.TarInfo(name); info.mode = 0o644
                if kind == 'file':
                    info.size = len(data); archive.addfile(info, io.BytesIO(data))
                else:
                    info.type = tarfile.SYMTYPE if kind == 'symlink' else tarfile.LNKTYPE
                    info.linkname = 'elsewhere'; archive.addfile(info)
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def test_identity_reuse_and_unknown_existing_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve(); destination=root/'owned'
            module.initialize_staging(destination,self.identity)
            marker=destination/'.ride-staging.json'; original=marker.read_bytes(); stamp=marker.stat().st_mtime_ns
            module.initialize_staging(destination,self.identity)
            self.assertEqual((marker.read_bytes(),marker.stat().st_mtime_ns),(original,stamp))
            with self.assertRaises(ValueError):module.initialize_staging(destination,dict(self.identity,workspace_id='other'))
            unknown=root/'unknown';unknown.mkdir()
            with self.assertRaises(ValueError):module.initialize_staging(unknown,self.identity)
            self.assertEqual(list(unknown.iterdir()),[])

    def test_matching_partial_and_complete_stage_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve(); destination=root/'owned';module.initialize_staging(destination,self.identity)
            path,sha=self.archive(root);(destination/'payload').mkdir();a=destination/'payload/a';a.write_bytes(b'first')
            os.utime(a,ns=(1_000_000_000,1_000_000_000));stamp=a.stat().st_mtime_ns
            first=module.stage_archive(path,destination,self.identity,sha)
            second=module.stage_archive(path,destination,self.identity,sha)
            self.assertEqual(first['files'],second['files']);self.assertEqual(a.stat().st_mtime_ns,stamp)
            self.assertEqual((destination/'payload/b').read_bytes(),b'second')

    def test_wrong_hash_and_conflicting_existing_file_preserve_everything(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();destination=root/'owned';module.initialize_staging(destination,self.identity)
            path,sha=self.archive(root)
            with self.assertRaises(ValueError):module.stage_archive(path,destination,self.identity,'b'*64)
            self.assertFalse((destination/'payload').exists())
            (destination/'payload').mkdir();(destination/'payload/b').write_bytes(b'original')
            with self.assertRaises(ValueError):module.stage_archive(path,destination,self.identity,sha)
            self.assertFalse((destination/'payload/a').exists());self.assertEqual((destination/'payload/b').read_bytes(),b'original')

    def test_unsafe_archive_is_rejected_before_any_file_write(self):
        for bad in [('../outside',b'bad','file'),('payload/link',b'','symlink'),('payload/link',b'','hardlink'),('.ride-staging.json',b'bad','file'),('payload/a',b'duplicate','file')]:
            with self.subTest(bad=bad),tempfile.TemporaryDirectory() as directory:
                root=Path(directory).resolve();destination=root/'owned';module.initialize_staging(destination,self.identity)
                path,sha=self.archive(root,[('payload/a',b'first','file'),bad])
                with self.assertRaises(ValueError):module.stage_archive(path,destination,self.identity,sha)
                self.assertFalse((destination/'payload/a').exists());self.assertFalse((root/'outside').exists())

    def test_symlink_and_exposed_staging_root_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();destination=root/'owned';module.initialize_staging(destination,self.identity)
            foreign=root/'foreign';foreign.mkdir();(destination/'payload').symlink_to(foreign,target_is_directory=True)
            path,sha=self.archive(root)
            with self.assertRaises(ValueError):module.stage_archive(path,destination,self.identity,sha)
            self.assertEqual(list(foreign.iterdir()),[])
            destination.chmod(0o777)
            with self.assertRaises(ValueError):module.initialize_staging(destination,self.identity)

    def test_interrupted_atomic_publication_can_resume_without_partial_final_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();destination=root/'owned';module.initialize_staging(destination,self.identity)
            path,sha=self.archive(root)
            with patch.object(module.os,'link',side_effect=OSError('interrupted publication')):
                with self.assertRaises(OSError):module.stage_archive(path,destination,self.identity,sha)
            self.assertFalse((destination/'payload/a').exists())
            module.stage_archive(path,destination,self.identity,sha)
            self.assertEqual((destination/'payload/a').read_bytes(),b'first')
            self.assertEqual((destination/'payload/b').read_bytes(),b'second')

    def test_another_archive_cannot_be_appended_under_same_deployment_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();destination=root/'owned';module.initialize_staging(destination,self.identity)
            path,sha=self.archive(root);module.stage_archive(path,destination,self.identity,sha)
            path,changed_sha=self.archive(root,[('payload/c',b'changed archive','file')])
            with self.assertRaisesRegex(ValueError,'archive identity changed'):
                module.stage_archive(path,destination,self.identity,changed_sha)
            self.assertFalse((destination/'payload/c').exists())

    def test_corrupt_marker_and_identity_validation_do_not_reset_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();destination=root/'owned'
            with self.assertRaises(ValueError):module.initialize_staging(destination,dict(self.identity,plan_sha256='not-a-sha'))
            self.assertFalse(destination.exists())
            module.initialize_staging(destination,self.identity)
            marker=destination/'.ride-staging.json';marker.write_text('unknown original')
            with self.assertRaises(ValueError):module.initialize_staging(destination,self.identity)
            self.assertEqual(marker.read_text(),'unknown original')
