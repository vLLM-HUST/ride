"""Real backend checks. No synthetic backend or synthetic token evidence."""
import concurrent.futures
import hashlib
import json
import threading
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from pathlib import Path


def http(url, body=None):
    request = Request(url, data=None if body is None else json.dumps(body).encode(), headers={'Content-Type':'application/json'})
    try:
        with urlopen(request, timeout=300) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, json.loads(error.read())


def payload(model, messages=None):
    return {'model':model,'messages':messages or [{'role':'user','content':'Explain why the sky is blue.'}],
            'max_tokens':64,'ignore_eos':True,'temperature':0,'stream':False}


def valid(value):
    status, body = value
    assert status == 200, value
    assert body.get('choices') and body['usage']['prompt_tokens'] > 0, value
    assert body['usage']['completion_tokens'] == 64, value
    return body


def signature(body):
    text = json.dumps({'message':body['choices'][0]['message'],'usage':body['usage']},sort_keys=True)
    return hashlib.sha256(text.encode()).hexdigest()


def demo(plan, target, record):
    base = record['endpoint']; backend = record['backend']; body = payload(target['model'])
    before = http(base+'/status')[1]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        replies = list(pool.map(lambda _: valid(http(base+'/v1/chat/completions',body)),range(4)))
    after = http(base+'/status')[1]
    assert after['peak_active']==1 and after['queued_total']>before['queued_total'], after
    assert after['completed']-before['completed']==4 and after['failed']==before['failed'], after
    direct = valid(http(backend+'/v1/chat/completions',body))
    assert all(signature(x)==signature(direct) for x in replies), 'Direct/demo output or token mismatch'
    negative=[]
    for request in ([],dict(body,stream=True),dict(body,model='missing-model')):
        response = http(base+'/v1/chat/completions',request)
        assert response[0] in (400,404), response
        negative.append(response)
    restored = valid(http(base+'/v1/chat/completions',body))
    final = http(base+'/status')[1]
    assert final['active']==0 and final['waiting']==0, final
    return {'before':before,'after':after,'final':final,'responses':replies,'direct':direct,
            'negative':negative,'after_errors':restored,'output_token_hash':signature(direct)}


def programs(plan, target, record):
    base = record['endpoint']; backend=record['backend']
    identity = http(base+'/migration-identity')[1]
    manifest=json.loads(Path(plan['upstream_manifest']).read_text())
    # Source paths are rooted at the ThunderAgent package, not an old checkout.
    expected=manifest['files']
    source_root = next(parent for parent in Path(identity['router_file']).parents if parent.name == 'ThunderAgent')
    actual = {Path(x['file']).relative_to(source_root).as_posix():x['sha256'] for x in identity['loaded_sources']}
    assert actual==expected and len(actual)==17, 'Loaded source manifest mismatch'
    assert identity['backends']==[backend] and identity['scheduling_enabled'] is True, identity
    assert identity['transport']['max_keepalive_connections']==0, identity
    initial=http(base+'/programs')[1]
    ordinary=valid(http(base+'/v1/chat/completions',payload(target['model'])))
    assert http(base+'/programs')[1]==initial, 'Ordinary request created Program state'
    stop=threading.Event(); samples=[]
    def sample():
        while not stop.is_set():
            samples.append({'time':time.time(),'programs':http(base+'/programs')[1]})
            stop.wait(.05)
    sampler=threading.Thread(target=sample);sampler.start()
    results=[]
    def workflow(index):
        identifier='acceptance-program-'+str(index); messages=[{'role':'user','content':'Explain why the sky is blue.'}]; rounds=[]
        for step in range(3):
            body=payload(target['model'],messages); body['program_id']=identifier
            tokens=http(backend+'/tokenize',{'model':target['model'],'messages':messages,'add_generation_prompt':True})
            reply=valid(http(base+'/v1/chat/completions',body))
            assert tokens[0]==200 and tokens[1]['count']==reply['usage']['prompt_tokens'], (tokens,reply['usage'])
            state=http(base+'/programs')[1][identifier]
            assert state['step_count']==step+1 and state['status']=='acting',state
            rounds.append({'request':body,'response':reply,'tokenize':tokens[1],'state':state})
            messages=messages+[reply['choices'][0]['message'],{'role':'user','content':'Now give another short explanation.'}]
            time.sleep(.15)
        released=http(base+'/programs/release',{'program_id':identifier})
        assert released[0]==200 and released[1]['released'] is True,released
        assert identifier not in http(base+'/programs')[1]
        return {'program_id':identifier,'rounds':rounds,'released':released}
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(workflow,range(2)))
    finally:
        stop.set();sampler.join(timeout=10)
    reasoning=any(v['status']=='reasoning' for x in samples for v in x['programs'].values())
    assert reasoning,'No actual reasoning state observed'
    assert http(base+'/programs')[1]==initial,'Program state leaked after release'
    invalid=http(base+'/v1/chat/completions',[])
    assert invalid[0]==400,invalid
    return {'identity':identity,'ordinary_response':ordinary,'programs':results,'samples':samples,
            'final_programs':http(base+'/programs')[1],'invalid_request':invalid,
            'source_files':len(actual),'pause_resume':'NOT_RUN: capacity-pressure scenario separate'}


def adoption(plan, client, wait):
    from ride.__main__ import request
    before=request(plan['address'],'status')
    receipt=json.loads((Path(plan['deployment_output'])/'management-submission.json').read_text())
    identifier=receipt['job_id'];info=client.call('/api/jobs/'+identifier)
    assert info['entrypoint']==receipt['entrypoint'],'Management ownership mismatch'
    response=client.call('/api/jobs/'+identifier+'/stop',{})
    deadline=time.monotonic()+60
    while client.call('/api/jobs/'+identifier)['status'] not in ('STOPPED','FAILED','SUCCEEDED'):
        if time.monotonic()>deadline:raise TimeoutError('Management stop timeout')
        time.sleep(1)
    new=identifier+'-adopt'
    intent=Path(plan['deployment_output'])/'adoption-submission.json'
    if intent.exists():raise RuntimeError('Adoption intent exists; inspect instead of duplicate submission')
    intent.write_text(json.dumps({'job_id':new,'entrypoint':receipt['entrypoint']}))
    client.submit_job(submission_id=new,entrypoint=receipt['entrypoint'],runtime_env=plan['runtime_env'],entrypoint_num_cpus=.1,entrypoint_resources=plan.get('management_resources',{}))
    after=wait('status')
    assert after['management_pid']!=before['management_pid'] and after['run_id']==before['run_id']
    for kind in ('controllers','model_services'):
        assert [(x['id'],x['job_id']) for x in after[kind]]==[(x['id'],x['job_id']) for x in before[kind]]
        assert all(x['ready'] for x in after[kind]),after
    return {'before':before,'after':after,'stop_response':response,'management_job':new}
