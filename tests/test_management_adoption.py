"""Management replacement must preserve existing Jobs, including stopped models."""
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]


def module(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/f'{name}.py')
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value


class AdoptionTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.command='python -m ride start --config /owned/config.json'
        (self.root/'management-submission.json').write_text(json.dumps({'job_id':'owned-management','entrypoint':self.command}))
        self.plan={'address':'http://ride','management_job_id':'owned-management',
            'deployment_output':str(self.root),'runtime_env':{},'timeout':1}
        self.before={'management_pid':1,'run_id':'same','controllers':[
            {'id':'controller','job_id':'controller-job','job_status':'RUNNING','ready':True}],
            'model_services':[{'id':'a','job_id':'model-a','job_status':'RUNNING','ready':True},
                {'id':'b','job_id':'model-b','job_status':'STOPPED','ready':False}]}
        self.after=copy.deepcopy(self.before);self.after['management_pid']=2
        self.requests=0;self.calls=[];self.submissions=[];self.stopped=False
        outer=self
        class Jobs:
            def call(self,path,body=None):
                outer.calls.append((path,body))
                if path.endswith('/stop'):outer.stopped=True;return {'stopped':True}
                return {'entrypoint':outer.command,'status':'STOPPED' if path.endswith('/owned-management') and outer.stopped else 'RUNNING'}
            def submit_job(self,**kwargs):outer.submissions.append(kwargs);return {'job_id':kwargs['submission_id']}
        self.client=Jobs();self.scenarios=module('acceptance_scenarios')

    def request(self,address,path,body=None):
        self.assertEqual(path,'status');self.requests+=1
        return copy.deepcopy(self.before if self.requests==1 else self.after)

    def invoke(self,wait=None):
        with patch.dict(sys.modules,{'ride.__main__':types.SimpleNamespace(request=self.request)}), \
                patch.object(self.scenarios.time,'sleep',return_value=None):
            return self.scenarios.adoption(self.plan,self.client,wait or (lambda path:copy.deepcopy(self.after)))

    def test_new_management_job_is_used_by_fail_fast_readiness(self):
        for row in self.before['model_services']+self.after['model_services']:
            row.update(job_status='RUNNING',ready=True)
        def wait(path):
            self.assertEqual(self.plan['management_job_id'],'owned-management-adopt')
            return copy.deepcopy(self.after)
        self.invoke(wait)
        self.assertEqual(len(self.submissions),1)

    def test_stopped_model_does_not_need_to_become_ready(self):
        result=self.invoke()
        self.assertEqual(result['after']['model_services'][1]['job_status'],'STOPPED')
        self.assertEqual(result['after']['model_services'][1]['job_id'],'model-b')

    def test_controller_observation_recovers_before_adoption_passes(self):
        not_ready=copy.deepcopy(self.after);not_ready['controllers'][0]['ready']=False
        self.invoke(lambda path:not_ready)
        self.assertGreaterEqual(self.requests,2)

    def test_existing_intent_refuses_before_stopping_management(self):
        (self.root/'adoption-submission.json').write_text('{}')
        with self.assertRaisesRegex(RuntimeError,'intent exists'):
            self.invoke()
        self.assertFalse(any(path.endswith('/stop') for path,_ in self.calls))
        self.assertEqual(self.submissions,[])

    def test_changed_instance_job_is_not_adopted(self):
        self.after['model_services'][0]['job_id']='foreign-job'
        with self.assertRaises(AssertionError):self.invoke()
        self.assertEqual(len(self.submissions),1)

    def test_unready_baseline_refuses_before_stopping_management(self):
        self.before['model_services'][0]['ready']=False
        for row in self.after['model_services']:row.update(job_status='RUNNING',ready=True)
        with self.assertRaises((AssertionError,ValueError)):self.invoke()
        self.assertFalse(any(path.endswith('/stop') for path,_ in self.calls))

    def test_stopped_management_binding_cannot_be_replaced_again(self):
        self.stopped=True
        with self.assertRaisesRegex(AssertionError,'running before adoption'):
            self.invoke()
        self.assertEqual(self.submissions,[])
        self.assertFalse(any(path.endswith('/stop') for path,_ in self.calls))

    def test_invalid_restart_delay_refuses_before_any_stop(self):
        self.plan['management_restart_delay_seconds']=-1
        with self.assertRaises(ValueError):self.invoke()
        self.assertFalse(any(path.endswith('/stop') for path,_ in self.calls))


class AdoptionEntryTests(unittest.TestCase):
    def test_standard_acceptance_entry_has_an_adoption_only_scope(self):
        entry=module('acceptance_entry')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);plan=root/'plan.json';out=root/'evidence'
            plan.write_text(json.dumps({'ray_address':'http://ray','address':'http://ride',
                'management_job_id':'owned-management'}))
            snapshot={'controllers':[],'model_services':[]}
            fake_adoption=lambda plan,client,wait:{'management_job':'owned-management-adopt'}
            with patch.dict(sys.modules,{'ride.__main__':types.SimpleNamespace(request=lambda *a,**k:snapshot),
                    'deployment_identity':types.SimpleNamespace(verify_live=lambda p:{'verified':True}),
                    'acceptance_scenarios':types.SimpleNamespace(adoption=fake_adoption)}), \
                    patch.object(sys,'argv',['acceptance_entry.py','accept-adoption','--plan',str(plan),'--output',str(out)]), \
                    patch.object(entry,'urlopen',side_effect=lambda *a,**k:io.BytesIO(b'{}')):
                entry.main()
            ledger=json.loads((out/'accept-adoption.json').read_text())
            self.assertEqual(ledger['status'],'PASS')
            self.assertEqual(ledger['scope'],'Management adoption only; no model submission or performance acceptance')

    def test_actual_one_click_shell_forwards_adoption_operation(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);capture=root/'capture.json';python=root/'python'
            python.write_text('#!'+sys.executable+'\nimport json,os,sys\nopen(os.environ["CAPTURE"],"w").write(json.dumps(sys.argv[1:]))\n')
            python.chmod(0o755)
            value=subprocess.run(['bash',str(ROOT/'scripts/one-click.sh'),'accept-adoption','plan.json','evidence'],
                env={**os.environ,'RIDE_PYTHON':str(python),'CAPTURE':str(capture)},capture_output=True,text=True)
            self.assertEqual(value.returncode,0,value.stderr)
            self.assertEqual(json.loads(capture.read_text())[1:3],['accept-adoption','--plan'])


if __name__=='__main__':unittest.main()
