"""RIDE platform entry: operations on Controller and model-service instances."""
import argparse
import json
import os
import sys
from pathlib import Path
from http.server import ThreadingHTTPServer
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from .server import handler

KINDS={'controller':'controllers','model-service':'model-services','controllers':'controllers','model-services':'model-services'}

def request(address,path,body=None):
    req=Request(address.rstrip('/')+'/api/v1/'+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json'})
    try:
        with urlopen(req,timeout=30) as response:return json.load(response)
    except HTTPError as e:
        try:message=json.load(e).get('error',str(e))
        except Exception:message=str(e)
        raise ValueError(message) from e

def parser():
    p=argparse.ArgumentParser(description='RIDE control plane: deploy and observe processes on Ray')
    sub=p.add_subparsers(dest='command',required=True)
    for verb in ('start','stop','get','describe','logs','serve'):
        s=sub.add_parser(verb)
        s.add_argument('resource',nargs='?',choices=list(KINDS))
        s.add_argument('target',nargs='?')
        s.add_argument('--address',default=os.environ.get('RIDE_ADDRESS','http://127.0.0.1:19100'))
        if verb in ('start','serve'):
            s.add_argument('--config');s.add_argument('--listen',default='127.0.0.1:19100')
            s.add_argument('--ray-address',default='http://127.0.0.1:8265')
            s.add_argument('--state-file',default='.ride/state.json');s.add_argument('--workspace',default=os.environ.get('CODER_WORKSPACE_NAME','local-development'))
            s.add_argument('--name');s.add_argument('--backend');s.add_argument('--endpoint');s.add_argument('--model-service');s.add_argument('--model')
            s.add_argument('--executor',choices=['ray']);s.add_argument('--transport',choices=['upstream-default','no-keepalive'])
            s.add_argument('--port',type=int);s.add_argument('--num-cpus',type=float);s.add_argument('--num-gpus',type=float)
            s.add_argument('--runtime-env',help='JSON object');s.add_argument('--resources',help='Ray custom resources JSON object')
            s.add_argument('--model-arg',action='append',help='vllm argument; use --model-arg=--option for flags')
    v=sub.add_parser('verify',help='Execute standardized acceptance and save evidence')
    v.add_argument('--address',default=os.environ.get('RIDE_ADDRESS','http://127.0.0.1:19100'))
    v.add_argument('--controller',required=True);v.add_argument('--model-service',required=True)
    v.add_argument('--output',required=True);v.add_argument('--lifecycle',action='store_true')
    v.add_argument('--model');v.add_argument('--baseline');v.add_argument('--timeout',type=float,default=120)
    return p

def main(argv=None):
    p=parser();a=p.parse_args(argv)
    try:
        if a.command=='verify':
            from .acceptance import run
            report=run(a.address,a.controller,a.model_service,a.output,a.lifecycle,a.model,a.baseline,a.timeout)
            print(json.dumps({key:report[key] for key in ('status','complete','checks')},indent=2,ensure_ascii=False))
            if report['status']=='FAIL':raise SystemExit(1)
            return
        if a.command=='serve' or (a.command=='start' and not a.resource):
            if a.command=='serve' and a.resource:p.error('serve accepts control-plane configuration only')
            config=json.loads(Path(a.config).read_text()) if a.config else {'name':'RIDE','deployment':'ray','workspace':a.workspace,'state_file':a.state_file,'ray_address':a.ray_address,'controllers':[],'model_services':[]}
            if config.get('deployment')!='ray':raise ValueError('Only Ray process deployment is implemented')
            from .runtime import Runtime
            runtime=Runtime(config)
            for kind in ('model_services','controllers'):
                for spec in config.get(kind,[]):
                    if spec.get('autostart'):runtime.start_instance(kind,spec['id'])
            host,port=a.listen.rsplit(':',1)
            server=ThreadingHTTPServer((host,int(port)),handler(config,runtime))
            print(json.dumps({'service':'ride','pid':os.getpid(),'listen':a.listen,'workspace':config['workspace']}),flush=True)
            try:server.serve_forever()
            finally:server.server_close()
            return
        if not a.resource:p.error('Specify controller or model-service')
        kind=KINDS[a.resource]
        if a.command=='get':
            result=request(a.address,kind+('/'+a.target if a.target else ''))
        else:
            if not a.target:p.error('Specify a type when creating, or an existing instance name')
            name=getattr(a,'name',None) or a.target
            if a.command=='start':
                changes=json.loads(Path(a.config).read_text()) if a.config else {}
                builtin='request-throttling' if kind=='controllers' else 'vllm'
                if a.target==builtin or (kind=='model-services' and a.target=='mock-vllm'):changes.setdefault('type',a.target)
                for field in ('backend','endpoint','model_service','model','executor','transport','port','num_cpus','num_gpus'):
                    value=getattr(a,field,None)
                    if value is not None:changes[field]=value
                for field in ('runtime_env','resources'):
                    value=getattr(a,field,None)
                    if value is not None:changes[field]=json.loads(value)
                if a.model_arg is not None:changes['args']=a.model_arg
                if a.port is not None and kind=='controllers':changes['listen']='0.0.0.0:'+str(a.port)
                result=request(a.address,kind+'/'+name+'/start',changes)
            elif a.command=='stop':result=request(a.address,kind+'/'+name+'/stop',{})
            else:result=request(a.address,kind+'/'+name+('/logs' if a.command=='logs' else ''))
        if a.command=='logs':print(result['logs'],end='')
        else:print(json.dumps(result,indent=2,ensure_ascii=False))
    except (ValueError,OSError) as e:
        print('RIDE: '+str(e),file=sys.stderr);raise SystemExit(1)

if __name__=='__main__':main()
