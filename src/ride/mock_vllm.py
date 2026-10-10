"""CPU-only deterministic OpenAI fixture. Never a real model or cache benchmark."""
import argparse,json,time,threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer

def server(host,port):
    state={'requests':0};lock=threading.Lock()
    class Handler(BaseHTTPRequestHandler):
        def reply(self,value,status=200):
            body=json.dumps(value).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def do_GET(self):
            if self.path=='/health':return self.reply({'status':'ok','evidence_type':'mock','requires_accelerator':False})
            if self.path=='/v1/models':return self.reply({'object':'list','data':[{'id':'mock-vllm','object':'model','owned_by':'ride-test-fixture'}]})
            if self.path=='/metrics':
                body=('vllm:cache_config_info{block_size="128",num_gpu_blocks="1206"} 1\nvllm:num_requests_running{model_name="mock-vllm"} 0\nvllm:num_requests_waiting{model_name="mock-vllm"} 0\nvllm:kv_cache_usage_perc{model_name="mock-vllm"} 0\n').encode()
                self.send_response(200);self.send_header('Content-Type','text/plain');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body);return
            self.reply({'error':'not found'},404)
        def do_POST(self):
            if self.path!='/v1/chat/completions':return self.reply({'error':'not found'},404)
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=65536:raise ValueError('Invalid request size')
                data=json.loads(self.rfile.read(length))
                if data.get('stream'):return self.reply({'error':'Streaming is not implemented by this fixture'},400)
                if data.get('model')!='mock-vllm' or not data.get('messages'):raise ValueError('Expected mock-vllm and messages')
                with lock:state['requests']+=1;number=state['requests']
                self.reply({'id':'mock-'+str(number),'object':'chat.completion','created':int(time.time()),'model':'mock-vllm','choices':[{'index':0,'message':{'role':'assistant','content':'hello'},'finish_reason':'stop'}],'usage':{'prompt_tokens':8,'completion_tokens':1,'total_tokens':9},'ride_evidence_type':'mock'})
            except (ValueError,TypeError) as e:self.reply({'error':str(e)},400)
    return ThreadingHTTPServer((host,port),Handler)

def main():
    p=argparse.ArgumentParser();p.add_argument('--host',default='0.0.0.0');p.add_argument('--port',type=int,default=8000);a=p.parse_args()
    print(json.dumps({'service':'mock-vllm','evidence_type':'mock','requires_accelerator':False}),flush=True)
    server(a.host,a.port).serve_forever()
if __name__=='__main__':main()
