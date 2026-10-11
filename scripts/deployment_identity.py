"""Fail-closed live Coder/Kubernetes binding verification before Ray submission.
Credentials are read from environment and are never included in the evidence.
"""
import json
import os
import subprocess
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def validate_binding(policy, user, workspace, cluster, pods, address, hostname):
    if user.get('username') != policy['owner']:
        raise ValueError('Coder login identity differs from approved owner')
    if workspace.get('owner_name') != policy['owner']:
        raise ValueError('Workspace owner differs from approved owner')
    if workspace.get('id') != policy['workspace_id']:
        raise ValueError('Unexpected workspace ID')
    if workspace.get('template_name') != policy['template']:
        raise ValueError('Unexpected workspace template')
    if workspace.get('latest_build', {}).get('status') != 'running':
        raise ValueError('Coder workspace build is not running')
    if cluster.get('metadata', {}).get('name') != policy['cluster']:
        raise ValueError('Unexpected RayCluster')
    labels = cluster.get('metadata', {}).get('labels', {})
    expected_cluster = 'ray-' + workspace['owner_name'].lower() + '-' + workspace['name'].lower()
    if labels.get('coder.owner') != policy['owner'] or cluster['metadata']['name'] != expected_cluster:
        raise ValueError('RayCluster does not match standard workspace naming and owner')
    heads = [p for p in pods if p.get('metadata', {}).get('labels', {}).get('ray.io/node-type') == 'head'
             and p['metadata']['labels'].get('ray.io/cluster') == policy['cluster']]
    if len(heads) != 1:
        raise ValueError('Exactly one associated Ray head required')
    head = heads[0]
    if head['metadata']['labels'].get('coder.workspace') != workspace['id']:
        raise ValueError('Ray head is not bound to approved workspace ID')
    owners = head['metadata'].get('ownerReferences', [])
    if not any(o.get('uid') == cluster['metadata']['uid'] and o.get('kind') == 'RayCluster' for o in owners):
        raise ValueError('Head ownership does not match RayCluster UID')
    if not any(c.get('type') == 'Ready' and c.get('status') == 'True' for c in head.get('status', {}).get('conditions', [])):
        raise ValueError('Ray head is not Ready')
    url = urlparse(address)
    if url.scheme not in ('http', 'https') or url.port != 8265:
        raise ValueError('Expected associated Ray Jobs endpoint on port 8265')
    direct = url.hostname == head['status'].get('podIP')
    internal = url.hostname in ('127.0.0.1', 'localhost') and hostname == head['metadata']['name']
    if not (direct or internal):
        raise ValueError('Ray endpoint cannot be bound to the verified head')
    return {'owner': policy['owner'], 'workspace_id': workspace['id'],
            'template_id': workspace['template_id'], 'template_version_id': workspace['latest_build']['template_version_id'],
            'cluster_uid': cluster['metadata']['uid'], 'head_uid': head['metadata']['uid'], 'verified': True}


def verify_live(plan):
    policy = plan['deployment_identity']
    token = os.environ.get('CODER_SESSION_TOKEN')
    if not token:
        raise ValueError('Live Coder session required; no self-attested identity fallback')
    def get(path):
        req = Request(policy['coder_url'].rstrip('/') + '/api/v2/' + path,
                      headers={'Coder-Session-Token': token})
        with urlopen(req, timeout=15) as response:
            return json.load(response)
    def kube(kind, name):
        return json.loads(subprocess.check_output(['kubectl', '-n', policy['namespace'], 'get', kind, name, '-o', 'json']))
    user = get('users/me')
    workspace = get('workspaces/' + policy['workspace_id'])
    cluster = kube('raycluster', policy['cluster'])
    pods = json.loads(subprocess.check_output(['kubectl', '-n', policy['namespace'], 'get', 'pods',
        '-l', 'ray.io/cluster=' + policy['cluster'], '-o', 'json']))['items']
    return validate_binding(policy, user, workspace, cluster, pods, plan['ray_address'], os.environ.get('HOSTNAME', ''))
