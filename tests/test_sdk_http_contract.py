import io,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from ride.server import handler
from ride.runtime import Runtime
from ride.sdk import RideClient,ApiError
from test_sdk_lifecycle import Ray,SPEC

class Socket:
    def __init__(self,data):self.rfile=io.BytesIO(data);self.output=io.BytesIO()
    def makefile(self,*a,**kw):return self.rfile
    def sendall(self,data):self.output.write(data)

class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.ray=Ray();self.runtime=Runtime({'state_file':str(Path(self.temp.name)/'state.json'),'workspace':'fixture'},self.ray)
        self.handler=handler({},self.runtime);self.handler.log_message=lambda *args:None
    def tearDown(self):self.temp.cleanup()
    def transport(self,method,path,body):
        raw=json.dumps(body).encode() if body is not None else b''
        request=(method+' '+path+' HTTP/1.0\r\nHost: ride.invalid\r\nContent-Type: application/json\r\nContent-Length: '+str(len(raw))+'\r\n\r\n').encode()+raw
        socket=Socket(request);self.handler(socket,('127.0.0.1',12345),SimpleNamespace(server_name='fixture',server_port=0))
        head,body=socket.output.getvalue().split(b'\r\n\r\n',1);status=int(head.split()[1]);data=json.loads(body)
        if not 200<=status<300:raise ApiError(status,data.get('error','HTTP error'))
        return data
    def test_sdk_handler_runtime_start_inspect_stop(self):
        sdk=RideClient('http://ride.invalid',transport=self.transport);sdk.require_capabilities('conditional_start','conditional_stop')
        first=sdk.models.start('model-a',SPEC,operation_id='start-1',expected_job_id=None)
        self.assertEqual(sdk.models.start('model-a',SPEC,operation_id='start-1',expected_job_id=None)['job_id'],first['job_id'])
        self.assertEqual(sdk.operation('start-1')['status'],'COMPLETED')
        self.assertEqual(len(self.ray.submitted),1)
        sdk.models.stop('model-a',expected_job_id=first['job_id']);self.assertEqual(self.ray.stopped,[first['job_id']])
    def test_conflicting_job_rejected_over_actual_handler(self):
        first=self.runtime.start_instance('model_services','model-a',SPEC)
        with self.assertRaises(ApiError) as error:self.transport('POST','/api/v1/model-services/model-a/start',{'spec':SPEC,'operation_id':'new','expected_job_id':None})
        self.assertEqual(error.exception.status,409);self.assertEqual(len(self.ray.submitted),1)
    def test_partial_envelopes_never_downgrade_to_legacy_start(self):
        for body in [{'spec':SPEC},{'spec':SPEC,'expected_job_id':None},{'spec':SPEC,'operation_id':'op'},{'spec':SPEC,'operation_id':'op','expected_job_id':None,'extra':1}]:
            with self.assertRaises(ApiError) as error:self.transport('POST','/api/v1/model-services/model-a/start',body)
            self.assertEqual(error.exception.status,409)
        self.assertEqual(self.ray.submitted,[])
    def test_legacy_start_remains_available(self):
        self.transport('POST','/api/v1/model-services/model-a/start',SPEC);self.transport('POST','/api/v1/model-services/model-a/start',SPEC)
        self.assertEqual(len(self.ray.submitted),1)
    def test_explicit_null_stop_cannot_downgrade_to_legacy(self):
        self.runtime.start_instance('model_services','model-a',SPEC,operation_id='start',expected_job_id=None)
        for invalid in (None,'',False,0):
            with self.subTest(invalid=invalid),self.assertRaises(ApiError) as error:
                self.transport('POST','/api/v1/model-services/model-a/stop',{'expected_job_id':invalid})
            self.assertEqual(error.exception.status,409)
        self.assertEqual(self.ray.stopped,[])
