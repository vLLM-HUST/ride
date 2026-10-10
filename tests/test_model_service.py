import tempfile
import unittest
from pathlib import Path
from ride.runtime import Runtime
from test_runtime import Client

class ModelServiceTests(unittest.TestCase):
    def test_separate_ownership_and_restart_adoption(self):
        with tempfile.TemporaryDirectory() as d:
            cfg={'state_file':str(Path(d)/'state.json'),'controllers':[{'id':'same','entrypoint':'request-throttling','backend':'http://engine:8000','endpoint':'http://controller:9000'}], 'model_services':[{'id':'same','type':'vllm','model':'/models/model name','endpoint':'http://engine:8000'}]}
            client=Client(); runtime=Runtime(cfg,client)
            controller=runtime.start('same'); model=runtime.start_model_service('same')
            self.assertNotEqual(controller['job_id'],model['job_id'])
            runtime.start_model_service('same')
            self.assertEqual(len(client.submitted),2)
            self.assertIn("'/models/model name'",client.submitted[1]['entrypoint'])
            restored=Runtime(cfg,client); restored.stop('same')
            self.assertEqual(client.stopped,[controller['job_id']])
            restored.stop_model_service('same')
            self.assertEqual(client.stopped[-1],model['job_id'])

    def test_missing_endpoint_rejected_before_submission(self):
        with tempfile.TemporaryDirectory() as d:
            client=Client(); runtime=Runtime({'state_file':str(Path(d)/'state.json'),'model_services':[{'id':'m','type':'vllm','model':'/models/m'}]},client)
            with self.assertRaises(ValueError):runtime.start_model_service('m')
            self.assertEqual(client.submitted,[])
