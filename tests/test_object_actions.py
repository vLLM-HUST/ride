"""Public contract: local state CAS, not a distributed transaction."""
import tempfile,unittest
from pathlib import Path
from ride.sdk import Journal, make_action, ActionConflict, validate_snapshot, verify_action_result

class Objects(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'state'
  self.j=Journal(self.path,'fixture');self.j.mutate(lambda state:state.update(owner_id='owner',members={'a':{'job_id':'job-a','phase':'active'},'b':{'job_id':'job-b','phase':'active'}}))
 def tearDown(self):self.j.close();self.temp.cleanup()
 def view(self,name):return lambda state:(state['members'][name]['job_id'],dict(state['members'][name]),{})
 def observe(self,name='a'):return self.j.observe_object('Instance',name,self.view(name))
 def action(self,snapshot=None,identifier='one',phase='draining'):
  return make_action(snapshot or self.observe(),'set-phase',{'phase':phase},operation_id=identifier,actor_id='actor')
 def apply(self,request):
  name=request['target']['name']
  def change(state,parameters):state['members'][name]['phase']=parameters['phase'];return {'changed':True}
  return self.j.apply_action(request,self.view(name),change)
 def test_snapshot_and_idempotent_action_survive_restart(self):
  before=self.observe();validate_snapshot(before);request=self.action(before);first=self.apply(request)
  verify_action_result(request,first);after=self.observe();self.assertNotEqual(before['resource_version'],after['resource_version'])
  self.assertEqual(self.apply(request),first);self.j.close();self.j=Journal(self.path,'fixture')
  self.assertEqual(self.apply(request),first);self.assertEqual(self.observe()['resource_version'],after['resource_version'])
 def test_stale_version_wrong_uid_or_owner_never_changes_state(self):
  before=self.observe();self.apply(self.action(before));old=self.action(before,'old','active')
  with self.assertRaises(ActionConflict):self.apply(old)
  for field,value in [('owner_id','foreign'),('owner_uid','foreign-epoch'),('target',dict(self.observe()['object'],uid='replacement'))]:
   request=self.action(identifier=field);request[field]=value
   with self.assertRaises(ActionConflict):self.apply(request)
  self.assertEqual(self.observe()['state']['phase'],'draining')
 def test_conflicting_operation_payload_is_rejected(self):
  request=self.action();self.apply(request);changed=dict(request,parameters={'phase':'active'})
  with self.assertRaises(ValueError):self.apply(changed)
 def test_other_object_and_nonobject_mutation_do_not_invalidate_version(self):
  a=self.observe();b=self.observe('b');self.apply(self.action(b,'b'))
  self.j.mutate(lambda state:state.update(telemetry='new'))
  self.assertEqual(self.observe()['resource_version'],a['resource_version']);self.apply(self.action(a,'a'))
 def test_legacy_transition_also_invalidates_object_version(self):
  before=self.observe();self.j.mutate(lambda s:s['members']['a'].update(phase='draining'),objects=[('Instance','a')])
  with self.assertRaises(ActionConflict):self.apply(self.action(before))
 def test_failed_transition_rolls_back_state_and_receipt(self):
  request=self.action();before=self.observe()
  def fail(state,parameters):state['members']['a']['phase']='broken';raise RuntimeError('injected')
  with self.assertRaises(RuntimeError):self.j.apply_action(request,self.view('a'),fail)
  self.assertEqual(self.observe()['resource_version'],before['resource_version'])
  self.assertEqual(self.observe()['state']['phase'],'active')
  with self.assertRaises(KeyError):self.j.read_action('one')
 def test_recreated_store_cannot_accept_old_observation(self):
  old=self.action();self.j.close();self.path.unlink()
  self.j=Journal(self.path,'fixture');self.j.mutate(lambda s:s.update(owner_id='owner',members={'a':{'job_id':'job-a','phase':'active'}}))
  with self.assertRaises(ActionConflict):self.apply(old)

class ConcurrentActions(unittest.TestCase):
 def test_duplicate_operation_commits_transition_once(self):
  from concurrent.futures import ThreadPoolExecutor
  with tempfile.TemporaryDirectory() as d:
   j=Journal(Path(d)/'state','fixture');j.mutate(lambda s:s.update(owner_id='owner',member={'job_id':'job','phase':'active'}))
   view=lambda s:('job',dict(s['member']),{})
   request=make_action(j.observe_object('Instance','a',view),'drain',{},operation_id='same',actor_id='actor');calls=[]
   def transition(s,p):calls.append('once');s['member']['phase']='draining';return {'drained':True}
   try:
    with ThreadPoolExecutor(max_workers=2) as pool:
     rows=list(pool.map(lambda _:j.apply_action(request,view,transition),range(2)))
    self.assertEqual(rows[0],rows[1]);self.assertEqual(calls,['once'])
   finally:j.close()
