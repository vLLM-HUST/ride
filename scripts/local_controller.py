"""Existing RIDE CLI on a CPU devbox; models remain external and untouched."""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import sys
import time
import uuid
from urllib.request import urlopen

from ride.local_process import LocalProcessClient
from ride.__main__ import request


def run(action, plan_path, output):
    if action not in ('local-start','local-stop','local-restart'):
        raise ValueError('Unsupported local lifecycle action')
    plan_path = Path(plan_path).resolve()
    plan = json.loads(plan_path.read_text())
    config_path = Path(plan['config']).resolve()
    config = json.loads(config_path.read_text())
    if config.get('deployment') != 'local' or config.get('model_services'):
        raise ValueError('Explicit local Controller configuration with external models required')
    if not config.get('controllers'):
        raise ValueError('At least one Controller required')
    address = plan['management_endpoint']
    timeout = plan['readiness_timeout_seconds']
    if not isinstance(timeout, (int,float)) or not 0 < timeout <= 300:
        raise ValueError('Bounded readiness timeout required')
    # Management stays loopback; Coder owner-only forwarding provides access.
    from urllib.parse import urlsplit
    parsed = urlsplit(address)
    if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or not parsed.port or parsed.path:
        raise ValueError('Management endpoint must be a loopback HTTP origin')
    state = Path(config['state_file'])
    if not state.is_absolute():
        raise ValueError('Absolute persistent state_file required')
    client = LocalProcessClient(state.parent / (state.stem + '-manager'))
    active = client.root / 'active.json'
    identifier = json.loads(active.read_text())['identifier'] if active.exists() else 'ride-local-manager'
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    record = {'action':action, 'executor':'local', 'plan_sha256':hashlib.sha256(plan_path.read_bytes()).hexdigest(),
              'config_sha256':hashlib.sha256(config_path.read_bytes()).hexdigest(), 'status':'RUNNING'}
    target = output / (action + '-result.json')
    if target.exists():
        raise ValueError('Evidence already exists; use a new output directory')
    target.write_text(json.dumps(record,indent=2))
    try:
        if action == 'local-restart':
            expected = {'config':str(config_path),'sha256':record['config_sha256']}
            if json.loads((client.root/'deployment.json').read_text()) != expected:
                raise ValueError('Existing management configuration conflict')
            before = request(address,'status')
            own = json.loads(state.read_text())
            if before.get('run_id') != own['run_id'] or before.get('workspace') != config['workspace']:
                raise ValueError('Management identity mismatch')
            if not before.get('controllers') or not all(x.get('ready') and x.get('job_status') == 'RUNNING' for x in before['controllers']):
                raise ValueError('Restart requires healthy existing Controllers')
            if client.get_job_status(identifier).value != 'RUNNING':
                raise ValueError('Management process is not running')
            record['before'] = before
            target.write_text(json.dumps(record,indent=2))
            if not client.stop_job(identifier):
                raise RuntimeError('Management stop not confirmed')
            # Record the new identity before submission. Failed or unknown submission
            # is never repaired by silently creating another management process.
            identifier = 'ride-local-manager-' + uuid.uuid4().hex
            temporary = active.with_suffix('.tmp')
            temporary.write_text(json.dumps({'identifier':identifier}))
            temporary.replace(active)
            command = shlex.join([sys.executable,'-m','ride','serve','--config',str(config_path),
                                  '--listen','127.0.0.1:'+str(parsed.port)])
            record.update(manager_identifier=identifier,command=command)
            target.write_text(json.dumps(record,indent=2))
            client.submit_job(submission_id=identifier,entrypoint=command,runtime_env={},entrypoint_resources={})
            deadline = time.monotonic()+timeout
            while time.monotonic() < deadline:
                try:
                    after = request(address,'status')
                except (OSError,ValueError):
                    time.sleep(.2)
                    continue
                if after.get('run_id') != before['run_id'] or after.get('workspace') != before['workspace']:
                    raise ValueError('Management adoption identity mismatch')
                if after.get('management_pid') == before['management_pid']:
                    raise ValueError('Management PID did not change')
                old_jobs = {x['id']:x['job_id'] for x in before['controllers']}
                new_jobs = {x['id']:x['job_id'] for x in after['controllers']}
                if old_jobs != new_jobs:
                    raise ValueError('Controller identity changed during management restart')
                if not all(x.get('ready') and x.get('job_status') == 'RUNNING' for x in after['controllers']):
                    raise ValueError('Controller lost readiness during management restart')
                record['observed'] = after
                break
            else:
                raise RuntimeError('Management restart readiness timed out')
        elif action == 'local-start':
            intent = client.root / 'deployment.json'
            expected = {'config':str(config_path),'sha256':record['config_sha256']}
            if intent.exists():
                if json.loads(intent.read_text()) != expected:
                    raise ValueError('Existing management configuration conflict')
                if client.get_job_status(identifier).value != 'RUNNING':
                    raise ValueError('Previous manager ended; inspect and use a new state/run')
            else:
                with intent.open('x') as stream: json.dump(expected,stream)
                command = shlex.join([sys.executable,'-m','ride','serve','--config',str(config_path),
                                      '--listen','127.0.0.1:'+str(parsed.port)])
                record['command'] = command
                client.submit_job(submission_id=identifier,entrypoint=command,runtime_env={},entrypoint_resources={})
            deadline = time.monotonic()+timeout
            last = None
            started = False
            while time.monotonic() < deadline:
                try:
                    observed = request(address,'status')
                    own = json.loads(state.read_text())
                    if observed.get('run_id') != own['run_id'] or observed.get('workspace') != config['workspace']:
                        raise ValueError('Management identity mismatch')
                    if not started:
                        for spec in config['controllers']:
                            request(address,'controllers/'+spec['id']+'/start',{})
                        started = True
                    observed = request(address,'status')
                    if any(x.get('job_status') in ('FAILED','STOPPED','SUCCEEDED') for x in observed['controllers']):
                        raise RuntimeError('Controller terminated; inspect logs before explicit restart')
                    if all(x.get('ready') for x in observed['controllers']):
                        record['observed'] = observed
                        break
                except (OSError,ValueError) as error:
                    last = str(error)
                time.sleep(.2)
            else:
                raise RuntimeError('Controller readiness timed out: '+str(last))
        else:
            observed = request(address,'status')
            own = json.loads(state.read_text())
            if observed.get('run_id') != own['run_id']:
                raise ValueError('Management identity mismatch')
            record['controller_stops'] = [request(address,'controllers/'+x['id']+'/stop',{}) for x in config['controllers']]
            record['manager_stopped'] = client.stop_job(identifier)
        record['status'] = 'PASS'
        record['scope'] = 'Controller deployment/readiness only; real model, lifecycle semantics and performance require separate evidence'
    except Exception as error:
        record.update(status='FAIL',error=str(error))
        raise
    finally:
        target.write_text(json.dumps(record,indent=2)+'\n')
        if (client.root/identifier/'stdout.log').exists():
            (output/'management.log').write_text(client.get_job_logs(identifier))
    print(json.dumps(record,indent=2))


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['local-start','local-stop','local-restart'])
    parser.add_argument('plan')
    parser.add_argument('output')
    args=parser.parse_args()
    run(args.action,args.plan,args.output)
