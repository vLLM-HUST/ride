"""Process descriptions: policy implementations remain in their own packages."""
import shlex
from importlib.metadata import entry_points

def controller_adapter(name):
    matches=list(entry_points(group="ride.controllers", name=name))
    if len(matches)>1: raise ValueError("Duplicate Controller type: " + name)
    return matches[0].load() if matches else None


def command(kind, spec):
    name = spec.get('type', spec.get('entrypoint'))
    if kind == 'controllers' and name == 'request-throttling':
        if not spec.get('backend') or not spec.get('endpoint'):
            raise ValueError('Controller requires --backend and reachable --endpoint')
        return shlex.join(['python', '-m', 'thunderagent_controller_mod',
            '--endpoint', spec['backend'], '--listen', spec.get('listen', '0.0.0.0:9000'),
            '--enable', '--transport', spec.get('transport', 'no-keepalive')])
    if kind == 'controllers':
        adapter=controller_adapter(name)
        if adapter is not None:return adapter.command(spec)
    if kind == 'model_services' and name == 'mock-vllm':
        if not spec.get('model') or not spec.get('endpoint'):raise ValueError('Mock service requires model and endpoint')
        if spec.get('num_gpus',0)>0 or any(v>0 for k,v in spec.get('resources',{}).items() if k in ('NPU','GPU')):raise ValueError('Mock fixture cannot reserve accelerator resources')
        return shlex.join(['python','-m','ride.mock_vllm','--host',spec.get('host','0.0.0.0'),'--port',str(spec.get('port',8000))])
    if kind == 'model_services' and name == 'vllm':
        if not spec.get('model') or not spec.get('endpoint'):
            raise ValueError('Model service requires --model and reachable --endpoint')
        args = spec.get('args', [])
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            raise ValueError('Model args must be a list of strings')
        command_args = ['vllm', 'serve', spec['model'], '--host',
            spec.get('host', '0.0.0.0'), '--port', str(spec.get('port', 8000)), *args]
        scripts = spec.get('environment_scripts', [])
        if not isinstance(scripts, list) or not all(isinstance(p, str) and p.startswith('/') for p in scripts):
            raise ValueError('Environment scripts must be explicitly configured absolute paths')
        if scripts:
            setup = 'set -e; ' + '; '.join('source ' + shlex.quote(p) for p in scripts) + '; exec "$@"'
            return shlex.join(['bash', '-c', setup, 'ride-model', *command_args])
        return shlex.join(command_args)
    raise ValueError('Unsupported ' + kind + ' type: ' + str(name))
