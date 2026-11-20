import importlib.util
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch


path = Path(__file__).resolve().parents[1] / "scripts/run_machine_experiment.py"
spec = importlib.util.spec_from_file_location("run_machine_experiment", path)
experiment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(experiment)


class MachineExperimentTests(unittest.TestCase):
    def execute(self, up_code):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            output = root / "results"
            configuration = root / "experiment.json"
            initial = root / "bootstrap.tar.gz"
            initial.write_bytes(b"bootstrap archive")
            configuration.write_text(json.dumps({
                "deployment": str(root / "deployment.json"),
                "initial_evidence": str(initial),
                "state_directory": str(root / "state"),
                "prepare_command": ["prepare-nodes"],
                "benchmark_command": ["score-requests"],
                "hosts": [{"name": "node-a", "paths": ["/evidence"]}],
            }))
            invoked = []

            def run(command, log):
                invoked.append(log.stem)
                log.write_text(log.stem + "\n")
                if log.stem == "benchmark":
                    self.assertEqual(command, ["score-requests", str(output)])
                    (output / "score.json").write_text('{"correct": 1}\n')
                return up_code if log.stem == "up" else 0

            def collect(host, config, path):
                self.assertEqual(host["name"], "node-a")
                (path / "node-a.tar.gz").write_bytes(b"remote archive")
                return {"exit_code": 0, "members": ["evidence"]}

            with (patch.object(sys, "argv", ["run", str(configuration), str(output)]),
                  patch.object(experiment, "run_logged", side_effect=run),
                  patch.object(experiment, "collect", side_effect=collect)):
                code = experiment.main()

            with tarfile.open(output.with_suffix(".tar.gz")) as result:
                self.assertIn("results/node-a.tar.gz", result.getnames())
                self.assertEqual(result.extractfile("results/bootstrap-evidence.tar.gz").read(), initial.read_bytes())
                manifest = result.extractfile("results/SHA256SUMS").read().decode()
                self.assertIn("  node-a.tar.gz", manifest)
            status = json.loads((output / "status.json").read_text())
            return code, invoked, status

    def test_measures_then_seals(self):
        code, invoked, status = self.execute(up_code=0)
        self.assertEqual(code, 0)
        self.assertEqual(invoked, ["validate", "prepare", "up", "benchmark"])
        self.assertEqual(status["status"], "PASS")

    def test_failed_deployment_skips_benchmark_and_seals_partial_data(self):
        code, invoked, status = self.execute(up_code=1)
        self.assertEqual(code, 1)
        self.assertEqual(invoked, ["validate", "prepare", "up"])
        self.assertEqual(status["status"], "FAIL")
        self.assertEqual(status["nodes"]["node-a"]["members"], ["evidence"])
