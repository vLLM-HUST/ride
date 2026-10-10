"""Management HTTP API shared by CLI and workspace UI."""
import json
from pathlib import Path
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlsplit, unquote

def handler(config, runtime=None):
    class Handler(BaseHTTPRequestHandler):
        def reply(self, value, status=200):
            body=json.dumps(value).encode();self.send_response(status)
            self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store')
            self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def parts(self): return [unquote(p) for p in urlsplit(self.path).path.strip('/').split('/')]
        def do_GET(self):
            parts=self.parts()
            try:
                if parts==['healthz']: return self.reply({'status':'ok','service':'ride'})
                if parts==['api','v1','status']: return self.reply(runtime.snapshot() if runtime else {'controllers':[],'model_services':[],'operations':[],'capabilities':{'mutate':False}})
                if runtime and parts[:2]==['api','v1'] and len(parts)>=3:
                    kind=parts[2].replace('-','_')
                    if kind in ('controllers','model_services'):
                        if len(parts)==3: return self.reply(runtime.snapshot()[kind])
                        if len(parts)==4: return self.reply(runtime.describe(kind,parts[3]))
                        if len(parts)==5 and parts[4]=='logs': return self.reply(runtime.logs(kind,parts[3]))
                if parts in ([''],['index.html']):
                    body=Path(__file__).with_name('index.html').read_bytes();self.send_response(200)
                    self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body);return
                self.send_error(404)
            except ValueError as e:self.reply({'error':str(e)},404)
            except Exception as e:self.reply({'error':type(e).__name__},503)
        def do_POST(self):
            if not runtime:self.send_error(405);return
            if self.headers.get('Content-Type')!='application/json':self.send_error(403);return
            origin=self.headers.get('Origin')
            if origin and urlsplit(origin).netloc!=self.headers.get('Host'):self.send_error(403);return
            parts=self.parts()
            if len(parts)!=5 or parts[:2]!=['api','v1'] or parts[2] not in ('controllers','model-services') or parts[4] not in ('start','stop'):
                self.send_error(404);return
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<=length<=65536:raise ValueError('Request body too large')
                changes=json.loads(self.rfile.read(length) or b'{}')
                if not isinstance(changes,dict):raise ValueError('Configuration must be an object')
                kind=parts[2].replace('-','_');name=parts[3]
                if parts[4]=='start':
                    # Old predeclared Controller endpoint stays compatible.
                    if not changes and kind=='controllers':result=runtime.start(name)
                    else:result=runtime.start_instance(kind,name,changes or None)
                else:result=runtime.stop_instance(kind,name)
                self.reply(result,202)
            except (ValueError,KeyError) as e:self.reply({'error':str(e)},409)
            except Exception as e:self.reply({'error':type(e).__name__},503)
    return Handler
