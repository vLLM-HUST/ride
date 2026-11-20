import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import tarfile
import sys
import unittest
from unittest.mock import patch

script = Path(__file__).resolve().parents[1] / "scripts/clean_machine_deployment.py"
spec = importlib.util.spec_from_file_location("clean_machine_deployment", script)
clean = importlib.util.module_from_spec(spec)
with patch.object(sys, "path", [str(script.parent), *sys.path]):
    spec.loader.exec_module(clean)


class CleanMachineDeploymentTests(unittest.TestCase):
    def inventory(self):
        return {
            "name": "myc-pujiang", "ssh_user": "root", "ssh_key": "/keys/id",
            "known_hosts": "/keys/known_hosts", "expected_nodes": 16,
            "nodes": [{"address": f"192.0.2.{i}", "cards": 8, "cpus": 12} for i in range(1, 17)],
            "model": "served-model", "model_args": ["--max-model-len", "32768"],
            "assets": {name: {"url": f"https://packages.example/{name}", "sha256": "a" * 64}
                       for name in ("python-runtime", "jump-wheelhouse", "worker-wheelhouse", "worker-debs", "model", "tokenizer", "swe-smith", "cann")},
            "installers": [{"asset": "cann", "args": ["--quiet", "--install"]}],
            "environment_scripts": ["/usr/local/Ascend/ascend-toolkit/set_env.sh"],
        }

    def test_incomplete_inventory_rejected_before_preparation(self):
        config = self.inventory()
        config["nodes"].pop()
        with self.assertRaisesRegex(ValueError, "expected 16"):
            clean.validate(config)

    def test_builds_16_ray_members_and_model_replicas(self):
        config = self.inventory()
        clean.validate(config)
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            plan = clean.write_plans(config, work, "/opt/ride-clean/myc-pujiang", "secret")
            cluster = json.loads((work / "cluster.json").read_text())
            self.assertEqual(len(cluster["provider"]["worker_ips"]), 15)
            self.assertEqual(cluster["min_workers"], 15)
            self.assertEqual(len(plan["model_services"]), 16)
            self.assertEqual(len(plan["model_bindings"][0]["model_services"]), 16)
            self.assertEqual(plan["model_services"][-1]["resources"], {"NPU": 8, "node:192.0.2.16": 0.001})
            self.assertNotIn("secret", (work / "request-throttling.json").read_text())

    def test_download_refuses_checksum_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.write_bytes(b"valid")
            dest = root / "download"
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                clean.fetch({"url": source.as_uri(), "sha256": "0" * 64}, dest)
            self.assertFalse(dest.exists())
            clean.fetch({"url": source.as_uri(), "sha256": hashlib.sha256(b"valid").hexdigest()}, dest)
            self.assertEqual(dest.read_bytes(), b"valid")

    def test_archive_rejects_a_runtime_link_outside_the_installation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = root / "bad.tar"
            with tarfile.open(bundle, "w") as tar:
                executable = tarfile.TarInfo("python/bin/python3")
                executable.type = tarfile.SYMTYPE
                executable.linkname = "../../../outside"
                tar.addfile(executable)
            with self.assertRaisesRegex(ValueError, "Unsafe link"):
                clean.unpack(bundle, root / "extracted", runtime=True)
            self.assertFalse((root / "outside").exists())

    def test_archive_keeps_the_runtime_executable_and_internal_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = root / "runtime.tar"
            with tarfile.open(bundle, "w") as tar:
                executable = tarfile.TarInfo("python/bin/python3.12")
                executable.mode = 0o755
                executable.size = 1
                tar.addfile(executable, io.BytesIO(b"x"))
                link = tarfile.TarInfo("python/bin/python3")
                link.type = tarfile.SYMTYPE
                link.linkname = "python3.12"
                tar.addfile(link)
            clean.unpack(bundle, root / "installed", runtime=True)
            target = root / "installed/python/bin/python3"
            self.assertEqual(target.read_bytes(), b"x")
            self.assertTrue(target.stat().st_mode & 0o100)

    def test_worker_inputs_are_streamed_and_use_local_paths(self):
        config = self.inventory()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            clean.write_plans(config, root, "/opt/ride-clean/myc-pujiang", "secret")
            staged = root / "cann"
            staged.write_bytes(b"example test installer")
            deb = root / "base.deb"
            deb.write_bytes(b"test")
            receipt = root / "worker-debs.sha256"
            receipt.write_text("test")
            transferred = root / "received.tar"
            with patch.object(clean, "ssh", return_value=["sh", "-c", 'cat > "$1"', "ssh", str(transferred)]):
                code = clean.prepare_node(config, config["nodes"][0], "/opt/ride-clean/myc-pujiang",
                                          root, "ray start", root, ({"cann": staged}, [deb], receipt))
            self.assertEqual(code, 0)
            with tarfile.open(transferred) as archive:
                worker = json.load(archive.extractfile("worker.json"))
                self.assertEqual(worker["assets"]["cann"]["url"],
                                 "file:///opt/ride-clean/myc-pujiang/incoming/cann.run")
                self.assertEqual(archive.extractfile("incoming/cann.run").read(), staged.read_bytes())
                self.assertIn("debs/base.deb", archive.getnames())

    def test_jump_unpacks_the_runtime_once_before_installing_wheels(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.inventory()
            with (patch.object(clean, "fetch", side_effect=lambda asset, path: path),
                  patch.object(clean, "unpack", side_effect=lambda archive, path, **kwargs: path.mkdir()) as extract,
                  patch.object(clean.subprocess, "run")):
                self.assertEqual(clean.environment(root, config["assets"], "jump"), root / "venv/bin/python")
            self.assertEqual([call.args[1].name for call in extract.call_args_list], ["wheelhouse", "python-runtime"])

    def test_worker_debs_accepts_ubuntu_update_version_filenames(self):
        config = self.inventory()
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp).resolve()
            root = source / "jump"
            root.mkdir()
            raw = source / "worker-debs.tar"
            with tarfile.open(raw, "w") as tar:
                package = tarfile.TarInfo("libcc1-0_12.3.0-1ubuntu1~22.04.3_arm64.deb")
                package.size = 1
                tar.addfile(package, io.BytesIO(b"x"))
            lock = source / "package"
            lock.write_bytes(b"locked artifact")
            for asset in ("worker-wheelhouse", "model", "cann", "worker-debs"):
                path = raw if asset == "worker-debs" else lock
                config["assets"][asset] = {"url": path.as_uri(), "sha256": clean.hash_file(path)}
            _, packages, checksums = clean.stage_worker_assets(config, root)
            self.assertEqual([deb.name for deb in packages], [package.name])
            self.assertIn(package.name, checksums.read_text())
