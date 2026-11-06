"""Public SDK -> actual HTTP handler -> Runtime -> external model plugin.

Ray submission is a test double; no model, device or cloud service is started.
"""
from contextlib import ExitStack
import unittest
from unittest.mock import patch
from ride.sdk import RideClient, ApiError
import test_sdk_http_contract as http_fixture


SPEC = {'type':'external-engine','model':'fixture-model','endpoint':'http://model.invalid:8000'}

class Plugin:
    ready = True
    @staticmethod
    def command(spec): return 'python -m external_engine'
    @staticmethod
    def probe(spec): return {'model_ready':Plugin.ready,'identity':{'source':'external-plugin'}}


class ModelPluginSDK(unittest.TestCase):
    def setUp(self):
        self.http=http_fixture.Tests('test_sdk_handler_runtime_start_inspect_stop');self.http.setUp()
        self.addCleanup(self.http.tearDown);self.patches=ExitStack();self.addCleanup(self.patches.close)
        self.patches.enter_context(patch('ride.registry.model_service_adapter',return_value=Plugin))
        self.patches.enter_context(patch('ride.runtime.model_service_adapter',return_value=Plugin))
        self.patches.enter_context(patch.object(Plugin,'ready',True))
        self.sdk=RideClient('http://ride.invalid',transport=self.http.transport)

    def test_model_plugin_capability_is_explicit(self):
        self.sdk.require_capabilities('model_service_plugins')

    def test_conditional_plugin_lifecycle_and_exact_stop(self):
        first=self.sdk.models.start('native-a',SPEC,operation_id='native-start',expected_job_id=None)
        again=self.sdk.models.start('native-a',SPEC,operation_id='native-start',expected_job_id=None)
        self.assertEqual(first['job_id'],again['job_id']);self.assertEqual(len(self.http.ray.submitted),1)
        self.assertEqual(self.http.ray.submitted[0]['entrypoint'],'python -m external_engine')
        row=self.sdk.models.describe('native-a');self.assertTrue(row['ready']);self.assertEqual(row['identity']['source'],'external-plugin')
        with self.assertRaises(ApiError) as error:self.sdk.models.stop('native-a',expected_job_id='foreign')
        self.assertEqual(error.exception.status,409);self.assertEqual(self.http.ray.stopped,[])
        self.sdk.models.stop('native-a',expected_job_id=first['job_id']);self.assertEqual(self.http.ray.stopped,[first['job_id']])

    def test_plugin_readiness_is_not_inferred_from_running_job(self):
        self.sdk.models.start('native-a',SPEC,operation_id='native-start',expected_job_id=None)
        Plugin.ready=False
        row=self.sdk.models.describe('native-a');self.assertEqual(row['job_status'],'RUNNING');self.assertFalse(row['ready'])

    def test_unknown_plugin_submission_never_retries(self):
        self.http.ray.fail=True
        with self.assertRaises(ApiError):self.sdk.models.start('native-a',SPEC,operation_id='native-start',expected_job_id=None)
        with self.assertRaises(ApiError):self.sdk.models.start('native-a',SPEC,operation_id='native-start',expected_job_id=None)
        self.assertEqual(len(self.http.ray.submitted),1)
