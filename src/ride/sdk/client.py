"""Lightweight management/peer clients. Explicit endpoints, no startup or retries."""
import json
from urllib.error import HTTPError
from urllib.parse import urlsplit, quote
from urllib.request import Request, urlopen

PROTOCOL_VERSION = '1'

class ApiError(RuntimeError):
    def __init__(self, status, message):
        self.status=status
        super().__init__(message)

class PeerClient:
    def __init__(self, endpoint, *, token=None, timeout=None, transport=None):
        parsed=urlsplit(endpoint)
        if (parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username
                or parsed.password or parsed.path not in ('','/') or parsed.query or parsed.fragment):
            raise ValueError('Explicit HTTP origin required')
        parsed.port
        self.endpoint=endpoint.rstrip('/');self.token=token;self.timeout=timeout;self.transport=transport
    def call(self, method, path, body=None):
        if not isinstance(path,str) or not path.startswith('/') or path.startswith('//'):
            raise ValueError('Absolute API path required')
        if self.transport is not None:return self.transport(method,path,body)
        headers={'Content-Type':'application/json'}
        if self.token:headers['Authorization']='Bearer '+self.token
        request=Request(self.endpoint+path,method=method,headers=headers,
            data=None if body is None else json.dumps(body,allow_nan=False).encode())
        try:
            with urlopen(request,timeout=self.timeout) as response:return json.load(response)
        except HTTPError as error:
            try:message=json.load(error).get('error','Management API error')
            except (ValueError,AttributeError):message='Management API error'
            raise ApiError(error.code,message) from error
    def get(self,path):return self.call('GET',path)
    def post(self,path,body):return self.call('POST',path,body)

class ResourceClient:
    def __init__(self,client,kind):self.client,self.kind=client,kind
    def path(self,name):
        if not isinstance(name,str) or not name:raise ValueError('Instance identity required')
        return '/api/v1/'+self.kind+'/'+quote(name,safe='')
    def describe(self,name):return self.client.get(self.path(name))
    def logs(self,name):return self.client.get(self.path(name)+'/logs')
    def start(self,name,spec,*,operation_id,expected_job_id):
        if not isinstance(operation_id,str) or not 0<len(operation_id)<=256:raise ValueError('Operation identity required')
        if expected_job_id is not None and (not isinstance(expected_job_id,str) or not expected_job_id):raise ValueError('Prior Job identity required')
        required=['conditional_start']
        if isinstance(spec,dict) and 'start_not_after' in spec:required.append('start_deadline')
        self.client.require_capabilities(*required)
        return self.client.post(self.path(name)+'/start',dict(spec=spec,operation_id=operation_id,expected_job_id=expected_job_id))
    def stop(self,name,*,expected_job_id):
        if not isinstance(expected_job_id,str) or not expected_job_id:raise ValueError('Exact Job identity required')
        self.client.require_capabilities('conditional_stop')
        return self.client.post(self.path(name)+'/stop',{'expected_job_id':expected_job_id})

class RideClient(PeerClient):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.models=ResourceClient(self,'model-services');self.controllers=ResourceClient(self,'controllers')
    def status(self):return self.get('/api/v1/status')
    def require_capabilities(self,*names):
        capabilities=self.get('/api/v1/capabilities')
        if capabilities.get('protocol_version')!=PROTOCOL_VERSION:raise ValueError('Incompatible RIDE protocol version')
        if any(capabilities.get(name) is not True for name in names):raise ValueError('RIDE capability missing: '+', '.join(names))
    def operation(self,operation_id):return self.get('/api/v1/operations/'+quote(operation_id,safe=''))
