"""Ray-only execution entrypoint. Controller packages remain independent of Ray.

    Ray Jobs owns the entrypoint process group, including the foreground child.
    Do not detach the child, add another resource reservation, retry it or impose
    a business timeout. Its stdout/stderr go directly to the Ray Job log.
"""
import argparse
import json
import os
import subprocess


def run(command, name, *, ray_module=None):
    if not command:
        raise ValueError('Foreground component command required')
    if ray_module is None:
        import ray as ray_module
    # Ray Jobs supplies the selected cluster address and JobConfig metadata.
    # Never start a private Ray runtime when the selected cluster is unavailable.
    ray_module.init(address=os.environ.get('RAY_ADDRESS') or 'auto')
    try:
        print(json.dumps({'component': name,
                          'ray_job_id': str(ray_module.get_runtime_context().get_job_id()),
                          'event': 'driver_registered'}), flush=True)
        result = subprocess.run(command, check=False)
        return result.returncode if result.returncode >= 0 else 128 - result.returncode
    finally:
        ray_module.shutdown()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name', required=True)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    arguments = parser.parse_args()
    command = arguments.command
    if command[:1] == ['--']:
        command = command[1:]
    return run(command, arguments.name)


if __name__ == '__main__':
    raise SystemExit(main())
