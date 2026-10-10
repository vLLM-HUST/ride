"""Explicitly restart one verified RIDE management Job, never its child processes."""
import argparse,json,shlex,subprocess,uuid
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--deployment',type=Path,required=True);p.add_argument('--ssh-host',required=True);a=p.parse_args();s=json.loads(a.deployment.read_text());new='ride-management-acceptance-'+uuid.uuid4().hex[:12]
code=f'''import json,time
from ray.job_submission import JobSubmissionClient
c=JobSubmissionClient('http://127.0.0.1:8265')
identifier={s['management_job']!r}
job=c.get_job_info(identifier)
expected='python -m ride start --config '+{s['root']!r}+'/ride.json --listen 0.0.0.0:19100'
assert job.entrypoint==expected,'Refuse to stop a Job with a different entrypoint'
print(json.dumps({{'before':identifier,'entrypoint':job.entrypoint,'logs':c.get_job_logs(identifier)}}),flush=True)
c.stop_job(identifier)
deadline=time.monotonic()+60
while c.get_job_status(identifier).value not in ('STOPPED','FAILED','SUCCEEDED'):
 assert time.monotonic()<deadline,'Management stop deadline exceeded'
 time.sleep(1)
c.submit_job(submission_id={new!r},entrypoint=expected,runtime_env=job.runtime_env,entrypoint_resources={{'node:'+{s['ip']!r}:0.001}},entrypoint_num_cpus=0.1)
print(json.dumps({{'after':{new!r}}}),flush=True)
'''
cmd=['kubectl','exec','-i','-n','coder-workspaces',s['head'],'-c','ray-head','--','python','-']
r=subprocess.check_output(['ssh','-o','ClearAllForwardings=yes',a.ssh_host,shlex.join(cmd)],input=code.encode())
a.deployment.with_name('restart-'+new+'.jsonl').write_bytes(r);s['management_job']=new;a.deployment.write_text(json.dumps(s,indent=2));print(new)
