import copy,json,tempfile,unittest
from pathlib import Path
from ride.acceptance import run

class AcceptanceTest(unittest.TestCase):
    def setUp(self):
        self.snapshot={'name':'RIDE','workspace':'owned','management_pid':2,'run_id':'same',
            'controllers':[{'id':'controller','job_id':'controller-job','ready':True,'job_status':'RUNNING','backend':'http://engine'}],
            'model_services':[{'id':'model','job_id':'model-job','ready':True,'job_status':'RUNNING','endpoint':'http://engine'}]}
        self.actions=[]
    def request(self,address,path,body=None):
        self.actions.append((path,body))
        if path=='status':return copy.deepcopy(self.snapshot)
        if path.endswith('/logs'):return {'logs':'raw log','job_id':'owned'}
        if path=='model-services/model':return copy.deepcopy(self.snapshot['model_services'][0])
        if path=='controllers/controller':return copy.deepcopy(self.snapshot['controllers'][0])
        controller=self.snapshot['controllers'][0]
        if path.endswith('/stop'):
            controller.update(job_status='STOPPED',ready=False);return {'stop_requested':True}
        if path.endswith('/start'):
            if controller['job_status']=='RUNNING':return {'unchanged':True,'job_id':controller['job_id']}
            controller.update(job_status='RUNNING',ready=True,job_id='new-controller-job');return {'job_id':controller['job_id']}
        raise AssertionError(path)
    def test_read_only_preserves_not_run_and_no_actions(self):
        with tempfile.TemporaryDirectory() as d:
            report=run('http://ride','controller','model',Path(d)/'report.json',request=self.request)
        self.assertEqual(report['status'],'PASS');self.assertFalse(report['complete'])
        self.assertEqual(report['checks']['performance']['status'],'NOT_RUN')
        self.assertFalse(any(body is not None for _,body in self.actions))
    def test_lifecycle_and_independent_model(self):
        with tempfile.TemporaryDirectory() as d:
            report=run('http://ride','controller','model',Path(d)/'report.json',lifecycle=True,request=self.request)
        for key in ('idempotence','stop_isolation','restore'):self.assertEqual(report['checks'][key]['status'],'PASS')
        self.assertEqual(self.snapshot['model_services'][0]['job_id'],'model-job')
    def test_adoption_requires_new_management_process(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d)/'base.json';base.write_text(json.dumps({'after':self.snapshot}))
            report=run('http://ride','controller','model',Path(d)/'report.json',baseline=base,request=self.request)
            self.assertEqual(report['checks']['adoption']['status'],'FAIL')
            self.snapshot['management_pid']=3
            report=run('http://ride','controller','model',Path(d)/'report.json',baseline=base,request=self.request)
            self.assertEqual(report['checks']['adoption']['status'],'PASS')
    def test_unready_blocks_lifecycle(self):
        self.snapshot['model_services'][0]['ready']=False
        with tempfile.TemporaryDirectory() as d:
            report=run('http://ride','controller','model',Path(d)/'report.json',lifecycle=True,request=self.request)
        self.assertEqual(report['status'],'FAIL');self.assertEqual(report['checks']['restore']['status'],'NOT_RUN')
        self.assertFalse(any(body is not None for _,body in self.actions))
