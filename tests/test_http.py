import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from ride.__main__ import handler

class Runtime:
    def __init__(self): self.actions=[]
    def snapshot(self): return {'controllers': []}
    def start(self, identifier): self.actions.append(identifier);return {'job_id':'owned'}

class Tests(unittest.TestCase):
    def test_mutation_requires_json_same_origin(self):
        runtime=Runtime();server=ThreadingHTTPServer(('127.0.0.1',0),handler({},runtime))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        address='http://127.0.0.1:'+str(server.server_port)
        try:
            for headers in ({'Content-Type':'text/plain'},{'Content-Type':'application/json','Origin':'https://untrusted.example'}):
                with self.assertRaises(HTTPError) as error:urlopen(Request(address+'/api/v1/controllers/request-throttling/start',data=b'{}',headers=headers))
                self.assertEqual(error.exception.code,403)
            self.assertEqual(runtime.actions,[])
            response=urlopen(Request(address+'/api/v1/controllers/request-throttling/start',data=b'{}',headers={'Content-Type':'application/json','Origin':address}))
            self.assertEqual(response.status,202);self.assertEqual(runtime.actions,['request-throttling'])
        finally:server.shutdown();server.server_close();thread.join()
