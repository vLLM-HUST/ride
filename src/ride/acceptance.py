"""Versioned acceptance contract; execution results never imply performance gains."""
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

CONTRACT = {
    'schema_version': 'ride.acceptance/v1',
    'deployment_checks': ['control_plane','model_ready','controller_ready','dependency','idempotence','stop_isolation','restore','inference','adoption'],
    'checks': {
        'control_plane': 'Management service identifies itself as RIDE',
        'model_ready': 'Owned model Job is RUNNING and health is Ready',
        'controller_ready': 'Owned Controller Job is RUNNING and Ready',
        'dependency': 'Controller uses the selected model endpoint',
        'idempotence': 'Starting a running instance preserves its Job ID',
        'stop_isolation': 'Stopping Controller leaves the same model Job Ready',
        'restore': 'Controller restart creates a new Ready Job',
        'inference': 'Real OpenAI response has nonempty content and positive token counts',
        'adoption': 'A new management process retains run identity and all selected Job IDs',
        'program_semantics': 'Controller-specific enter/pause/resume/complete/release and input/history correctness evidence required',
        'source_identity': 'Pinned source origin and loaded file hashes must be compared against an expected manifest',
        'web_ui': 'Cloud workspace UI actions must be independently exercised and recorded',
        'access_boundary': 'Authentication and cross-origin ownership controls require dedicated negative checks',
        'performance': 'Requires separate same-input baseline and upstream experiment',
    },
}

def run(address, controller, model_service, output, lifecycle=False, model=None,
        baseline=None, timeout=120, request=None):
    if request is None:
        from .__main__ import request
    def call(path, body=None): return request(address, path, body)
    def selected(snapshot, kind, identifier):
        return next(x for x in snapshot[kind] if x['id'] == identifier)
    def await_state(name, predicate):
        deadline=time.monotonic()+timeout
        while True:
            value=call('controllers/'+name)
            if predicate(value): return value
            if time.monotonic()>=deadline: raise TimeoutError('Controller state deadline exceeded')
            time.sleep(1)
    report={'schema_version':CONTRACT['schema_version'],
        'started_at':datetime.now(timezone.utc).isoformat(),
        'address':address,'controller':controller,'model_service':model_service,
        'checks':{key:{'status':'NOT_RUN','criterion':criterion} for key,criterion in CONTRACT['checks'].items()},
        'evidence':{},'scope':'Deployment and lifecycle; no performance or full policy equivalence claim'}
    def check(key, function):
        try:
            result=function(); report['evidence'][key]=result
            if not result['passed']: raise ValueError(result.get('reason','Criterion not satisfied'))
            report['checks'][key]['status']='PASS'
            return result
        except Exception as error:
            report['checks'][key].update(status='FAIL',error=str(error))
            return None
    try:
        first=call('status');report['before']=first
        engine=selected(first,'model_services',model_service); router=selected(first,'controllers',controller)
        check('control_plane',lambda:{'passed':first.get('name')=='RIDE','workspace':first.get('workspace')})
        check('model_ready',lambda:{'passed':engine.get('ready') is True and engine.get('job_status')=='RUNNING','record':engine})
        check('controller_ready',lambda:{'passed':router.get('ready') is True and router.get('job_status')=='RUNNING','record':router})
        check('dependency',lambda:{'passed':router.get('backend')==engine.get('endpoint'),'backend':router.get('backend'),'endpoint':engine.get('endpoint')})
        ready=all(report['checks'][key]['status']=='PASS' for key in ('control_plane','model_ready','controller_ready','dependency'))
        if ready and lifecycle:
            def idempotence():
                r=call('controllers/'+controller+'/start',{})
                return {'passed':r.get('unchanged') is True and r.get('job_id')==router['job_id'],'response':r}
            check('idempotence',idempotence)
            def stop_isolation():
                response=call('controllers/'+controller+'/stop',{})
                stopped=await_state(controller,lambda x:x['job_status']=='STOPPED')
                current=call('model-services/'+model_service)
                return {'passed':current.get('ready') is True and current['job_id']==engine['job_id'],'response':response,'stopped':stopped,'model':current}
            stopped=check('stop_isolation',stop_isolation)
            # Always attempt restoration after an accepted stop, even if isolation failed.
            def restore():
                r=call('controllers/'+controller+'/start',{})
                current=await_state(controller,lambda x:x.get('ready') is True)
                return {'passed':current['job_id']!=router['job_id'],'response':r,'record':current}
            check('restore',restore)
        if ready and model:
            def inference():
                current=call('controllers/'+controller)
                payload={'model':model,'messages':[{'role':'user','content':'Reply with one word: hello'}],'max_tokens':16,'temperature':0}
                req=Request(current['endpoint'].rstrip('/')+'/v1/chat/completions',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
                with urlopen(req,timeout=timeout) as response: data=json.load(response)
                usage=data.get('usage',{});choices=data.get('choices',[])
                passed=bool(choices and choices[0].get('message',{}).get('content')) and usage.get('prompt_tokens',0)>0 and usage.get('completion_tokens',0)>0
                return {'passed':passed,'request':payload,'response':data,'note':'Ordinary request; does not prove program scheduling semantics'}
            check('inference',inference)
        if baseline:
            def adoption():
                previous=json.loads(Path(baseline).read_text())['after'];current=call('status')
                jobs={}
                for kind,name in [('controllers',controller),('model_services',model_service)]:
                    old=selected(previous,kind,name);new=selected(current,kind,name)
                    jobs[kind]={'before':old['job_id'],'after':new['job_id'],'ready':new.get('ready')}
                passed=previous['run_id']==current['run_id'] and previous.get('management_pid')!=current.get('management_pid') and previous.get('management_pid') is not None and all(x['before']==x['after'] and x['ready'] for x in jobs.values())
                return {'passed':passed,'jobs':jobs,'previous_pid':previous.get('management_pid'),'current_pid':current.get('management_pid'),'run_id':current['run_id']}
            check('adoption',adoption)
        report['after']=call('status')
        for kind,name in [('controllers',controller),('model-services',model_service)]:
            report['evidence'][kind+'_logs']=call(kind+'/'+name+'/logs')
    except Exception as error:
        report['fatal_error']=str(error)
    report['finished_at']=datetime.now(timezone.utc).isoformat()
    report['status']='FAIL' if 'fatal_error' in report or any(x['status']=='FAIL' for x in report['checks'].values()) else 'PASS'
    report['complete']=all(report['checks'][key]['status']=='PASS' for key in CONTRACT['deployment_checks'])
    path=Path(output);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    return report
