"""Process descriptions: policy implementations remain in their own packages."""
import shlex

def command(kind, spec):
    name = spec.get('type', spec.get('entrypoint'))
    if kind == 'controllers' and name == 'request-throttling':
        if not spec.get('backend') or not spec.get('endpoint'):
            raise ValueError('Controller requires --backend and reachable --endpoint')
        return shlex.join(['python', '-m', 'thunderagent_controller_mod',
            '--endpoint', spec['backend'], '--listen', spec.get('listen', '0.0.0.0:9000'),
            '--enable', '--transport', spec.get('transport', 'no-keepalive')])
    if kind == 'model_services' and name == 'vllm':
        if not spec.get('model') or not spec.get('endpoint'):
            raise ValueError('Model service requires --model and reachable --endpoint')
        args = spec.get('args', [])
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            raise ValueError('Model args must be a list of strings')
        return shlex.join(['vllm', 'serve', spec['model'], '--host',
            spec.get('host', '0.0.0.0'), '--port', str(spec.get('port', 8000)), *args])
    raise ValueError('Unsupported ' + kind + ' type: ' + str(name))
