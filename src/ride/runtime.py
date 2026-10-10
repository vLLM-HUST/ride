"""Workspace-owned Ray lifecycle. Only persisted owned submission IDs may stop."""
import json
import shlex
import threading
import uuid
from pathlib import Path
from datetime import datetime, timezone
from urllib.request import urlopen

class Runtime:
    def __init__(self, config, client=None):
        self.config = config
        self.lock = threading.RLock()
        self.path = Path(config['state_file'])
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if client is None:
            from ray.job_submission import JobSubmissionClient
            client = JobSubmissionClient(config['ray_address'])
        self.client = client
        self.state = json.loads(self.path.read_text()) if self.path.exists() else {'run_id': uuid.uuid4().hex, 'jobs': {}, 'operations': []}
        self.save()

    def save(self):
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.state, indent=2))
        temporary.replace(self.path)

    def operation(self, action, target, result):
        self.state['operations'].append({'at':datetime.now(timezone.utc).isoformat(), 'action':action, 'target':target, 'result':result})
        self.save()

    def start(self, identifier):
        with self.lock:
            spec = next(c for c in self.config['controllers'] if c['id']==identifier)
            if spec.get('entrypoint') != 'request-throttling':
                raise ValueError('Unsupported controller entrypoint')
            prior = self.state['jobs'].get(identifier)
            if prior and self.client.get_job_status(prior).value in ('RUNNING','PENDING'):
                return {'job_id':prior, 'unchanged':True}
            # Persist intent before submission. Ambiguous failures retain exact ID.
            job_id = 'ride-controller-'+self.state['run_id']+'-'+uuid.uuid4().hex[:8]
            self.state['jobs'][identifier] = job_id
            self.operation('start-intent', identifier, job_id)
            env = spec.get('runtime_env', {})
            command = shlex.join(['python','-m','thunderagent_controller_mod','--endpoint',spec['backend'],
                                  '--listen',spec.get('listen','0.0.0.0:9000'),'--enable',
                                  '--transport',spec.get('transport','no-keepalive')])
            try:
                self.client.submit_job(submission_id=job_id, entrypoint=command, runtime_env=env,
                                       entrypoint_resources=spec.get('resources',{}))
            except Exception:
                self.operation('start', identifier, 'UNKNOWN_OUTCOME'); raise
            self.operation('start', identifier, 'SUBMITTED')
            return {'job_id':job_id}

    def stop(self, identifier):
        with self.lock:
            job_id = self.state['jobs'].get(identifier)
            if not job_id: raise ValueError('No owned job for controller')
            result = self.client.stop_job(job_id)
            self.operation('stop',identifier,str(result))
            return {'job_id':job_id,'stop_requested':result}

    def snapshot(self):
        with self.lock:
            records=[]
            for spec in self.config['controllers']:
                job_id=self.state['jobs'].get(spec['id'])
                record={'id':spec['id'],'backend':spec['backend'],'endpoint':spec['endpoint'], 'job_id':job_id, 'job_status':'NOT_STARTED','ready':False}
                if job_id:
                    try: record['job_status']=self.client.get_job_status(job_id).value
                    except Exception as error: record['job_status']='UNKNOWN';record['job_error']=type(error).__name__
                try:
                    with urlopen(spec['backend'].rstrip('/')+'/health',timeout=2) as response:
                        record['engine_ready']=response.status==200
                except Exception as error:
                    record['engine_ready']=False;record['engine_probe_error']=type(error).__name__
                if record['job_status']=='RUNNING':
                    try:
                        for route,key in [('/migration-identity','identity'),('/health','health'),('/programs','programs')]:
                            with urlopen(spec['endpoint'].rstrip('/')+route,timeout=2) as response:record[key]=json.load(response)
                        record['controller_ready']=record['identity'].get('backends')==[spec['backend']] and record['identity'].get('scheduling_enabled') is True
                        record['ready']=record['controller_ready'] and record['engine_ready']
                    except Exception as error:record['probe_error']=type(error).__name__
                records.append(record)
            return {'name':self.config.get('name','RIDE'),'workspace':self.config['workspace'],
                    'run_id':self.state['run_id'],'observed_at':datetime.now(timezone.utc).isoformat(),
                    'controllers':records,'operations':self.state['operations'][-30:],
                    'capabilities':{'inspect':True,'start_controller':True,'mutate':True}}
