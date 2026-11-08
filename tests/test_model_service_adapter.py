"""Model backend plugins keep lifecycle effects in the existing RIDE runtime."""
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from ride import registry
from ride.runtime import Runtime
from test_runtime import Client


class Adapter:
    @staticmethod
    def command(spec):
        if not spec.get('configuration_sha256'):
            raise ValueError('Frozen backend configuration required')
        return 'python -m example_model_backend'

    @staticmethod
    def probe(spec):
        return {'model_ready': False, 'identity': {'id': spec['id']}}


def entrypoints(**query):
    if query.get('group')=='ride.model_services'and query.get('name')in ('example-model-worker','example-model-frontend'):
        return [SimpleNamespace(load=lambda:Adapter)]
    return []


def model(identifier):
    return dict(id=identifier,type='example-model-frontend'if identifier=='frontend'else'example-model-worker',model='example-model',
                endpoint='http://'+identifier+'.invalid:8000',configuration_sha256='a'*64)


def test_model_plugin_command_and_duplicate_registration():
    with patch.object(registry,'entry_points',side_effect=entrypoints):
        assert registry.command('model_services',model('worker'))=='python -m example_model_backend'
    with patch.object(registry,'entry_points',return_value=[object(),object()]):
        with pytest.raises(ValueError,match='Duplicate'):registry.model_service_adapter('ambiguous')


def test_worker_stop_and_management_adoption_preserve_frontend():
    with tempfile.TemporaryDirectory()as directory,patch.object(registry,'entry_points',side_effect=entrypoints):
        client=Client();config=dict(state_file=str(Path(directory)/'state'),workspace='test',
                                  model_services=[model('frontend'),model('worker')])
        runtime=Runtime(config,client)
        frontend=runtime.start_model_service('frontend');worker=runtime.start_model_service('worker')
        runtime.close();restored=Runtime(config,client)
        try:
            assert restored.start_model_service('frontend')['job_id']==frontend['job_id']
            restored.stop_instance('model_services','worker',expected_job_id=worker['job_id'])
            assert client.stopped==[worker['job_id']]
            assert len(client.submitted)==2
        finally:restored.close()


def test_model_plugin_readiness_never_falls_back_to_http_health():
    with tempfile.TemporaryDirectory()as directory,patch.object(registry,'entry_points',side_effect=entrypoints):
        runtime=Runtime(dict(state_file=str(Path(directory)/'state'),model_services=[model('worker')]),Client())
        try:
            runtime.start_model_service('worker')
            with patch.object(Runtime,'health',side_effect=AssertionError('Wrong fallback')):
                observed=runtime.describe('model_services','worker')
            assert observed['ready']is False
            assert observed['identity']['id']=='worker'
            with patch.object(Adapter,'probe',side_effect=ValueError('Wrong engine identity')):
                observed=runtime.describe('model_services','worker')
            assert observed['ready']is False
            assert observed['probe_error']=='ValueError'
        finally:runtime.close()


def test_invalid_backend_configuration_refuses_before_job_submission():
    with tempfile.TemporaryDirectory()as directory,patch.object(registry,'entry_points',side_effect=entrypoints):
        spec=model('worker');spec.pop('configuration_sha256');client=Client()
        runtime=Runtime(dict(state_file=str(Path(directory)/'state'),model_services=[spec]),client)
        try:
            with pytest.raises(ValueError,match='Frozen'):runtime.start_model_service('worker')
            assert client.submitted==[]
        finally:runtime.close()


@pytest.mark.parametrize('missing',['model','endpoint'])
def test_missing_standard_model_binding_refuses_before_plugin_execution(missing):
    spec=model('worker');spec.pop(missing)
    with patch.object(registry,'entry_points',side_effect=AssertionError('Must validate first')):
        with pytest.raises(ValueError,match='Model service requires'):registry.command('model_services',spec)


@pytest.mark.parametrize('command',[None,'',[],42])
def test_invalid_plugin_command_refuses(command):
    with patch.object(registry,'entry_points',side_effect=entrypoints),patch.object(Adapter,'command',return_value=command):
        with pytest.raises(ValueError,match='foreground command'):registry.command('model_services',model('worker'))


def test_cli_model_type_discovery_keeps_explicit_instance_name():
    from ride import __main__ as cli
    with patch.object(registry,'entry_points',side_effect=entrypoints),patch.object(cli,'request',return_value={})as request:
        cli.main(['start','model-service','example-model-worker','--name','worker-1',
                  '--model','example-model','--endpoint','http://worker.invalid:8000'])
    assert request.call_args.args[1]=='model-services/worker-1/start'
    assert request.call_args.args[2]['type']=='example-model-worker'


def test_unknown_submission_for_backend_plugin_is_not_retried():
    class LostReply(Client):
        def submit_job(self,**kwargs):
            super().submit_job(**kwargs)
            raise OSError('Lost reply')
    with tempfile.TemporaryDirectory()as directory,patch.object(registry,'entry_points',side_effect=entrypoints):
        client=LostReply();config=dict(state_file=str(Path(directory)/'state'),workspace='test',model_services=[model('worker')])
        runtime=Runtime(config,client)
        with pytest.raises(OSError):runtime.start_instance('model_services','worker',operation_id='start-worker',expected_job_id=None)
        runtime.close();restored=Runtime(config,client)
        try:
            with pytest.raises(ValueError,match='unknown'):restored.start_instance('model_services','worker',operation_id='start-worker',expected_job_id=None)
            assert len(client.submitted)==1
        finally:restored.close()


def test_missing_installed_backend_never_becomes_ready_via_http_fallback():
    with tempfile.TemporaryDirectory()as directory:
        client=Client();runtime=Runtime(dict(state_file=str(Path(directory)/'state'),model_services=[model('worker')]),client)
        try:
            with patch.object(registry,'entry_points',side_effect=entrypoints):runtime.start_model_service('worker')
            with patch.object(registry,'entry_points',return_value=[]),patch.object(Runtime,'health',return_value=True):
                observed=runtime.describe('model_services','worker')
            assert observed['ready']is False
            assert observed['probe_error']=='ModelServiceAdapterUnavailable'
        finally:runtime.close()
