"""Identity rejection prerequisites, not hardware acceptance."""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from deployment_identity import validate_binding

class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.policy = {'owner':'admin', 'workspace_id':'workspace-id', 'template':'ascend-raycluster', 'cluster':'ray-admin-shared'}
        self.user = {'username':'admin'}
        self.workspace = {'id':'workspace-id','name':'shared','owner_name':'admin','template_name':'ascend-raycluster','template_id':'template-id','latest_build':{'status':'running','template_version_id':'version-id'}}
        self.cluster = {'metadata':{'name':'ray-admin-shared','uid':'cluster-id','labels':{'coder.owner':'admin'}}}
        self.head = {'metadata':{'name':'head','uid':'head-id','labels':{'coder.workspace':'workspace-id','ray.io/cluster':'ray-admin-shared','ray.io/node-type':'head'},'ownerReferences':[{'kind':'RayCluster','uid':'cluster-id'}]},'status':{'podIP':'10.0.0.2','conditions':[{'type':'Ready','status':'True'}]}}
    def verify(self):
        return validate_binding(self.policy,self.user,self.workspace,self.cluster,[self.head],'http://10.0.0.2:8265','gateway')
    def test_standard_binding(self):
        self.assertTrue(self.verify()['verified'])
    def test_wrong_login(self):
        self.user['username']='user'
        with self.assertRaises(ValueError): self.verify()
    def test_wrong_owner(self):
        self.workspace['owner_name']='user'
        with self.assertRaises(ValueError): self.verify()
    def test_wrong_template(self):
        self.workspace['template_name']='custom-demo'
        with self.assertRaises(ValueError): self.verify()
    def test_unmanaged_cluster(self):
        self.cluster['metadata']['name']='direct-kubernetes-cluster'
        with self.assertRaises(ValueError): self.verify()
    def test_wrong_workspace(self):
        self.head['metadata']['labels']['coder.workspace']='other-workspace'
        with self.assertRaises(ValueError): self.verify()
    def test_wrong_head_owner(self):
        self.head['metadata']['ownerReferences'][0]['uid']='other-cluster'
        with self.assertRaises(ValueError): self.verify()
    def test_unready(self):
        self.head['status']['conditions'][0]['status']='False'
        with self.assertRaises(ValueError): self.verify()
    def test_wrong_endpoint(self):
        with self.assertRaises(ValueError):
            validate_binding(self.policy,self.user,self.workspace,self.cluster,[self.head],'http://10.0.0.3:8265','gateway')

if __name__ == '__main__': unittest.main()
