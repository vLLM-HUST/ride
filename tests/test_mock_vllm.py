import json,threading,unittest
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from ride.mock_vllm import server
from ride.registry import command
class MockServiceTest(unittest.TestCase):
    def setUp(self):
        self.server=server('127.0.0.1',0);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.url='http://127.0.0.1:'+str(self.server.server_port)
    def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join()
    def post(self,data):
        with urlopen(Request(self.url+'/v1/chat/completions',data=json.dumps(data).encode(),headers={'Content-Type':'application/json'})) as r:return json.load(r)
    def test_explicit_mock_identity_and_deterministic_response(self):
        with urlopen(self.url+'/health') as r:self.assertEqual(json.load(r)['evidence_type'],'mock')
        for _ in range(2):
            r=self.post({'model':'mock-vllm','messages':[{'role':'user','content':'hello'}]})
            self.assertEqual(r['choices'][0]['message']['content'],'hello');self.assertEqual(r['ride_evidence_type'],'mock')
    def test_wrong_model_and_stream_are_rejected(self):
        for data in [{'model':'real-model','messages':[{}]},{'model':'mock-vllm','messages':[{}],'stream':True}]:
            with self.assertRaises(HTTPError) as error:self.post(data)
            self.assertEqual(error.exception.code,400)
    def test_mock_cannot_allocate_accelerator(self):
        for spec in [{'num_gpus':1},{'resources':{'NPU':1}}]:
            with self.assertRaises(ValueError):command('model_services',dict(type='mock-vllm',model='mock-vllm',endpoint='http://mock',**spec))
