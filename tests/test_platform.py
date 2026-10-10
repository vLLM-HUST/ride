import contextlib
import io
import tempfile
import threading
import unittest
from pathlib import Path
from http.server import ThreadingHTTPServer
from ride.runtime import Runtime
from ride.server import handler
from ride.__main__ import main
from test_runtime import Client

class LoggingClient(Client):
    def get_job_logs(self, identifier):return 'log for '+identifier+'\n'

class PlatformTests(unittest.TestCase):
    def test_cli_http_ray_contract_and_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            config={'state_file':str(Path(directory)/'state.json'),'workspace':'test','controllers':[]}
            client=LoggingClient();runtime=Runtime(config,client)
            server=ThreadingHTTPServer(('127.0.0.1',0),handler(config,runtime))
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            address='http://127.0.0.1:'+str(server.server_port)
            def cli(*args):
                with contextlib.redirect_stdout(io.StringIO()) as output:main([*args,'--address',address])
                return output.getvalue()
            try:
                cli('start','model-service','vllm','--name','model-main','--model','/models/m','--endpoint','http://127.0.0.1:9')
                cli('start','controller','request-throttling','--name','throttle-main','--backend','http://127.0.0.1:9','--endpoint','http://127.0.0.1:10')
                cli('start','controller','throttle-main')
                self.assertEqual(len(client.submitted),2)
                self.assertIn('throttle-main',cli('get','controllers'))
                self.assertIn('model-main',cli('get','model-services'))
                self.assertIn('log for',cli('logs','model-service','model-main'))
                cli('stop','controller','throttle-main')
                self.assertEqual(client.stopped,[client.submitted[1]['submission_id']])
                restored=Runtime(config,client)
                self.assertEqual(restored.state['specs']['model_services']['model-main']['model'],'/models/m')
                with self.assertRaises(SystemExit):cli('start','controller','throttle-main','--backend','http://different:8000')
                self.assertEqual(len(client.submitted),2)
            finally:server.shutdown();server.server_close();thread.join()

    def test_uncertain_submit_does_not_duplicate(self):
        class Uncertain(Client):
            def submit_job(self,**kw):super().submit_job(**kw);raise TimeoutError()
        with tempfile.TemporaryDirectory() as directory:
            config={'state_file':str(Path(directory)/'state.json'),'workspace':'test','controllers':[]}
            client=Uncertain();runtime=Runtime(config,client)
            with self.assertRaises(TimeoutError):runtime.start_instance('model_services','m',{'type':'vllm','model':'/models/m','endpoint':'http://model:8000'})
            restored=Runtime(config,client);result=restored.start_model_service('m')
            self.assertTrue(result['unchanged']);self.assertEqual(len(client.submitted),1)

    def test_not_ready_dependency_blocks_controller(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime=Runtime({'state_file':str(Path(directory)/'state.json'),'workspace':'test','controllers':[], 'model_services':[{'id':'m','type':'vllm','model':'/models/m','endpoint':'http://127.0.0.1:9'}]},Client())
            with self.assertRaisesRegex(ValueError,'not Ready'):
                runtime.start_instance('controllers','c',{'type':'request-throttling','backend':'http://127.0.0.1:9','endpoint':'http://127.0.0.1:10','model_service':'m'})
            self.assertEqual(runtime.client.submitted,[])
