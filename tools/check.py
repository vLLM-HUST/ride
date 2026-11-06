"""Standard software checks; no cloud deployment or model requests."""
import argparse,json,subprocess,sys
from pathlib import Path

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True);args=parser.parse_args()
    out=args.output_dir.resolve();out.mkdir(parents=True,exist_ok=True)
    if any(out.iterdir()):parser.error('Choose an empty evidence directory')
    root=Path(__file__).resolve().parents[1]
    checks=[('tests',[sys.executable,'-m','pytest','-q']),
            ('cli',[sys.executable,'-m','ride','--help']),
            ('installed-cli',[str(Path(sys.executable).parent/'ride'),'--help']),
            ('build',[sys.executable,'-m','build','--no-isolation'])]
    receipt={'status':'RUNNING','evidence_type':'software','hardware':'NOT_RUN','performance':'NOT_RUN','checks':[],'new_model_requests':0}
    for name,command in checks:
        with (out/(name+'.log')).open('w') as stream:
            try:code=subprocess.run(command,cwd=root,stdout=stream,stderr=subprocess.STDOUT).returncode
            except OSError as error:stream.write(str(error)+'\n');code=127
        receipt['checks'].append(dict(name=name,command=command,exit_code=code))
        receipt['status']='FAIL' if code else 'RUNNING';(out/'result.json').write_text(json.dumps(receipt,indent=2)+'\n')
        print(name,code,flush=True)
        if code:return code
    receipt['status']='PASS';(out/'result.json').write_text(json.dumps(receipt,indent=2)+'\n');return 0
if __name__=='__main__':raise SystemExit(main())
