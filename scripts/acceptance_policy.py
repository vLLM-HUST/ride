"""Real NPU policy supplement. Fixed workload, actual states, no scheduler injection."""
import concurrent.futures
import csv
import json
import time
from pathlib import Path
from acceptance_scenarios import http, payload, valid, signature


def pressure(plan, output):
    spec = plan['pressure_instances']['controllers'][0]
    base = spec['endpoint']; model = plan['pressure_model']
    assert http(base+'/programs')[1] == {}, 'Pressure fixture must start empty'
    samples=[]; results={}; released=[]
    def save():
        (output/'pressure-progress.json').write_text(json.dumps({'samples':samples,'results':results,'released':released},indent=2))
    messages=[{'role':'user','content':'Explain the following observations: '+('blue sky and scattered sunlight. '*100)}]
    tokens=http(spec['backend']+'/tokenize',{'model':model,'messages':messages,'add_generation_prompt':True})
    assert tokens[0]==200 and 400<tokens[1]['count']<1800, tokens
    identifiers=['pressure-program-'+str(i) for i in range(32)]
    pool=concurrent.futures.ThreadPoolExecutor(max_workers=32)
    def step(identifier, history):
        body=payload(model,history);body['program_id']=identifier
        reply=valid(http(base+'/v1/chat/completions',body))
        return {'request':body,'response':reply}
    futures={pool.submit(step,i,messages):i for i in identifiers}
    deadline=time.monotonic()+180; paused=None
    try:
        while time.monotonic()<deadline:
            states=http(base+'/programs')[1]
            samples.append({'time':time.time(),'programs':states})
            for future, identifier in futures.items():
                if future.done() and identifier not in results: results[identifier]=future.result()
            candidates=[i for i,s in states.items() if s['status']=='paused' and i in results]
            if candidates:
                paused=candidates[0];save();break
            save();time.sleep(.5)
        assert paused, 'No completed Program actually paused within pressure deadline'
        history=messages+[results[paused]['response']['choices'][0]['message'],{'role':'user','content':'Explain one more observation.'}]
        follow=pool.submit(step,paused,history)
        # Retained completed Programs occupy actual scheduler capacity; release these,
        # rather than altering capacity or scheduler state, to enable resumption.
        deadline=time.monotonic()+180
        while time.monotonic()<deadline:
            for future,identifier in futures.items():
                if future.done() and identifier not in results:results[identifier]=future.result()
            for identifier in list(results):
                if identifier!=paused and identifier not in released:
                    response=http(base+'/programs/release',{'program_id':identifier})
                    assert response[0]==200 and response[1]['released'];released.append(identifier)
            states=http(base+'/programs')[1];samples.append({'time':time.time(),'programs':states});save()
            if follow.done() and all(f.done() for f in futures):break
            time.sleep(.2)
        assert follow.done() and all(f.done() for f in futures), 'Resume/drain deadline exceeded'
        resumed=follow.result(); state=http(base+'/programs')[1][paused]
        assert state['status']=='acting' and state['step_count']==2,state
        tokenize=http(spec['backend']+'/tokenize',{'model':model,'messages':history,'add_generation_prompt':True})
        assert tokenize[1]['count']==resumed['response']['usage']['prompt_tokens']
        response=http(base+'/programs/release',{'program_id':paused});assert response[1]['released']
        assert http(base+'/programs')[1]=={}, 'Released Programs leaked'
        result={'paused_program':paused,'resumed':resumed,'completed_state':state,'tokenize':tokenize,'initial_prompt_tokens':tokens[1]['count'],'samples':samples,'first_steps':results,'released':released+[paused]}
        (output/'pressure-result.json').write_text(json.dumps(result,indent=2));return result
    finally:
        save()
        pool.shutdown(wait=False,cancel_futures=True)


def comparison(plan, output):
    from ride.__main__ import request
    rows=[];replies=[]
    for concurrency in (1,4,8):
        for repeat in range(2):
            # Alternate ordering to avoid always placing the baseline first.
            names=['direct','demo','request-throttling']
            if repeat: names.reverse()
            for name in names:
                target=plan['acceptance_targets'][0]
                record=request(plan['address'],'model-services/'+target['model_service']) if name=='direct' else request(plan['address'],'controllers/'+name)
                body=payload(target['model']);start=time.monotonic()
                with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
                    values=list(pool.map(lambda _:valid(http(record['endpoint']+'/v1/chat/completions',body)),range(concurrency)))
                elapsed=time.monotonic()-start
                replies.append({'strategy':name,'concurrency':concurrency,'repeat':repeat,'responses':values})
                rows.append({'strategy':name,'concurrency':concurrency,'repeat':repeat,'completed_requests':concurrency,'elapsed_seconds':elapsed,'requests_per_second':concurrency/elapsed})
                (output/'comparison-responses.json').write_text(json.dumps(replies,indent=2))
                with (output/'comparison.csv').open('w') as f:
                    writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    signatures={signature(v) for r in replies for v in r['responses']}
    assert len(signatures)==1,'Same-input output/token mismatch'
    return {'rows':rows,'output_token_hash':signatures.pop(),'scope':'Bounded request throughput, ordinary untracked requests; no program-aware performance or Figure1a claim'}
