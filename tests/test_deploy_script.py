"""Check CloudShell deployment orchestration without contacting AWS."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "deploy-sandbox.sh"


class DeployScriptTests(unittest.TestCase):
    def run_script(self, *args: str) -> tuple[subprocess.CompletedProcess[str], str]:
        with tempfile.TemporaryDirectory() as directory:
            bin_dir = Path(directory)
            log_path = bin_dir / "aws.log"
            aws_path = bin_dir / "aws"
            aws_path.write_text(
                "#!/usr/bin/env bash\n"
                "printf '%s\\n' \"$*\" >> \"$MOCK_AWS_LOG\"\n"
                "case \"$1 $2\" in\n"
                "  'sts get-caller-identity') echo 123456789012 ;;\n"
                "  'cloudformation describe-stacks')\n"
                "    case \"$*\" in\n"
                "      *WebUrl*) echo http://127.0.0.1/ ;;\n"
                "      *NodeAInstanceId*) echo i-node-a ;;\n"
                "      *NodeBInstanceId*) echo i-node-b ;;\n"
                "    esac ;;\n"
                "esac\n",
                encoding="utf-8",
            )
            aws_path.chmod(0o755)
            curl_path = bin_dir / "curl"
            curl_path.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            curl_path.chmod(0o755)
            environment = dict(os.environ)
            environment["PATH"] = f"{bin_dir}:{environment['PATH']}"
            environment["MOCK_AWS_LOG"] = str(log_path)
            result = subprocess.run(
                ["bash", str(SCRIPT), *args],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            log = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
            return result, log

    def test_deploys_in_dependency_order_with_peer_ssh_off(self) -> None:
        result, log = self.run_script("--management-cidr", "203.0.113.10/32")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(log.index("--stack-name cloudlink-network"), log.index("--stack-name cloudlink-web"))
        self.assertLess(log.index("--stack-name cloudlink-web"), log.index("--stack-name cloudlink-probes"))
        self.assertIn("EnablePeerSsh=false", log)
        self.assertIn("ManagementCidr=203.0.113.10/32", log)
        self.assertIn("http://127.0.0.1/", result.stdout)

    def test_peer_ssh_requires_explicit_opt_in(self) -> None:
        result, log = self.run_script("--management-cidr", "203.0.113.10/32", "--enable-peer-ssh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("EnablePeerSsh=true", log)

    def test_invalid_management_address_stops_before_aws(self) -> None:
        result, log = self.run_script("--management-cidr", "0.0.0.0/0")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(log, "")


if __name__ == "__main__":
    unittest.main()
