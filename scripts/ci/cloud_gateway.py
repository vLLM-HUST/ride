"""Installed cloud-side fixed command. Accept source files, execute only inside CPU Pod."""
import hashlib,io,json,os,re,shutil,subprocess,sys,tarfile,uuid
from pathlib import Path
os.umask(0o077)
if os.environ.get('SSH_ORIGINAL_COMMAND') != 'ride-cpu-acceptance':raise SystemExit('Only ride-cpu-acceptance is permitted')
profile=json.loads(Path('/etc/ride-ci/config.json').read_text())
root=Path('/var/lib/ride-ci/runs')/uuid.uuid4().hex;root.mkdir(parents=True)
try:
 data=sys.stdin.buffer.read(64*1024*1024+1)
 if len(data)>64*1024*1024:raise ValueError('Bundle exceeds 64 MiB')
 with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as archive:
  members=archive.getmembers()
  if sum(x.size for x in members)>128*1024*1024:raise ValueError('Expanded bundle exceeds 128 MiB')
  for member in members:
   path=Path(member.name)
   if path.is_absolute() or '..' in path.parts or not(member.isfile() or member.isdir()):raise ValueError('Unsafe source bundle')
   target=root/path
   if member.isdir():target.mkdir(parents=True,exist_ok=True)
   else:
    target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(archive.extractfile(member).read())
 metadata=json.loads((root/'metadata.json').read_text());revision=metadata['revision']
 if not re.fullmatch('[a-f0-9]{40}',revision):raise ValueError('Expected exact commit')
 if metadata.get('controller_revision')!='cb4c4e5c46875ea7f2a0a8618c54c9bb39989926':raise ValueError('Unknown Controller revision')
 provenance=json.loads(Path('/opt/ride-ci/controller-provenance.json').read_text())
 for relative,digest in provenance['hashes'].items():
  if hashlib.sha256((Path('/opt/ride-ci/controller-source')/relative).read_bytes()).hexdigest()!=digest:raise ValueError('Controller cache hash mismatch')
 shutil.copytree('/opt/ride-ci/controller-source',root/'controller')
 evidence=root/'evidence';evidence.mkdir()
 (evidence/'controller-provenance.json').write_text(json.dumps(provenance,indent=2))
 result=subprocess.run(['/usr/bin/python3','/opt/ride-ci/run_cloud_cpu_acceptance.py','--local','--revision',revision,'--image',profile['cpu_image'],'--controller-source',str(root/'controller'),'--upstream-source',str(root/'upstream'),'--output',str(evidence)],cwd=root/'repo',stdout=sys.stderr,stderr=sys.stderr)
 with tarfile.open(fileobj=sys.stdout.buffer,mode='w|gz') as archive:archive.add(evidence,arcname='evidence')
 sys.stdout.buffer.flush()
 sys.exit(result.returncode)
finally:
 # This unique run directory is created above; no shared directory deletion.
 shutil.rmtree(root)
