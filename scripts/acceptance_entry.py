"""Cloud-only entrypoints for existing Ray deployment and evidence collection.
No Coder/Kubernetes creation and no implicit stop or retry of a submission.
"""
import argparse
import hashlib
import json
import shlex
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['deploy', 'accept'])
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text())
    args.output.mkdir(parents=True, exist_ok=True)
    from ride.__main__ import request
    from ray.job_submission import JobSubmissionClient
    client = JobSubmissionClient(plan['ray_address'])
    ledger = {'operation': args.operation, 'status': 'RUNNING', 'actions': [],
              'plan_sha256': hashlib.sha256(args.plan.read_bytes()).hexdigest()}
    def save():
        (args.output / (args.operation + '.json')).write_text(json.dumps(ledger, indent=2))
    def action(name, expected, function):
        record = {'name': name, 'expected': expected, 'status': 'RUNNING'}
        ledger['actions'].append(record)
        save()
        try:
            record['observation'] = function()
            record['status'] = 'PASS'
        except Exception as error:
            record.update(status='FAIL', error=str(error))
            raise
        finally:
            save()
    def wait(path):
        deadline = time.monotonic() + plan.get('timeout', 900)
        while time.monotonic() < deadline:
            try:
                record = request(plan['address'], path)
                if path == 'status' or record.get('ready') is True:
                    return record
                if record.get('job_status') in ('FAILED', 'STOPPED', 'SUCCEEDED'):
                    raise RuntimeError('Service terminated: ' + json.dumps(record))
            except (OSError, ValueError):
                pass
            time.sleep(2)
        raise TimeoutError(path + ' did not become Ready')
    try:
        action('ray', 'Selected existing Ray Jobs endpoint responds', lambda: client.get_version())
        if args.operation == 'deploy':
            receipt = args.output / 'management-submission.json'
            identifier = plan['management_job_id']
            if receipt.exists():
                raise RuntimeError('Submission receipt exists; inspect existing Job rather than resubmit')
            config = json.loads(Path(plan['config']).read_text())
            if any(s.get('autostart') for k in ('model_services', 'controllers') for s in config.get(k, [])):
                raise ValueError('Use autostart=false: models must be Ready before Controllers')
            command = 'python -m ride start --config ' + shlex.quote(str(Path(plan['config']).resolve())) + ' --listen ' + shlex.quote(plan['listen'])
            def submit():
                receipt.write_text(json.dumps({'job_id': identifier, 'entrypoint': command, 'status': 'SUBMISSION_INTENT'}))
                return client.submit_job(submission_id=identifier, entrypoint=command,
                    runtime_env=plan.get('runtime_env', {}), entrypoint_num_cpus=0.1)
            action('management', 'One explicitly named management Job submitted', submit)
            action('management_ready', 'RIDE API available', lambda: wait('status'))
            for kind in ('model_services', 'controllers'):
                route = kind.replace('_', '-')
                for spec in config.get(kind, []):
                    path = route + '/' + spec['id']
                    action('start_' + spec['id'], 'Instance submitted through RIDE', lambda path=path: request(plan['address'], path + '/start', {}))
                    action('ready_' + spec['id'], 'Job running and service Ready', lambda path=path: wait(path))
            ledger['status'] = 'PASS'
        else:
            from ride.acceptance import run
            for target in plan['acceptance_targets']:
                report = run(plan['address'], target['controller'], target['model_service'],
                    args.output / (target['controller'] + '.json'), lifecycle=True,
                    model=target['model'], timeout=plan.get('timeout', 900))
                ledger['actions'].append({'name': target['controller'], 'status': report['status'],
                    'complete': report['complete'], 'checks': report['checks']})
                save()
                if report['status'] != 'PASS':
                    raise RuntimeError('Controller deployment/lifecycle check failed')
            ledger['status'] = 'INCOMPLETE'
            ledger['remaining'] = ['management adoption', 'controller-specific negative cases',
                'source identity and program semantics', 'same-input performance']
            # Narrow lifecycle checks must never be reported as full acceptance.
            raise SystemExit(3)
    except Exception as error:
        ledger.update(status='FAIL', error=str(error))
        raise
    finally:
        save()
        (args.output / 'evidence-sha256.json').write_text(json.dumps({p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in args.output.glob('*.json') if p.name != 'evidence-sha256.json'}, indent=2))


if __name__ == '__main__':
    main()
