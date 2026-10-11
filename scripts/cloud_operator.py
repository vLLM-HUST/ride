"""Transport a cloud operation through existing SSH and Coder credentials.
No local service/port. Credential remains in stdin/process memory, not argv/files.
"""
import argparse
import base64
import json
import os
import shlex
import subprocess
from urllib.parse import urlparse


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('operation', choices=['deploy', 'accept'])
    p.add_argument('--ssh-host', required=True)
    p.add_argument('--cloud-root', required=True)
    p.add_argument('--coder-url', required=True)
    p.add_argument('--plan', default='plan-live.json')
    p.add_argument('--output', required=True)
    a = p.parse_args()
    if a.ssh_host.startswith('-') or not a.cloud_root.startswith('/'):
        p.error('Explicit SSH host and absolute cloud root required')
    token = os.environ.get('CODER_SESSION_TOKEN')
    if not token:
        r = subprocess.run(['security', 'find-generic-password', '-s', 'coder-v2-credentials',
                            '-a', 'coder-login-credentials', '-w'], capture_output=True, text=True)
        if r.returncode:
            raise SystemExit('Existing Coder session unavailable; no credential printed')
        credentials = json.loads(base64.b64decode(r.stdout.strip()))
        token = credentials[urlparse(a.coder_url).netloc]['api_token']
    script = ('import os\n'
              + 'os.environ["CODER_SESSION_TOKEN"]=' + repr(token) + '\n'
              + 'os.environ["PYTHONPATH"]=' + repr(a.cloud_root + '/bundle/src') + '\n'
              + 'os.execv("/bin/bash",' + repr(['bash', a.cloud_root + '/bundle/scripts/one-click.sh',
                  a.operation, a.cloud_root + '/' + a.plan, a.cloud_root + '/' + a.output]) + ')\n')
    result = subprocess.run(['ssh', '-o', 'ClearAllForwardings=yes', a.ssh_host, 'python3 -'],
                            input=script, text=True)
    raise SystemExit(result.returncode)

if __name__ == '__main__':
    main()
