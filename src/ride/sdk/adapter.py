"""Shared frozen configuration and process adapter; no policy implementation."""
import hashlib
import json
import re
import shlex
from pathlib import Path
from .client import PeerClient,PROTOCOL_VERSION


def load_configuration(path, expected_sha256, *, role=None):
    path=Path(path)
    if not path.is_absolute() or path.is_symlink():raise ValueError('Absolute regular configuration required')
    raw=path.read_bytes();digest=hashlib.sha256(raw).hexdigest()
    if digest!=expected_sha256:raise ValueError('Configuration SHA256 differs')
    config=json.loads(raw)
    if (config.get('schema')!='ride.controller/v1' or not isinstance(config.get('id'),str)
            or not re.fullmatch(r'[A-Za-z0-9_.-]{1,127}',config['id']) or role and config.get('role')!=role):
        raise ValueError('Controller schema, identity and role required')
    PeerClient(config['endpoint'])
    state=Path(config.get('state_file',''))
    if not state.is_absolute() or state.is_symlink():raise ValueError('Absolute dedicated state_file required')
    config['_sha256']=digest
    return config

class PythonControllerAdapter:
    module=None
    role=None
    @classmethod
    def configuration(cls,spec):
        config=load_configuration(spec['configuration'],spec['configuration_sha256'],role=cls.role)
        if config['id']!=spec['id'] or config['endpoint']!=spec['endpoint']:raise ValueError('Controller binding differs')
        return config
    @classmethod
    def command(cls,spec):
        cls.configuration(spec)
        if not cls.module:raise ValueError('Controller process module required')
        return shlex.join(['python','-m',cls.module,'--configuration',spec['configuration'],'--configuration-sha256',spec['configuration_sha256']])
    @classmethod
    def probe(cls,spec):
        config=cls.configuration(spec);client=PeerClient(config['endpoint'],timeout=2)
        values={key:client.get('/'+key) for key in ['health','identity','status']}
        identity=values['identity']
        values['controller_ready']=(values['health'].get('status')=='ok' and identity.get('id')==config['id']
            and identity.get('role')==cls.role and identity.get('configuration_sha256')==config['_sha256']
            and identity.get('protocol_version')==PROTOCOL_VERSION)
        return values
