"""Cloud-only entrypoints for existing Ray deployment and evidence collection.
No Coder/Kubernetes creation and no implicit stop or retry of a submission.
"""
import argparse
import hashlib
import json
import shlex
import time
from urllib.request import Request, urlopen
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['deploy', 'accept', 'accept-policy'])
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text())
    args.output.mkdir(parents=True, exist_ok=True)
    from ride.__main__ import request
    class JobsClient:
        def call(self, path, body=None):
            request = Request(plan['ray_address'].rstrip('/') + path, data=None if body is None else json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
            with urlopen(request, timeout=30) as response:
                return json.load(response)
        def get_version(self):
            return self.call('/api/version')
        def submit_job(self, **kwargs):
            return self.call('/api/jobs/', kwargs)
    client = JobsClient()
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
        from deployment_identity import verify_live
        action('deployment_identity', 'Live Coder owner/template/workspace/Ray binding verified', lambda: verify_live(plan))
        action('ray', 'Selected existing Ray Jobs endpoint responds', lambda: client.get_version())
        if args.operation == 'deploy' and plan.get('payload'):
            from deployment_payload import prepare_payload
            action('payload', 'Explicit Pod identity, source hashes and remote readback match; no overwrite',
                   lambda: prepare_payload(plan['payload']))
        if args.operation == 'accept-policy':
            from acceptance_policy import pressure, comparison
            prerequisite = json.loads(Path(plan['prerequisite']).read_text())
            assert prerequisite['status'] == 'INCOMPLETE' and all(x['status'] == 'PASS' for x in prerequisite['actions']), 'Functional prerequisite failed'
            for kind in ('model_services', 'controllers'):
                route = kind.replace('_', '-')
                for spec in plan['pressure_instances'][kind]:
                    path = route + '/' + spec['id']
                    action('start_' + spec['id'], 'Owned pressure fixture submitted via RIDE', lambda path=path, spec=spec: request(plan['address'], path + '/start', spec))
                    action('ready_' + spec['id'], 'Real pressure service Ready', lambda path=path: wait(path))
            action('capacity_pressure', 'Actual paused Program resumes, completes and releases', lambda: pressure(plan, args.output))
            action('same_input_comparison', 'Real direct and Controller responses match; timings archived without assumed speedup', lambda: comparison(plan, args.output))
            ledger['status'] = 'PASS'
            ledger['scope'] = 'RIDE real NPU functional/lifecycle and bounded pressure acceptance; short comparison is not research performance reproduction'
        elif args.operation == 'deploy':
            receipt = args.output / 'management-submission.json'
            identifier = plan['management_job_id']
            if receipt.exists():
                raise RuntimeError('Submission receipt exists; inspect existing Job rather than resubmit')
            config = json.loads(Path(plan['config']).read_text())
            if any(s.get('autostart') for k in ('model_services', 'controllers') for s in config.get(k, [])):
                raise ValueError('Use autostart=false: models must be Ready before Controllers')
            command = 'python -m ride start --config ' + shlex.quote(plan.get('management_config', str(Path(plan['config']).resolve()))) + ' --listen ' + shlex.quote(plan['listen'])
            def submit():
                receipt.write_text(json.dumps({'job_id': identifier, 'entrypoint': command, 'status': 'SUBMISSION_INTENT'}))
                return client.submit_job(submission_id=identifier, entrypoint=command,
                    runtime_env=plan.get('runtime_env', {}), entrypoint_num_cpus=0.1, entrypoint_resources=plan.get('management_resources', {}))
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
            from acceptance_scenarios import demo, programs, adoption
            for target in plan['acceptance_targets']:
                record = request(plan['address'], 'controllers/' + target['controller'])
                scenario = demo if record['type'] == 'demo' else programs
                action('real_control_' + target['controller'], 'Actual control, output/token and negative-case evidence', lambda target=target, record=record, scenario=scenario: scenario(plan, target, record))
                report = run(plan['address'], target['controller'], target['model_service'],
                    args.output / (target['controller'] + '.json'), lifecycle=True,
                    model=target['model'], timeout=plan.get('timeout', 900))
                ledger['actions'].append({'name': target['controller'], 'status': report['status'],
                    'complete': report['complete'], 'checks': report['checks']})
                save()
                if report['status'] != 'PASS':
                    raise RuntimeError('Controller deployment/lifecycle check failed')
            action('management_adoption', 'New management process retains same instance Jobs and real requests', lambda: adoption(plan, client, wait))
            for target in plan['acceptance_targets']:
                from acceptance_scenarios import http, valid, payload
                current = request(plan['address'], 'controllers/' + target['controller'])
                action('post_adoption_' + target['controller'], 'Real inference succeeds after management restart', lambda target=target, current=current: valid(http(current['endpoint']+'/v1/chat/completions', payload(target['model']))))
            ledger['status'] = 'INCOMPLETE'
            ledger['remaining'] = ['capacity-pressure pause/resume', 'same-input performance']
            ledger['scope'] = 'Real NPU RIDE deployment, two Controller control/negative cases and lifecycle; policy/performance incomplete'
            # Narrow lifecycle checks must never be reported as full acceptance.
            raise SystemExit(3)
    except Exception as error:
        ledger.update(status='FAIL', error=str(error))
        raise
    finally:
        try:
            snapshot = request(plan['address'], 'status')
            (args.output / 'final-status.json').write_text(json.dumps(snapshot, indent=2))
            identifiers = [x['job_id'] for kind in ('controllers','model_services') for x in snapshot[kind] if x.get('job_id')]
            identifiers.append(plan['management_job_id'])
            for job_id in identifiers:
                (args.output / (job_id + '-log.json')).write_text(json.dumps(client.call('/api/jobs/' + job_id + '/logs'), indent=2))
        except Exception as error:
            ledger['archive_error'] = str(error)
            if ledger['status'] == 'PASS':
                ledger['status'] = 'FAIL'
        save()
        (args.output / 'evidence-sha256.json').write_text(json.dumps({p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in args.output.glob('*.json') if p.name != 'evidence-sha256.json'}, indent=2))


if __name__ == '__main__':
    main()
