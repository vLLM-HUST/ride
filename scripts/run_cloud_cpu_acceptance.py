"""Create one disposable CPU Pod on the explicitly selected cloud; collect then delete."""
import argparse, io, json, shlex, subprocess, tarfile, uuid
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--ssh-host');p.add_argument('--local',action='store_true');p.add_argument('--revision');p.add_argument('--image',required=True);p.add_argument('--controller-source',type=Path,required=True);p.add_argument('--upstream-source',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
name='ride-cpu-ci-myc-'+uuid.uuid4().hex[:10];namespace='coder-workspaces'
def remote(args,data=None):
 command=args if a.local else ['ssh','-o','ClearAllForwardings=yes',a.ssh_host,shlex.join(args)]
 return subprocess.check_output(command,input=data,timeout=480)
def execute(args,data=None):return remote(['kubectl','exec','-i','-n',namespace,name,'--',*args],data)
manifest={'apiVersion':'v1','kind':'Pod','metadata':{'name':name,'namespace':namespace,'labels':{'app':'ride-cpu-acceptance','ride-owner':'myc'}},'spec':{'restartPolicy':'Never','activeDeadlineSeconds':1200,'automountServiceAccountToken':False,'volumes':[{'name':'shm','emptyDir':{'medium':'Memory','sizeLimit':'2Gi'}}],'containers':[{'name':'acceptance','image':a.image,'command':['sleep','1200'],'volumeMounts':[{'name':'shm','mountPath':'/dev/shm'}],'resources':{'requests':{'cpu':'1','memory':'2Gi'},'limits':{'cpu':'4','memory':'8Gi'}}}]}}
(a.output/'pod.json').write_text(json.dumps(manifest,indent=2));created=False
try:
 remote(['kubectl','create','-f','-'],json.dumps(manifest).encode());created=True
 remote(['kubectl','wait','-n',namespace,'--for=condition=Ready','pod/'+name,'--timeout=120s'])
 buf=io.BytesIO()
 with tarfile.open(fileobj=buf,mode='w:gz') as t:
  for directory in ['src/ride','scripts','tests']:t.add(directory,arcname='repo/'+directory,filter=lambda x:None if '__pycache__' in x.name else x)
  t.add('pyproject.toml',arcname='repo/pyproject.toml')
  t.add(a.controller_source/'src/thunderagent_controller_mod',arcname='dependencies/thunderagent_controller_mod')
  t.add(a.upstream_source/'ThunderAgent',arcname='dependencies/ThunderAgent')
 execute(['mkdir','-p','/tmp/ride-ci']);execute(['tar','-xzf','-','-C','/tmp/ride-ci'],buf.getvalue())
 revision=a.revision or subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
 code='''import json,socket,subprocess,os
from pathlib import Path
root='/tmp/ride-ci'; env=dict(os.environ,PYTHONPATH=root+'/dependencies:'+root+'/repo/src')
with open(root+'/ray-start.log','w') as ray_log:
 subprocess.run(['ray','start','--head','--num-cpus=4','--num-gpus=0','--include-dashboard=true','--dashboard-host=0.0.0.0'],env=env,stdin=subprocess.DEVNULL,stdout=ray_log,stderr=subprocess.STDOUT,check=True)
ip=socket.gethostbyname(socket.gethostname())
Path(root+'/deployment.json').write_text(json.dumps({'cloud':'9450','workspace':os.environ['HOSTNAME'],'root':root+'/dependencies','ip':ip}))
Path(root+'/evidence').mkdir(exist_ok=True)
with open(root+'/evidence/tests.log','w') as f:
 subprocess.run(['python','-m','pip','install','--no-build-isolation',root+'/repo'],env=env,stdout=f,stderr=subprocess.STDOUT,check=True)
 subprocess.run(['python','-m','unittest','discover','-s','tests','-v'],cwd=root+'/repo',env=dict(env,PYTHONPATH=root+'/dependencies'),stdout=f,stderr=subprocess.STDOUT,check=True)
subprocess.run(['python','scripts/cloud_cpu_workflow.py','--deployment',root+'/deployment.json','--output',root+'/evidence','--revision',REVISION],cwd=root+'/repo',env=env,check=True)
'''.replace('REVISION',repr(revision))
 try:(a.output/'cloud.log').write_bytes(execute(['python','-'],code.encode()))
 except subprocess.CalledProcessError as error:
  (a.output/'cloud.log').write_bytes(error.output or b'');raise
finally:
 if created:
  try:(a.output/'evidence.tar.gz').write_bytes(execute(['tar','-czf','-','-C','/tmp/ride-ci/evidence','.']))
  except subprocess.CalledProcessError:(a.output/'collection-error.txt').write_text('Evidence directory unavailable; inspect cloud pod log.')
  (a.output/'pod-final.json').write_bytes(remote(['kubectl','get','pod',name,'-n',namespace,'-o','json']))
  remote(['kubectl','delete','pod',name,'-n',namespace,'--wait=true','--timeout=60s'])
  try:remote(['kubectl','get','pod',name,'-n',namespace]);raise RuntimeError('Temporary Pod still present')
  except subprocess.CalledProcessError:pass
  (a.output/'cleanup.json').write_text(json.dumps({'pod':name,'deleted':True,'accelerator_resources_requested':0}))
