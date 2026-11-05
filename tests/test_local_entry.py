import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('ride_local_entry',Path(__file__).resolve().parents[1]/'scripts/local_controller.py')
entry=importlib.util.module_from_spec(spec);spec.loader.exec_module(entry)


class LocalEntry(unittest.TestCase):
    def test_failed_controller_is_not_automatically_resubmitted(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);state=root/'state.json';state.write_text(json.dumps({'run_id':'r'}))
            config=root/'config.json';config.write_text(json.dumps({'deployment':'local','model_services':[],
                'controllers':[{'id':'c'}],'state_file':str(state),'workspace':'x'}))
            plan=root/'plan.json';plan.write_text(json.dumps({'config':str(config),
                'management_endpoint':'http://127.0.0.1:19100','readiness_timeout_seconds':.03}))
            starts=[]
            def request(address,path,body=None):
                if path.endswith('/start'):starts.append(path);return {'job_id':'failed'}
                return {'run_id':'r','workspace':'x','controllers':[{'id':'c','ready':False,'job_status':'FAILED'}]}
            class Client:
                def __init__(self,path):self.root=path;path.mkdir()
                def submit_job(self,**kwargs):return 'manager'
            with patch.object(entry,'LocalProcessClient',Client),patch.object(entry,'request',request),patch.object(entry.time,'sleep'):
                with self.assertRaises(RuntimeError):entry.run('local-start',plan,root/'evidence')
            self.assertEqual(starts,['controllers/c/start'])

    def test_restart_preserves_controllers_and_checks_adoption(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); state=root/'state.json';state.write_text(json.dumps({'run_id':'r'}))
            config=root/'config.json';config.write_text(json.dumps({'deployment':'local','model_services':[],
                'controllers':[{'id':'c'}],'state_file':str(state),'workspace':'x'}))
            plan=root/'plan.json';plan.write_text(json.dumps({'config':str(config),'management_endpoint':'http://127.0.0.1:19100','readiness_timeout_seconds':1}))
            manager=root/'state-manager';manager.mkdir()
            import hashlib
            (manager/'deployment.json').write_text(json.dumps({'config':str(config.resolve()),'sha256':hashlib.sha256(config.read_bytes()).hexdigest()}))
            calls=[];stops=[];submits=[]
            snapshots=[{'run_id':'r','workspace':'x','management_pid':10,'controllers':[{'id':'c','job_id':'same','job_status':'RUNNING','ready':True}]}]
            snapshots += [dict(snapshots[0],management_pid=20)]
            def request(address,path,body=None):
                calls.append(path)
                if len(calls)>3:return snapshots[-1]
                return snapshots[len(calls)-1]
            class Client:
                def __init__(self,path):self.root=path
                def get_job_status(self,identifier):
                    from types import SimpleNamespace
                    return SimpleNamespace(value='RUNNING')
                def stop_job(self,identifier):stops.append(identifier);return True
                def submit_job(self,**kwargs):submits.append(kwargs)
            with patch.object(entry,'LocalProcessClient',Client),patch.object(entry,'request',request):
                entry.run('local-restart',plan,root/'evidence')
            self.assertTrue(all(path=='status' for path in calls))
            self.assertEqual(stops,['ride-local-manager'])
            self.assertEqual(len(submits),1)
            self.assertNotEqual(submits[0]['submission_id'],'ride-local-manager')
            self.assertEqual(json.loads((root/'evidence/local-restart-result.json').read_text())['status'],'PASS')

    def test_unknown_action_cannot_stop_controllers(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(entry,'LocalProcessClient') as client:
                with self.assertRaisesRegex(ValueError,'Unsupported'):
                    entry.run('typo',Path(directory)/'absent.json',Path(directory)/'out')
                client.assert_not_called()

    def test_restart_requires_same_config_before_signaling(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);state=root/'state.json';state.write_text(json.dumps({'run_id':'r'}))
            config=root/'config.json';config.write_text(json.dumps({'deployment':'local','model_services':[],
                'controllers':[{'id':'c'}],'state_file':str(state),'workspace':'x'}))
            plan=root/'plan.json';plan.write_text(json.dumps({'config':str(config),'management_endpoint':'http://127.0.0.1:19100','readiness_timeout_seconds':1}))
            manager=root/'state-manager';manager.mkdir();(manager/'deployment.json').write_text('{}')
            class Client:
                def __init__(self,path):self.root=path
                def stop_job(self,identifier):raise AssertionError('must not signal')
                def submit_job(self,**kwargs):raise AssertionError('must not submit')
            with patch.object(entry,'LocalProcessClient',Client),patch.object(entry,'request') as request:
                with self.assertRaisesRegex(ValueError,'configuration conflict'):
                    entry.run('local-restart',plan,root/'evidence')
                request.assert_not_called()
