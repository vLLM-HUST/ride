import tempfile
import unittest
from pathlib import Path
from ride.runtime import Runtime

class Status:
    value="RUNNING"
class Client:
    def __init__(self):self.submitted=[];self.stopped=[]
    def submit_job(self,**kw):self.submitted.append(kw)
    def get_job_status(self,identifier):return Status()
    def stop_job(self,identifier):self.stopped.append(identifier);return True
class Tests(unittest.TestCase):
    def test_idempotence_ownership_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            c=Client();config={"state_file":str(Path(directory)/"state.json"),"workspace":"test","controllers":[{"id":"request-throttling","entrypoint":"request-throttling","backend":"http://127.0.0.1:8000","endpoint":"http://127.0.0.1:9000"}]}
            r=Runtime(config,c);a=r.start("request-throttling");r.start("request-throttling")
            self.assertEqual(len(c.submitted),1)
            restored=Runtime(config,c);restored.stop("request-throttling")
            self.assertEqual(c.stopped,[a["job_id"]])
            with self.assertRaises(ValueError):restored.stop("someone-else")
if __name__=="__main__":unittest.main()
