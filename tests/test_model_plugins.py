import tempfile
from pathlib import Path
from unittest.mock import patch
from ride import registry
from ride.runtime import Runtime
from test_runtime import Client


def test_model_plugin_command_and_readiness_use_plugin_contract():
    class Adapter:
        @staticmethod
        def command(spec):return 'python -m native_engine'
        @staticmethod
        def probe(spec):return {'model_ready':spec['model']=='expected','identity':{'source':'native'}}
    with tempfile.TemporaryDirectory() as directory,patch.object(registry,'model_service_adapter',return_value=Adapter):
        assert registry.command('model_services',{'type':'native','model':'expected'})=='python -m native_engine'
        config={'workspace':'test','state_file':str(Path(directory)/'state.json'),'model_services':[
            {'id':'engine','type':'native','model':'expected','endpoint':'http://127.0.0.1:8000'}]}
        with patch('ride.runtime.model_service_adapter',return_value=Adapter):
            runtime=Runtime(config,Client());runtime.start_model_service('engine')
            actual=runtime.describe('model_services','engine')
            assert actual['ready'] and actual['identity']['source']=='native'


def test_failed_model_plugin_probe_cannot_be_reported_ready():
    class Adapter:
        @staticmethod
        def command(spec):return 'python -m native_engine'
        @staticmethod
        def probe(spec):return {'model_ready':False}
    with tempfile.TemporaryDirectory() as directory,patch.object(registry,'model_service_adapter',return_value=Adapter),patch('ride.runtime.model_service_adapter',return_value=Adapter):
        runtime=Runtime({'workspace':'test','state_file':str(Path(directory)/'state.json'),'model_services':[
            {'id':'engine','type':'native','model':'x','endpoint':'http://127.0.0.1:8000'}]},Client())
        runtime.start_model_service('engine');assert not runtime.describe('model_services','engine')['ready']
