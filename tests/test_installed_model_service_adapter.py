"""An independent installed wheel registers a model backend without Ray imports."""
import os
from pathlib import Path
import subprocess
import sys
import venv


def test_independent_backend_wheel_is_discovered_by_installed_ride(tmp_path):
    project=tmp_path/'backend';project.mkdir()
    (project/'pyproject.toml').write_text('''[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"
[project]
name = "ride-model-adapter-test-fixture"
version = "0.0.1"
[project.entry-points."ride.model_services"]
example-model-worker = "example_model_backend:Adapter"
[tool.setuptools]
py-modules = ["example_model_backend"]
''')
    (project/'example_model_backend.py').write_text('''from ride.sdk import ModelServiceAdapter

class Adapter:
    @staticmethod
    def command(spec):
        return 'python -m example_model_backend'
    @staticmethod
    def probe(spec):
        return {'model_ready':True,'identity':{'id':spec['id']}}
''')
    root=Path(__file__).resolve().parents[1];wheels=tmp_path/'wheels'
    for source in (root,project):
        result=subprocess.run([sys.executable,'-m','build','--wheel','--no-isolation',
                               '--outdir',str(wheels),str(source)],capture_output=True,text=True)
        assert result.returncode==0,result.stdout+result.stderr
    environment=tmp_path/'installed';venv.EnvBuilder(with_pip=True).create(environment)
    python=environment/('Scripts/python.exe'if os.name=='nt'else'bin/python')
    result=subprocess.run([str(python),'-m','pip','install','--no-index','--no-deps',
                           *map(str,wheels.glob('*.whl'))],capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
    script='''import sys,tempfile
from pathlib import Path
from ride.registry import command,model_service_adapter
from ride.runtime import Runtime
assert 'ray'not in sys.modules
assert model_service_adapter('example-model-worker').__module__=='example_model_backend'
assert command('model_services',dict(type='example-model-worker',id='worker',model='model',endpoint='http://worker.invalid'))=='python -m example_model_backend'
class Client:
    def submit_job(self,**kwargs):self.submitted=kwargs
    def get_job_status(self,identifier):
        class Status:value='RUNNING'
        return Status()
with tempfile.TemporaryDirectory()as directory:
    client=Client();runtime=Runtime(dict(state_file=str(Path(directory)/'state'),workspace='test',model_services=[dict(type='example-model-worker',id='worker',model='model',endpoint='http://worker.invalid')]),client)
    runtime.start_model_service('worker')
    assert runtime.describe('model_services','worker')['ready']is True
    runtime.close()
assert 'ray'not in sys.modules
print('INSTALLED_MODEL_BACKEND_PASS')
'''
    clean={key:value for key,value in os.environ.items()if key not in ('PYTHONPATH','PYTHONHOME')}
    result=subprocess.run([str(python),'-I','-c',script],cwd=tmp_path,env=clean,capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
    assert 'INSTALLED_MODEL_BACKEND_PASS'in result.stdout
