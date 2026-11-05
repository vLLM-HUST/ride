"""Prepare explicit payload files in an identified existing workspace Pod."""
import base64
import hashlib
import json
import subprocess
import io
import os
import re
import tarfile
import tempfile
from pathlib import Path


def _ordinary_path(path):
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('Absolute ordinary staging path required')
    if any(p.is_symlink() for p in [path, *path.parents]):
        raise ValueError('Symlink staging path refused')


def _publish(path, data, mode):
    """Publish a complete file exclusively; never expose a partial final file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix='.ride-', dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        temporary.chmod(mode)
        try:
            os.link(temporary, path)
        except FileExistsError:
            _ordinary_path(path)
            if not path.is_file() or path.read_bytes() != data or path.stat().st_mode & 0o7777 != mode:
                raise ValueError('Existing staged file differs; refusing overwrite')
    finally:
        if temporary is not None: temporary.unlink(missing_ok=True)


def initialize_staging(destination, identity):
    """Bind a private file-staging directory to an explicit frozen deployment.

    This identity is local custody metadata, not platform ownership validation.
    Callers must separately verify the actual workspace and Pod identities.
    """
    root = Path(destination); _ordinary_path(root)
    if (not isinstance(identity, dict) or set(identity) != {'run_id', 'workspace_id', 'plan_sha256'}
            or not isinstance(identity['run_id'], str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,127}', identity['run_id'])
            or not isinstance(identity['workspace_id'], str) or not 0 < len(identity['workspace_id']) <= 256
            or not isinstance(identity['plan_sha256'], str) or not re.fullmatch(r'[a-f0-9]{64}', identity['plan_sha256'])):
        raise ValueError('Explicit staging run/workspace/frozen-plan identity required')
    raw = json.dumps(identity, sort_keys=True, separators=(',', ':')).encode()
    marker = root / '.ride-staging.json'
    if root.exists():
        if not root.is_dir() or root.stat().st_mode & 0o7777 != 0o700:
            raise ValueError('Private staging directory required')
        _ordinary_path(marker)
        if not marker.is_file() or marker.read_bytes() != raw:
            raise ValueError('Unknown or conflicting staging directory; preserve original')
    else:
        root.mkdir(mode=0o700, parents=False)
        _publish(marker, raw, 0o600)
    return {'identity': dict(identity), 'destination': str(root)}


def stage_archive(archive, destination, identity, expected_sha256):
    """Resume immutable source files only; does not submit or start any process."""
    root = Path(destination)
    initialize_staging(root, identity)
    if not isinstance(expected_sha256, str) or not re.fullmatch(r'[a-f0-9]{64}', expected_sha256):
        raise ValueError('Explicit archive SHA256 required')
    archive = Path(archive); _ordinary_path(archive)
    if not archive.is_file() or archive.stat().st_size > 256 * 1024 * 1024:
        raise ValueError('Bounded ordinary payload archive required')
    raw = archive.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError('Archive SHA256 differs')
    pin = root / '.ride-archive.json'
    _ordinary_path(pin)
    pin_data = json.dumps({'archive_sha256': expected_sha256}, sort_keys=True).encode()
    if pin.exists() and (not pin.is_file() or pin.read_bytes() != pin_data):
        raise ValueError('Staging archive identity changed')
    checked = []; names = set(); total = 0
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:*') as source:
        for member in source:
            relative = Path(member.name)
            if (not member.isfile() or relative.is_absolute() or '..' in relative.parts
                    or not relative.parts or relative.parts[0].startswith('.ride-')
                    or str(relative) in names):
                raise ValueError('Unsafe or duplicate archive member')
            names.add(str(relative)); total += member.size
            if len(names) > 10000 or total > 256 * 1024 * 1024:
                raise ValueError('Payload archive exceeds staging bounds')
            if member.mode not in (0o600, 0o644, 0o755):
                raise ValueError('Unsupported staged file mode')
            target = root / relative; _ordinary_path(target)
            data = source.extractfile(member).read()
            digest = hashlib.sha256(data).hexdigest()
            if target.exists() and (not target.is_file() or target.read_bytes() != data or target.stat().st_mode & 0o7777 != member.mode):
                raise ValueError('Existing staged file differs; refusing overwrite')
            checked.append((target, data, digest, member.mode))
    # Validate the whole archive before writing any of its files. These two
    # stages already support exact immutable replay after transport loss.
    _publish(pin, pin_data, 0o600)
    for target, data, digest, mode in checked:
        if not target.exists(): _publish(target, data, mode)
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError('Staged source readback differs')
    return {'archive_sha256': expected_sha256,
            'files': [{'path': str(target.relative_to(root)), 'sha256': digest, 'mode': mode} for target, data, digest, mode in checked]}

REMOTE = r'''
import base64,hashlib,json,os,pathlib,sys,tempfile
p=json.load(sys.stdin);root=pathlib.Path(p['destination'])
if not str(root).startswith('/workspace/home/') or '..' in root.parts:
 raise ValueError('Destination outside workspace home')
checked=[]
for item in p['files']:
 mode=item.get('mode')
 if mode is not None and (type(mode) is not int or mode not in (0o644,0o755)):
  raise ValueError('Only explicit regular or executable file modes are supported')
 rel=pathlib.Path(item['path'])
 if rel.is_absolute() or '..' in rel.parts:raise ValueError('Unsafe relative path')
 target=root/rel
 for ancestor in [target,*target.parents]:
  if ancestor.is_symlink():raise ValueError('Symlink destination refused')
 data=base64.b64decode(item['data']);digest=hashlib.sha256(data).hexdigest()
 if digest!=item['sha256']:raise ValueError('Payload checksum mismatch')
 if target.exists() and (not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest()!=digest):
  raise ValueError('Existing destination differs; refusing overwrite')
 checked.append((target,data,digest,mode))
for target,data,digest,mode in checked:
 target.parent.mkdir(parents=True,exist_ok=True)
 if not target.exists():
  temporary=None
  try:
   with tempfile.NamedTemporaryFile(prefix='.ride-payload-',dir=target.parent,delete=False) as f:
    temporary=pathlib.Path(f.name);f.write(data);f.flush();os.fsync(f.fileno())
   mask=os.umask(0);os.umask(mask)
   temporary.chmod(mode if mode is not None else 0o666 & ~mask)
   try:os.link(temporary,target)
   except FileExistsError:
    if target.is_symlink() or not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest()!=digest:
     raise ValueError('Existing destination differs; refusing overwrite')
  finally:
   if temporary is not None:temporary.unlink(missing_ok=True)
 if hashlib.sha256(target.read_bytes()).hexdigest()!=digest:raise ValueError('Readback differs')
 if mode is not None:target.chmod(mode)
 if mode is not None and target.stat().st_mode & 0o7777 != mode:raise ValueError('File mode readback differs')
print(json.dumps({'files':[{'path':str(t),'sha256':h,'mode':t.stat().st_mode & 0o7777} for t,d,h,m in checked]}))
'''

def prepare_payload(spec):
    base = ['kubectl', '-n', spec['namespace']]
    for kind, name, expected in [('raycluster', spec['cluster'], spec['cluster_uid']),
                                ('pod', spec['pod'], spec['pod_uid'])]:
        record = json.loads(subprocess.check_output(base + ['get', kind, name, '-o',
                             'json'], text=True))
        if record['metadata']['uid'] != expected:
            raise ValueError('Payload target identity changed')
        if kind == 'pod' and record['metadata'].get('labels', {}).get('ray.io/cluster') != spec['cluster']:
            raise ValueError('Payload Pod is not a member of the selected RayCluster')
    files = []
    total = 0
    for item in spec['files']:
        mode = item.get('mode')
        if mode is not None and (type(mode) is not int or mode not in (0o644, 0o755)):
            raise ValueError('Only explicit regular or executable file modes are supported')
        data = Path(item['source']).read_bytes()
        total += len(data)
        if total > 256 * 1024 * 1024:
            raise ValueError('Payload exceeds 256 MiB; use shared storage for model weights')
        digest = hashlib.sha256(data).hexdigest()
        if digest != item['sha256']:
            raise ValueError('Source checksum differs from frozen plan')
        files.append({'path': item['path'], 'sha256': digest,
                      'data': base64.b64encode(data).decode(), 'mode': mode})
    response = subprocess.check_output(base + ['exec', '-i', spec['pod'], '--',
                   'python3', '-c', REMOTE], input=json.dumps(
                       {'destination': spec['destination'], 'files': files}).encode(), timeout=120)
    return json.loads(response)
