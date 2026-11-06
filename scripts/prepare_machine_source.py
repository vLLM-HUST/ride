"""Export a complete immutable Git source, including acceptance fixtures.

Wheel construction remains the normal Python build workflow. This export is
for source verification and Linux tests; it never exports operator credentials,
untracked results, ignored files or another worktree's uncommitted edits.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import stat
import subprocess
import zipfile


def prepare(repository, revision, output):
    repository, output = Path(repository), Path(output)
    resolved = subprocess.check_output(['git', '-C', str(repository), 'rev-parse',
        '--verify', '--end-of-options', revision + '^{commit}'], text=True).strip()
    archive = subprocess.check_output(['git', '-C', str(repository), 'archive',
                                       '--format=zip', resolved])
    output.mkdir(parents=True, exist_ok=False)
    source = output / 'repository'; source.mkdir()
    files = {}
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        for entry in bundle.infolist():
            relative = PurePosixPath(entry.filename)
            if relative.is_absolute() or '..' in relative.parts or stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError('Source archive must contain regular relative files')
            path = source.joinpath(*relative.parts)
            if entry.is_dir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                content = bundle.read(entry)
                path.write_bytes(content)
                path.chmod((entry.external_attr >> 16) & 0o777 or 0o644)
                files[str(relative)] = hashlib.sha256(content).hexdigest()
    result = {'revision': resolved, 'files': files}
    (output / 'source-manifest.json').write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('repository', type=Path)
    parser.add_argument('revision')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    result = prepare(args.repository, args.revision, args.output)
    print(json.dumps({'revision': result['revision'], 'files': len(result['files'])}))


if __name__ == '__main__':
    main()
