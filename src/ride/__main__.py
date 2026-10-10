import argparse
import json
import os
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import urlopen
from datetime import datetime, timezone

def snapshot(config):
    controllers = []
    for item in config.get('controllers', []):
        record = {'id': item['id'], 'endpoint': item['endpoint'], 'state': 'Unavailable'}
        try:
            with urlopen(item['endpoint'].rstrip('/') + '/migration-identity', timeout=3) as response:
                record['identity'] = json.load(response)
            with urlopen(item['endpoint'].rstrip('/') + '/health', timeout=3) as response:
                record['health'] = json.load(response)
            record['state'] = 'Reachable'
        except Exception as error:
            record['error'] = type(error).__name__
        controllers.append(record)
    return {'name': config.get('name', 'RIDE'), 'mode': 'read-only-inspection',
            'observed_at': datetime.now(timezone.utc).isoformat(), 'controllers': controllers,
            'capabilities': {'inspect': True, 'start_controller': False, 'mutate': False}}

def handler(config, runtime=None):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split('?')[0]
            if path == '/healthz':
                body, mime = json.dumps({'status': 'ok', 'service': 'ride'}).encode(), 'application/json'
            elif path in ('/api/v1/status', '/api/v1/controllers'):
                body, mime = json.dumps(runtime.snapshot() if runtime else snapshot(config)).encode(), 'application/json'
            elif path in ('/', '/index.html'):
                body, mime = Path(__file__).with_name('index.html').read_bytes(), 'text/html; charset=utf-8'
            else:
                self.send_error(404); return
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers(); self.wfile.write(body)
        def do_POST(self):
            if not runtime:
                self.send_error(405); return
            # A browser must deliberately send JSON. Cross-origin forms are refused.
            if self.headers.get('Content-Type') != 'application/json':
                self.send_error(403); return
            origin=self.headers.get('Origin')
            if origin:
                from urllib.parse import urlsplit
                if urlsplit(origin).netloc != self.headers.get('Host'):
                    self.send_error(403); return
            parts=self.path.split('/')
            if len(parts)!=6 or parts[1:4]!=['api','v1','controllers'] or parts[5] not in ('start','stop'):
                self.send_error(404); return
            try:
                result=getattr(runtime,parts[5])(parts[4])
                body=json.dumps(result).encode()
                self.send_response(202);self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            except Exception as error:
                self.send_error(409,type(error).__name__)
    return Handler

def main():
    parser = argparse.ArgumentParser(description='RIDE workspace control plane')
    sub = parser.add_subparsers(dest='command', required=True)
    serve = sub.add_parser('serve')
    serve.add_argument('--config', required=True)
    serve.add_argument('--listen', default='127.0.0.1:19100')
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    runtime=None
    if config.get('deployment')=='ray':
        from .runtime import Runtime
        runtime=Runtime(config)
        for controller in config['controllers']:
            if controller.get('autostart',False):runtime.start(controller['id'])
    host, port = args.listen.rsplit(':', 1)
    print(json.dumps({'service': 'ride', 'pid': os.getpid(), 'listen': args.listen,
                      'mode': 'ray-controller-management' if runtime else 'read-only-inspection'}), flush=True)
    ThreadingHTTPServer((host, int(port)), handler(config,runtime)).serve_forever()

if __name__ == '__main__':
    main()
