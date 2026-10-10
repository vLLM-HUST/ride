"""Deploy only an explicitly selected owned workspace; no cluster restart."""
import argparse,json,subprocess
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--ssh-host',required=True);p.add_argument('--cluster',required=True);p.add_argument('--namespace',default='coder-workspaces');a=p.parse_args()
def shell(args,stdin=None):return subprocess.check_output(['ssh',a.ssh_host]+args,input=stdin)
pods=json.loads(shell(['kubectl','get','pods','-n',a.namespace,'-l','ray.io/cluster='+a.cluster,'-o','json']))['items']
assert len(pods)==1,'Acceptance expects a dedicated single-node cluster'
head=pods[0];pod=head['metadata']['name'];ip=head['status']['podIP']
def python(code):return shell(['kubectl','exec','-i','-n',a.namespace,pod,'-c','ray-head','--','python','-'],code.encode()).decode()
code='''import os,json
from pathlib import Path
from ray.job_submission import JobSubmissionClient
root='/workspace/home/ride-e2e'
ip=IP
client=JobSubmissionClient('http://127.0.0.1:8265')
active=[j for j in client.list_jobs() if j.status.value in ('RUNNING','PENDING')]
assert not active,'Refuse existing jobs: do not duplicate acceptance launch'
model='/models/Qwen2.5-14B-Instruct'
assert (Path(model)/'config.json').exists(),'Missing real model'
env={'PYTHONPATH':root+'/ride/src:'+root+'/controller/src:'+root+'/upstream:'+os.environ.get('PYTHONPATH',''),'ENGINE_RAY_NODE_ADDRESSES':json.dumps([ip]),'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','PYTHONUNBUFFERED':'1'}
engine='python '+root+'/controller/scripts/serve_pinned_engine.py --model '+model+' --served-model-name qwen2.5-14b --host 0.0.0.0 --port 8100 --tensor-parallel-size 1 --max-model-len 32768 --enforce-eager --enable-prefix-caching --block-size 128 --num-gpu-blocks-override 1206'
client.submit_job(submission_id='ride-e2e-engine',entrypoint=engine,runtime_env={'env_vars':env},entrypoint_resources={'node:'+ip:0.001})
config={'name':'RIDE','deployment':'ray','workspace':WORKSPACE,'state_file':root+'/ride-state.json','ray_address':'http://127.0.0.1:8265','controllers':[{'id':'request-throttling','entrypoint':'request-throttling','backend':'http://'+ip+':8100','endpoint':'http://'+ip+':9000','listen':'0.0.0.0:9000','transport':'no-keepalive','autostart':False,'runtime_env':{'env_vars':env},'resources':{'node:'+ip:0.001}}]}
Path(root+'/ride.json').write_text(json.dumps(config))
client.submit_job(submission_id='ride-e2e-management',entrypoint='python -m ride serve --config '+root+'/ride.json --listen 0.0.0.0:19100',runtime_env={'env_vars':env},entrypoint_resources={'node:'+ip:0.001})
print(json.dumps({'workspace':WORKSPACE,'head':HEAD,'ip':ip,'engine_job':'ride-e2e-engine','management_job':'ride-e2e-management'}))
'''.replace('IP',repr(ip)).replace('WORKSPACE',repr(a.cluster)).replace('HEAD',repr(pod))
result=python(code);Path('results/acceptance/launch.json').write_text(result);print(result)
