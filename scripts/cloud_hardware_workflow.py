"""Run only inside the dedicated cloud workspace; exact management Job ownership."""
import argparse,json,os,sys,time,uuid,shutil,hashlib,re
from pathlib import Path
from urllib.request import urlopen
p=argparse.ArgumentParser();p.add_argument('--deployment',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--revision',required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
s=json.loads(a.deployment.read_text())
assert s.get('cloud')=='9450' and s.get('workspace')=='ray-admin-ride-e2e-myc','Dedicated owned 9450 deployment required'
from ray.job_submission import JobSubmissionClient
c=JobSubmissionClient('http://127.0.0.1:8265')
listen=s.get('listen','0.0.0.0:19100')
address='http://127.0.0.1:'+listen.rsplit(':',1)[1]
# Keep immutable candidate sources outside the runner checkout.
assert re.fullmatch(r'[a-zA-Z0-9_-]+',a.revision),'Invalid revision'
candidate=Path(s['root']).parent/'ride-ci-sources'/a.revision
source=Path('src/ride').resolve()
if candidate.exists():
    for f in source.rglob('*'):
        if f.is_file() and '__pycache__' not in f.parts:
            assert hashlib.sha256(f.read_bytes()).digest()==hashlib.sha256((candidate/'ride'/f.relative_to(source)).read_bytes()).digest(),'Immutable candidate differs'
else:
    shutil.copytree(source,candidate/'ride',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
sys.path.insert(0,str(candidate))
from ride.acceptance import run

def restart():
    identifier=s['management_job'];job=c.get_job_info(identifier)
    expected='python -m ride start --config '+s['root']+'/ride.json --listen '+listen
    assert job.entrypoint==expected,'Unexpected management entrypoint; refuse stop'
    (a.output/(identifier+'.log')).write_text(c.get_job_logs(identifier))
    c.stop_job(identifier);deadline=time.monotonic()+60
    while c.get_job_status(identifier).value not in ('STOPPED','FAILED','SUCCEEDED'):
        if time.monotonic()>deadline:raise TimeoutError('Management stop timed out')
        time.sleep(1)
    runtime_env=dict(job.runtime_env or {});env=dict(runtime_env.get('env_vars',{}))
    env['PYTHONPATH']=str(candidate)+':'+s['root'];env['RIDE_BUILD_REVISION']=a.revision;runtime_env['env_vars']=env
    new='ride-ci-management-'+uuid.uuid4().hex[:12]
    # Persist before submit; an uncertain submission never results in blind retry.
    s['management_job']=new;a.deployment.write_text(json.dumps(s,indent=2))
    c.submit_job(submission_id=new,entrypoint=expected,runtime_env=runtime_env,entrypoint_num_cpus=0.1,entrypoint_resources={'node:'+s['ip']:0.001})
    deadline=time.monotonic()+90
    while True:
        try:
            with urlopen(address+'/api/v1/status',timeout=5) as response:state=json.load(response)
            if state.get('build_revision')==a.revision:return
        except Exception:pass
        if time.monotonic()>deadline:raise TimeoutError('Candidate control plane not Ready')
        time.sleep(1)
try:
    restart()
    before=run(address,s['controller'],s['model_service'],a.output/'before.json',lifecycle=True,model=s['served_model'])
    required=['control_plane','model_ready','controller_ready','dependency','idempotence','stop_isolation','restore','inference']
    assert all(before['checks'][key]['status']=='PASS' for key in required),'Lifecycle gate failed'
    restart()
    after=run(address,s['controller'],s['model_service'],a.output/'after.json',model=s['served_model'],baseline=a.output/'before.json')
    assert after['checks']['adoption']['status']=='PASS' and after['checks']['inference']['status']=='PASS','Adoption gate failed'
    (a.output/'gate.json').write_text(json.dumps({'status':'PASS','revision':a.revision,'scope':'cloud deployment/lifecycle only','performance':'NOT_RUN'},indent=2))
except Exception as error:
    (a.output/'gate.json').write_text(json.dumps({'status':'FAIL','revision':a.revision,'error':str(error)},indent=2));raise
finally:
    try:(a.output/'management.log').write_text(c.get_job_logs(s['management_job']))
    except Exception:pass
