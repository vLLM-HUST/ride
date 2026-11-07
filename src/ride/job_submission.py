"""Stable component names, distinct from unique Ray submission identities."""
import re
import shlex


CONTROLLER_NAMES = {
    'request-throttling': 'Request Throttling Controller',
    'request-throttling-managed': 'Request Throttling Controller',
    'kv-control': 'Key Value Cache Controller',
    'instance-scaling': 'Instance Autoscaling Controller',
}


def component_name(kind, spec):
    name = spec.get('display_name')
    if name is None:
        controller_type = spec.get('type', spec.get('entrypoint'))
        name = (CONTROLLER_NAMES.get(controller_type, spec['id'])
                if kind == 'controllers' else 'Inference Model ' + spec['id'])
    if (not isinstance(name, str) or not name.strip() or len(name) > 160
            or any(ord(character) < 32 or ord(character) == 127 for character in name)):
        raise ValueError('Component display_name must be 1–160 printable characters')
    return name


def ray_entrypoint(command, name):
    """Keep a native Ray driver alive for the foreground component command.

    Commands are argument lists encoded by registry.command; do not interpret
    them through an extra shell or change their environment/resource assignment.
    """
    arguments = shlex.split(command)
    if not arguments:
        raise ValueError('Component command is empty')
    return shlex.join(['python', '-m', 'ride.ray_job', '--name', name, '--', *arguments])


def next_execution_submission_id(submission_id):
    match = re.fullmatch(r'(.+)-execution-([1-9][0-9]*)', submission_id)
    if not match:
        raise ValueError('Explicit execution number required for management recovery')
    return match[1] + '-execution-' + str(int(match[2]) + 1)


def job_metadata(name, component_id, workspace, execution):
    return {'job_name': name, 'ride.component_id': component_id,
            'ride.workspace': str(workspace), 'ride.execution': str(execution)}
