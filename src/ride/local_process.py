"""Owned devbox Controller processes, with durable identity and no Ray dependency.

Only foreground process groups are supported. A persisted, uniquely named worker
survives management restart. Unknown identity never authorizes a signal/retry.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys
import time
import uuid
from types import SimpleNamespace


def _write(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def _birth(pid):
    result = subprocess.run(['ps', '-p', str(pid), '-o', 'lstart='],
                            capture_output=True, text=True, check=True)
    if not result.stdout.strip():
        raise RuntimeError('Owned process is absent')
    return result.stdout.strip()


def _matches(record, directory):
    try:
        pid = record['pid']
        if type(pid) is not int or pid <= 1 or os.getpgid(pid) != pid:
            return False
        args = subprocess.run(['ps', '-ww', '-p', str(pid), '-o', 'args='],
                              capture_output=True, text=True, check=True).stdout
        return (_birth(pid) == record['birth'] and record['token'] in args
                and str(directory) in args and 'ride.local_process' in args)
    except (KeyError, OSError, subprocess.SubprocessError, RuntimeError):
        return False


def _terminal_after_exit(directory, previous):
    latest = json.loads((directory / 'process.json').read_text())
    if (latest.get('status') in ('STOPPED','SUCCEEDED','FAILED')
            and all(latest.get(key)==previous.get(key) for key in ('pid','birth','token'))):
        return latest['status']
    return None


class LocalProcessClient:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.children = {}

    def _directory(self, identifier):
        if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,200}', identifier):
            raise ValueError('Invalid owned process identifier')
        return self.root / identifier

    def submit_job(self, *, submission_id, entrypoint, runtime_env, entrypoint_resources, **options):
        if entrypoint_resources or options.get('entrypoint_num_gpus', 0):
            raise ValueError('Local Controller cannot reserve Ray/accelerator resources')
        if set(runtime_env) - {'env_vars'}:
            raise ValueError('Local runtime_env supports env_vars only; install dependencies first')
        variables = runtime_env.get('env_vars', {})
        if not isinstance(variables, dict) or not all(isinstance(k,str) and isinstance(v,str) for k,v in variables.items()):
            raise ValueError('env_vars must contain strings')
        args = shlex.split(entrypoint)
        if not args:
            raise ValueError('Empty Controller command')
        # Preserve the management interpreter/installed environment.
        if args[0] == 'python':
            args[0] = sys.executable
        directory = self._directory(submission_id)
        directory.mkdir(mode=0o700)  # exclusive intent; never resubmit unknown outcome
        token = uuid.uuid4().hex
        _write(directory / 'command.json', {'args': args})
        _write(directory / 'process.json', {'status': 'PENDING', 'token': token})
        environment = {**os.environ, **variables}
        # The worker itself must remain importable even with a Controller PYTHONPATH.
        package_root = str(Path(__file__).resolve().parents[1])
        environment['PYTHONPATH'] = os.pathsep.join(filter(None, [package_root, environment.get('PYTHONPATH')]))
        with (directory / 'stdout.log').open('ab', buffering=0) as output:
            child = subprocess.Popen([sys.executable, '-m', 'ride.local_process',
                '--worker', str(directory), '--token', token], env=environment,
                stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                start_new_session=True)
        self.children[submission_id] = child
        # Wait only for the durable identity handshake, not service readiness.
        for _ in range(250):
            record = json.loads((directory / 'process.json').read_text())
            if record['status'] != 'PENDING':
                return submission_id
            if child.poll() is not None:
                raise RuntimeError('Local worker exited before identity handshake; inspect logs')
            time.sleep(.02)
        raise RuntimeError('Unknown local worker outcome; inspect before retrying')

    def get_job_status(self, identifier):
        directory = self._directory(identifier)
        record = json.loads((directory / 'process.json').read_text())
        status = record['status']
        if status == 'RUNNING' and not _matches(record, directory):
            terminal = _terminal_after_exit(directory, record)
            if terminal is not None:return SimpleNamespace(value=terminal)
            raise RuntimeError('Owned process identity unavailable or changed')
        return SimpleNamespace(value=status)

    def get_job_logs(self, identifier):
        return (self._directory(identifier) / 'stdout.log').read_text(errors='replace')

    def stop_job(self, identifier):
        directory = self._directory(identifier)
        record = json.loads((directory / 'process.json').read_text())
        if record['status'] in ('STOPPED','SUCCEEDED','FAILED'):
            return False
        if not _matches(record, directory):
            if _terminal_after_exit(directory, record) is not None:return False
            raise RuntimeError('Refusing signal: owned process identity unavailable or changed')
        os.killpg(record['pid'], signal.SIGTERM)
        for _ in range(250):
            if json.loads((directory / 'process.json').read_text())['status'] in ('STOPPED','SUCCEEDED','FAILED'):
                child = self.children.get(identifier)
                if child is not None:
                    child.wait(timeout=5)
                return True
            time.sleep(.02)
        # Preserve unknown outcome. Never escalate using an unverified stale PID.
        raise RuntimeError('Controller stop timed out; inspect owned process group')


def _worker(directory, token):
    path = Path(directory)
    record = json.loads((path / 'process.json').read_text())
    if record != {'status':'PENDING','token':token}:
        raise RuntimeError('Worker intent mismatch')
    stopped = False
    def terminate(signum, frame):
        nonlocal stopped
        stopped = True  # SIGTERM reaches the entire owned group, including child.
    signal.signal(signal.SIGTERM, terminate)
    record.update(pid=os.getpid(), birth=_birth(os.getpid()), status='RUNNING')
    _write(path / 'process.json', record)
    try:
        args = json.loads((path / 'command.json').read_text())['args']
        child = subprocess.Popen(args, stdin=subprocess.DEVNULL)
        if stopped:
            child.terminate()
        code = child.wait()
        record.update(status='STOPPED' if stopped else ('SUCCEEDED' if code == 0 else 'FAILED'), exit_code=code)
    except Exception as error:
        record.update(status='FAILED', error=type(error).__name__)
        raise
    finally:
        _write(path / 'process.json', record)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--worker', required=True)
    parser.add_argument('--token', required=True)
    args = parser.parse_args()
    _worker(args.worker, args.token)
