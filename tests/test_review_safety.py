import tempfile, unittest
from pathlib import Path
from ride.runtime import Runtime
from test_sdk_lifecycle import Ray, SPEC

class Safety(unittest.TestCase):
 def test_second_runtime_refused_until_first_closed(self):
  with tempfile.TemporaryDirectory() as d:
   cfg={'state_file':str(Path(d)/'state.json'),'workspace':'fixture'};ray=Ray();first=Runtime(cfg,ray)
   try:
    job=first.start_instance('model_services','a',SPEC,operation_id='one',expected_job_id=None)
    with self.assertRaisesRegex(RuntimeError,'writer|locked'):Runtime(cfg,ray)
    self.assertEqual(len(ray.submitted),1)
   finally:
    if hasattr(first,'close'):first.close()
   restored=Runtime(cfg,ray)
   try:
    self.assertEqual(restored.start_instance('model_services','a',SPEC,operation_id='one',expected_job_id=None)['job_id'],job['job_id'])
    self.assertEqual(len(ray.submitted),1)
   finally:restored.close()
 def test_null_stop_is_not_legacy_omission(self):
  with tempfile.TemporaryDirectory() as d:
   r=Runtime({'state_file':str(Path(d)/'state'),'workspace':'fixture'},Ray())
   try:
    r.start_instance('model_services','a',SPEC,operation_id='one',expected_job_id=None)
    for invalid in (None,'',False,0):
     with self.subTest(invalid=invalid),self.assertRaises(ValueError):r.stop_instance('model_services','a',expected_job_id=invalid)
    self.assertEqual(r.client.stopped,[])
   finally:
    if hasattr(r,'close'):r.close()

class Completion(unittest.TestCase):
 def test_completion_and_state_are_one_transaction(self):
  from ride.sdk import Journal, UnknownOutcome
  with tempfile.TemporaryDirectory() as d:
   j=Journal(Path(d)/'journal','fixture');calls=[]
   def fail(state,result):state['done']=True;raise RuntimeError('commit failure')
   try:
    with self.assertRaises(RuntimeError):j.execute('one',{},lambda:calls.append('effect') or {'ok':True},on_complete=fail)
    self.assertNotIn('done',j.snapshot());self.assertEqual(j.operations()[0]['status'],'UNKNOWN')
    with self.assertRaises(UnknownOutcome):j.execute('one',{},lambda:calls.append('duplicate'))
    self.assertEqual(calls,['effect'])
   finally:j.close()

class ProcessOwnership(unittest.TestCase):
 def test_other_process_is_refused_and_close_preserves_jobs(self):
  import os,subprocess,sys
  with tempfile.TemporaryDirectory() as d:
   cfg={'state_file':str(Path(d)/'state'),'workspace':'fixture'};ray=Ray();r=Runtime(cfg,ray)
   source=str(Path(__file__).resolve().parents[1]/'src')
   code='from ride.runtime import Runtime\ntry: Runtime('+repr(cfg)+',object())\nexcept RuntimeError: print("SECOND_WRITER_REFUSED")\nelse: raise SystemExit(7)'
   try:
    result=subprocess.run([sys.executable,'-c',code],env={**os.environ,'PYTHONPATH':source},capture_output=True,text=True,timeout=10)
    self.assertEqual(result.returncode,0,result.stderr);self.assertIn('SECOND_WRITER_REFUSED',result.stdout)
   finally:r.close()
   self.assertEqual(ray.stopped,[])
 def test_failed_initialization_releases_lock(self):
  with tempfile.TemporaryDirectory() as d:
   cfg={'state_file':str(Path(d)/'state'),'workspace':'fixture'}
   with self.assertRaises(ValueError):Runtime(dict(cfg,deployment='unsupported'),Ray())
   r=Runtime(cfg,Ray());r.close()
