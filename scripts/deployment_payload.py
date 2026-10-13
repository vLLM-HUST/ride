"""Prepare explicit payload files in an identified existing workspace Pod."""
import base64
import hashlib
import json
import subprocess
from pathlib import Path

REMOTE = r'''
import base64,hashlib,json,pathlib,sys
p=json.load(sys.stdin);root=pathlib.Path(p['destination'])
if not str(root).startswith('/workspace/home/') or '..' in root.parts:
 raise ValueError('Destination outside workspace home')
checked=[]
for item in p['files']:
 rel=pathlib.Path(item['path'])
 if rel.is_absolute() or '..' in rel.parts:raise ValueError('Unsafe relative path')
 target=root/rel
 for ancestor in [target,*target.parents]:
  if ancestor.is_symlink():raise ValueError('Symlink destination refused')
 data=base64.b64decode(item['data']);digest=hashlib.sha256(data).hexdigest()
 if digest!=item['sha256']:raise ValueError('Payload checksum mismatch')
 if target.exists() and (not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest()!=digest):
  raise ValueError('Existing destination differs; refusing overwrite')
 checked.append((target,data,digest))
for target,data,digest in checked:
 target.parent.mkdir(parents=True,exist_ok=True)
 if not target.exists():
  with target.open('xb') as f:f.write(data)
 if hashlib.sha256(target.read_bytes()).hexdigest()!=digest:raise ValueError('Readback differs')
print(json.dumps({'files':[{'path':str(t),'sha256':h} for t,d,h in checked]}))
'''

def prepare_payload(spec):
    base = ['kubectl', '-n', spec['namespace']]
    for kind, name, expected in [('raycluster', spec['cluster'], spec['cluster_uid']),
                                ('pod', spec['pod'], spec['pod_uid'])]:
        uid = subprocess.check_output(base + ['get', kind, name, '-o',
                        'jsonpath={.metadata.uid}'], text=True).strip()
        if uid != expected:
            raise ValueError('Payload target identity changed')
    files = []
    total = 0
    for item in spec['files']:
        data = Path(item['source']).read_bytes()
        total += len(data)
        if total > 256 * 1024 * 1024:
            raise ValueError('Payload exceeds 256 MiB; use shared storage for model weights')
        digest = hashlib.sha256(data).hexdigest()
        if digest != item['sha256']:
            raise ValueError('Source checksum differs from frozen plan')
        files.append({'path': item['path'], 'sha256': digest,
                      'data': base64.b64encode(data).decode()})
    response = subprocess.check_output(base + ['exec', '-i', spec['pod'], '--',
                   'python3', '-c', REMOTE], input=json.dumps(
                       {'destination': spec['destination'], 'files': files}).encode(), timeout=120)
    return json.loads(response)
