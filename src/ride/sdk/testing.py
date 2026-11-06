"""Reusable CPU peer fixture: actual object/action transactions, fake execution only.

Not a server or an engine. Subclasses supply read/call/sample; never use as a
production peer. Lazy fixture slots model the caller's predeclared model pool.
"""
import tempfile
from pathlib import Path
from urllib.parse import unquote
from .journal import Journal
from .client import ApiError

class StatePeerFixture:
    def __init__(self,owner_id='software-fixture'):
        self._temporary=tempfile.TemporaryDirectory()
        self.journal=Journal(Path(self._temporary.name)/'state','peer-fixture')
        self.journal.mutate(lambda state:state.update(owner_id=owner_id,members={}))
        self.envelopes=[]
    def close(self):self.journal.close();self._temporary.cleanup()
    def read(self,path):raise KeyError(path)
    def call(self,path,body):raise KeyError(path)
    def sample(self,name,member):return {'drained':getattr(self,'drained',True)}
    def _view(self,state,name):
        member=state['members'][name];sample=dict(self.sample(name,member))
        sample['drained']=member['phase']=='draining' and sample.get('drained') is True
        return member['job_id'],dict(member),sample
    def get(self,path):
        if path=='/control/capabilities':return dict(versioned_state_actions=True,monotonic_drain=True,replica_job_binding=True)
        if path.startswith('/control/replicas/'):
            name=unquote(path.rsplit('/',1)[-1])
            if name not in self.journal.snapshot()['members']:
                self.journal.mutate(lambda state:state['members'].setdefault(name,dict(job_id=None,phase='inactive')))
            return self.journal.observe_object('Instance',name,lambda state:self._view(state,name))
        if path.startswith('/control/actions/'):
            try:return self.journal.read_action(unquote(path.rsplit('/',1)[-1]))
            except KeyError as error:raise ApiError(404,'Action receipt not found') from error
        return self.read(path)
    def post(self,path,body):
        if path!='/control/action':return self.call(path,body)
        self.envelopes.append(body)
        name=body['target']['name'];action=body['action']
        def transition(state,parameters):
            result=self.call('/control/'+action,parameters)
            state['members'][name].update(job_id=parameters['job_id'],phase={'activate':'active','drain':'draining','remove':'inactive'}[action])
            return result
        return self.journal.apply_action(body,lambda state:self._view(state,name),transition)
