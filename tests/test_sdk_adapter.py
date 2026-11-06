import hashlib,json,tempfile,unittest
from pathlib import Path
from ride.sdk import PythonControllerAdapter,load_configuration

class Example(PythonControllerAdapter):module='example_controller';role='example'
class Tests(unittest.TestCase):
    def test_frozen_binding_and_command(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);config={'schema':'ride.controller/v1','id':'example','role':'example','endpoint':'http://example.invalid:9000','state_file':str(root/'state')};p=root/'config.json';p.write_text(json.dumps(config));digest=hashlib.sha256(p.read_bytes()).hexdigest();spec={'id':'example','endpoint':config['endpoint'],'configuration':str(p),'configuration_sha256':digest}
            self.assertIn('python -m example_controller',Example.command(spec))
            with self.assertRaisesRegex(ValueError,'binding'):Example.command(dict(spec,id='other'))
            with self.assertRaisesRegex(ValueError,'SHA256'):load_configuration(str(p),'0'*64)
    def test_bad_schema_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'config';p.write_text('{}')
            with self.assertRaisesRegex(ValueError,'schema'):load_configuration(str(p),hashlib.sha256(p.read_bytes()).hexdigest())
