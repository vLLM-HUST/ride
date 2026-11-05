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
