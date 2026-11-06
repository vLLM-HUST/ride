import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from ride.runtime import Runtime


class Status:
    value='RUNNING'
class Ray:
    def __init__(self):self.submitted=[];self.stopped=[];self.fail=False
    def get_job_status(self,identifier):return Status()
    def submit_job(self,**kwargs):
        self.submitted.append(kwargs)
        if self.fail:raise OSError('lost submission response')
    def stop_job(self,identifier):self.stopped.append(identifier);return True


SPEC={'type':'vllm','model':'fixture-model','endpoint':'http://model.invalid:8000'}

class Lifecycle(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'state.json';self.ray=Ray();self.config={'state_file':str(self.path),'workspace':'fixture','model_services':[]};self.runtime=Runtime(self.config,self.ray)
    def tearDown(self):self.runtime.close();self.temp.cleanup()
    def start(self,operation='operation',prior=None,spec=None):
        return self.runtime.start_instance('model_services','model-a',spec or SPEC,operation_id=operation,expected_job_id=prior)
    def test_conditional_start_cannot_adopt_concurrently_created_job(self):
        foreign=self.runtime.start_instance('model_services','model-a',SPEC)
        with self.assertRaisesRegex(ValueError,'identity'):
            self.start()
        self.assertEqual(len(self.ray.submitted),1)
        self.assertEqual(self.runtime.describe('model_services','model-a')['job_id'],foreign['job_id'])
    def test_repeated_operation_recovers_same_job_after_restart(self):
        first=self.start();self.runtime.close();self.runtime=Runtime(self.config,self.ray)
        self.assertEqual(self.start()['job_id'],first['job_id']);self.assertEqual(len(self.ray.submitted),1)
    def test_same_operation_different_payload_is_conflict(self):
        self.start()
        with self.assertRaisesRegex(ValueError,'conflict'):self.start(spec=dict(SPEC,model='other'))
        self.assertEqual(len(self.ray.submitted),1)
    def test_unknown_submission_never_resubmits(self):
        self.ray.fail=True
        with self.assertRaises(OSError):self.start()
        self.runtime.close();self.runtime=Runtime(self.config,self.ray)
        with self.assertRaisesRegex(ValueError,'unknown'):self.start()
        self.assertEqual(len(self.ray.submitted),1)
    def test_conditional_stop_checks_identity(self):
        first=self.start()
        with self.assertRaisesRegex(ValueError,'identity'):self.runtime.stop_instance('model_services','model-a',expected_job_id='foreign')
        self.assertEqual(self.ray.stopped,[])
        result=self.runtime.stop_instance('model_services','model-a',expected_job_id=first['job_id']);self.assertEqual(result['job_id'],first['job_id'])
    def test_capabilities_explicit(self):
        self.assertIs(self.runtime.snapshot()['capabilities']['conditional_start'],True)
        self.assertIs(self.runtime.snapshot()['capabilities']['conditional_stop'],True)


class SDK(unittest.TestCase):
    def test_sdk_import_is_lightweight(self):
        code='import ride.sdk,sys;assert not any(n in sys.modules for n in ["ray","torch","vllm","fastapi"]);print("LIGHTWEIGHT")'
        x=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True)
        self.assertEqual(x.returncode,0,x.stderr)
    def test_model_client_serializes_condition_and_has_no_retry(self):
        from ride.sdk import RideClient
        calls=[]
        def transport(method,path,body):
            calls.append((method,path,body))
            return {'protocol_version':'1','conditional_start':True} if method=='GET' else {'job_id':'job-1'}
        client=RideClient('http://ride.invalid:19100',transport=transport)
        row=client.models.start('model-a',SPEC,operation_id='op-1',expected_job_id=None)
        self.assertEqual(row['job_id'],'job-1');self.assertEqual(calls[-1:],[('POST','/api/v1/model-services/model-a/start',{'spec':SPEC,'operation_id':'op-1','expected_job_id':None})])
        def lost(*a):
            calls.append(a)
            if a[0]=='GET':return {'protocol_version':'1','conditional_start':True}
            raise OSError('lost')
        client=RideClient('http://ride.invalid:19100',transport=lost)
        with self.assertRaises(OSError):client.models.start('model-a',SPEC,operation_id='op-2',expected_job_id=None)
        self.assertEqual(len(calls),4)
    def test_controller_lookup_uses_management_record(self):
        from ride.sdk import RideClient
        client=RideClient('http://ride.invalid:19100',transport=lambda *a:{'id':'kv','endpoint':'http://kv.invalid:19082','ready':True})
        self.assertEqual(client.controllers.describe('kv')['endpoint'],'http://kv.invalid:19082')

if __name__=='__main__':unittest.main()

class ModelStartDeadline(unittest.TestCase):
    def test_expired_deadline_refuses_before_any_intent_or_job(self):
        with tempfile.TemporaryDirectory() as directory:
            ray=Ray();runtime=Runtime({'workspace':'fixture','state_file':str(Path(directory)/'state.json')},ray)
            with self.assertRaisesRegex(ValueError,'deadline'):
                runtime.start_instance('model_services','late',dict(SPEC,start_not_after='2020-01-01T00:00:00+00:00'),operation_id='late',expected_job_id=None)
            self.assertFalse(ray.submitted);self.assertFalse(runtime.state['jobs']);self.assertFalse(runtime.state['start_operations'])

    def test_naive_or_invalid_deadline_is_not_interpreted_as_local_time(self):
        with tempfile.TemporaryDirectory() as directory:
            ray=Ray();runtime=Runtime({'workspace':'fixture','state_file':str(Path(directory)/'state.json')},ray)
            for value in ['2026-11-06T01:00:00','invalid',None,False]:
                with self.subTest(value=value),self.assertRaises(ValueError):
                    runtime.start_instance('model_services','invalid',dict(SPEC,start_not_after=value),operation_id='invalid',expected_job_id=None)
            self.assertFalse(ray.submitted)

    def test_completed_start_replay_is_a_query_even_after_deadline(self):
        from datetime import datetime,timezone
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            ray=Ray();runtime=Runtime({'workspace':'fixture','state_file':str(Path(directory)/'state.json')},ray)
            spec=dict(SPEC,start_not_after='2999-01-01T00:00:00Z')
            first=runtime.start_instance('model_services','a',spec,operation_id='first',expected_job_id=None)
            with patch('ride.runtime.datetime',wraps=datetime) as clock:
                clock.now.return_value=datetime(3000,1,1,tzinfo=timezone.utc)
                self.assertEqual(runtime.start_instance('model_services','a',spec,operation_id='first',expected_job_id=None),first)
                with self.assertRaises(ValueError):runtime.start_instance('model_services','b',spec,operation_id='second',expected_job_id=None)
            self.assertEqual(len(ray.submitted),1)

class SDKStartDeadlineCapability(unittest.TestCase):
    def test_deadline_is_not_silently_ignored_by_an_older_manager(self):
        from ride.sdk import RideClient
        calls=[]
        def transport(method,path,body):
            calls.append(method)
            return {'protocol_version':'1','conditional_start':True}
        sdk=RideClient('http://ride.invalid',transport=transport)
        with self.assertRaisesRegex(ValueError,'start_deadline'):
            sdk.models.start('late',dict(SPEC,start_not_after='2999-01-01T00:00:00Z'),operation_id='late',expected_job_id=None)
        self.assertEqual(calls,['GET'])
