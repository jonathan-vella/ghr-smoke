import contextlib
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml


WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "vmss-smoke.yml"
TEXT = WORKFLOW.read_text(encoding="utf-8")
PYTHON = TEXT.split("          python3 - <<'PY'\n", 1)[1].split("          PY\n", 1)[0]
PYTHON = "\n".join(line[10:] for line in PYTHON.splitlines())
PREFIX = "jonathan-vella/ghr-smoke/.github/workflows/vmss-smoke.yml@refs/heads/main"


def shell_blocks():
    blocks = []
    for block in TEXT.split("        run: |\n")[1:]:
        lines = []
        for line in block.splitlines():
            if line and not line.startswith("          "):
                break
            lines.append(line[10:])
        blocks.append("\n".join(lines) + "\n")
    return blocks


class DispatchContract(unittest.TestCase):
    def context(self):
        return {
            "GITHUB_ACTOR": "jonathan-vella",
            "GITHUB_REPOSITORY": "jonathan-vella/ghr-smoke",
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_WORKFLOW_REF": PREFIX,
            "GITHUB_SHA": "a" * 40,
            "GITHUB_WORKFLOW_SHA": "a" * 40,
            "REVIEWED_COMMIT": "a" * 40,
            "ENVELOPE": "b" * 32,
            "ORDINAL": "1",
            "SPIKE_LABEL": "ghr-smoke-vmss-spike-" + "b" * 32 + "-1",
            "EXPECTED_NAT_IPV4": "8.8.8.8",
            "EXPECTED_RESOURCE_GROUP": "rg-ghrunners-spike-vmss-swc",
        }

    def execute(self, updates):
        env = self.context() | updates
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            env["GITHUB_OUTPUT"] = str(output)
            with patch.dict(os.environ, env, clear=True), contextlib.redirect_stdout(io.StringIO()):
                try:
                    exec(compile(PYTHON, str(WORKFLOW), "exec"), {})
                except SystemExit:
                    self.assertFalse(output.exists(), "Rejected input must not emit a queue label.")
                    raise
            return output.read_text(encoding="ascii")

    def test_exact_custom_only_label_for_both_ordinals(self):
        for ordinal in ("1", "2"):
            label = "ghr-smoke-vmss-spike-" + "b" * 32 + "-" + ordinal
            self.assertEqual(self.execute({"ORDINAL": ordinal, "SPIKE_LABEL": label}), "label=" + label + "\n")

    def test_rejects_unreviewed_inputs_and_context(self):
        invalid = {
            "GITHUB_ACTOR": ["attacker"],
            "GITHUB_REPOSITORY": ["jonathan-vella/azure-gh-runners"],
            "GITHUB_EVENT_NAME": ["pull_request", "pull_request_target", "workflow_run"],
            "GITHUB_RUN_ATTEMPT": ["2", "0", ""],
            "GITHUB_REF": ["refs/heads/topic", "refs/pull/1/merge"],
            "GITHUB_WORKFLOW_REF": [PREFIX.replace("main", "topic")],
            "GITHUB_SHA": ["c" * 40],
            "GITHUB_WORKFLOW_SHA": ["c" * 40],
            "REVIEWED_COMMIT": ["A" * 40, "", "a" * 39],
            "ENVELOPE": ["B" * 32, "", "b" * 31, "b" * 32 + "\n"],
            "ORDINAL": ["0", "3", "01", "1\n"],
            "SPIKE_LABEL": ["self-hosted", "ghr-smoke-vmss-spike-" + "b" * 32, "x\nlabel=self-hosted"],
            "EXPECTED_NAT_IPV4": ["127.0.0.1", "10.0.0.1", "::1", "", "8.8.8.8\n",
                                  "224.0.0.1", "255.255.255.255"],
            "EXPECTED_RESOURCE_GROUP": ["production", ""],
        }
        for key, values in invalid.items():
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(SystemExit):
                    self.execute({key: value})

    def test_static_policy(self):
        trigger = TEXT.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
        self.assertEqual([line for line in trigger.splitlines()
                          if line.startswith("  ") and not line.startswith("   ")],
                         ["  workflow_dispatch:"])
        self.assertEqual(TEXT.count("  workflow_dispatch:"), 1)
        for forbidden in ("pull_request:", "pull_request_target:", "workflow_run:", "uses:",
                          "secrets.", "id-token:", "continue-on-error:", "sudo -", "docker run",
                          "set -x", "printenv", "retry", "actions/checkout"):
            self.assertNotIn(forbidden, TEXT)
        self.assertIn("permissions: {}", TEXT)
        self.assertIn("    runs-on: ${{ needs.validate.outputs.label }}", TEXT)
        self.assertIn("    needs: validate", TEXT)
        self.assertIn("    timeout-minutes: 15", TEXT)
        self.assertEqual(TEXT.count("    runs-on:"), 2)
        self.assertEqual(TEXT.count("    timeout-minutes:"), 2)
        self.assertIn("    timeout-minutes: 2", TEXT)
        self.assertIn("--output /dev/null", TEXT)
        self.assertIn("--max-time 5", TEXT)
        self.assertIn("--max-time 10", TEXT)
        self.assertIn("/bin/bash /opt/ghr-vmss/verify-spike-worker.sh", TEXT)
        self.assertNotIn("bash /opt/ghr-vmss/pre-job-spike.sh", TEXT)
        self.assertNotIn("ACTIONS_RUNNER_HOOK_JOB_STARTED=", TEXT)
        self.assertEqual(TEXT.count("github.actor == 'jonathan-vella'"), 2)
        self.assertEqual(TEXT.count("github.ref == 'refs/heads/main'"), 2)
        self.assertEqual(TEXT.count("github.event_name == 'workflow_dispatch'"), 2)
        self.assertNotIn("${{", shell_blocks()[0])
        self.assertNotIn("${{", shell_blocks()[1])
        self.assertIn("! command -v sudo", TEXT)
        self.assertIn("! command -v dockerd", TEXT)
        self.assertIn("$(id -u) == 1001 && $(id -g) == 1001", TEXT)
        self.assertEqual(TEXT.count("$(curl "), TEXT.count("$(curl --disable "))

    def test_yaml_job_graph_and_input_shape(self):
        workflow = yaml.load(TEXT, Loader=yaml.BaseLoader)
        self.assertEqual(set(workflow), {"name", "on", "permissions", "concurrency", "jobs"})
        self.assertEqual(set(workflow["on"]), {"workflow_dispatch"})
        self.assertEqual(workflow["permissions"], {})
        inputs = workflow["on"]["workflow_dispatch"]["inputs"]
        self.assertEqual(set(inputs), {"envelope", "ordinal", "spike_label",
                                      "reviewed_commit", "expected_nat_ipv4",
                                      "expected_resource_group"})
        for name, config in inputs.items():
            self.assertEqual(config["required"], "true")
            self.assertNotIn("default", config)
            self.assertEqual(config["type"], "choice" if name == "ordinal" else "string")
        self.assertEqual(inputs["ordinal"]["options"], ["1", "2"])
        jobs = workflow["jobs"]
        self.assertEqual(set(jobs), {"validate", "smoke"})
        self.assertEqual(jobs["validate"]["runs-on"], "ubuntu-24.04")
        self.assertEqual(jobs["validate"]["timeout-minutes"], "2")
        self.assertEqual(jobs["smoke"]["needs"], "validate")
        self.assertEqual(jobs["smoke"]["runs-on"], "${{ needs.validate.outputs.label }}")
        self.assertEqual(jobs["smoke"]["timeout-minutes"], "15")
        self.assertEqual(jobs["validate"]["outputs"], {"label": "${{ steps.contract.outputs.label }}"})
        for job in jobs.values():
            self.assertNotIn("permissions", job)
            self.assertNotIn("strategy", job)
            self.assertEqual(len(job["steps"]), 1)
            step = job["steps"][0]
            self.assertEqual(step["shell"], "bash")
            self.assertNotIn("uses", step)
            self.assertNotIn("ACTIONS_RUNNER_HOOK_JOB_STARTED", step["env"])
            self.assertNotIn("${{", step["run"])
        self.assertEqual(jobs["validate"]["steps"][0]["id"], "contract")

    def test_bash_syntax_without_execution(self):
        blocks = shell_blocks()
        self.assertEqual(len(blocks), 2)
        for block in blocks:
            result = subprocess.run(["bash", "-n"], input=block.encode("utf-8"),
                                    capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))

    def test_identity_probe_fail_closed_without_network(self):
        worker = shell_blocks()[1]
        probe = worker.split("set +e\n", 1)[1].split("for target in ", 1)[0]
        for exit_code, status, accepted in (
            (0, "400", True), (0, "404", True), (7, "000", True), (28, "000", True),
            (0, "200", False), (0, "401", False), (0, "403", False),
            (0, "500", False), (6, "000", False), (28, "200", False),
        ):
            with self.subTest(exit_code=exit_code, status=status):
                script = (
                    "set -euo pipefail\n"
                    "fail() { printf '%s\\n' \"$1\" >&2; exit 1; }\n"
                    "curl() {\n"
                    "  [[ \" $* \" == *' --output /dev/null '* ]] || return 99\n"
                    "  [[ \" $* \" == *' --max-time 5 '* ]] || return 99\n"
                    f"  printf '%s' '{status}'; return {exit_code}\n"
                    "}\nset +e\n" + probe
                )
                result = subprocess.run(["bash"], input=script.encode("utf-8"),
                                        capture_output=True, check=False)
                self.assertEqual(result.returncode == 0, accepted, result.stderr.decode("utf-8"))
                self.assertEqual(result.stdout, b"")

    def test_outbound_and_nat_fail_closed_without_network(self):
        worker = shell_blocks()[1]
        checks = "for target in " + worker.split("for target in ", 1)[1].split(
            "printf 'Nonsecret smoke", 1)[0]
        for github, nat, exit_code, accepted in (
            ("200", "8.8.8.8", 0, True), ("403", "8.8.8.8", 0, False),
            ("200", "1.1.1.1", 0, False), ("200", "", 28, False),
            ("200", "unexpected-body", 0, False),
        ):
            with self.subTest(github=github, nat=nat, exit_code=exit_code):
                script = (
                    "set -euo pipefail\nEXPECTED_NAT_IPV4=8.8.8.8\n"
                    "fail() { printf '%s\\n' \"$1\" >&2; exit 1; }\n"
                    "curl() {\n"
                    "  [[ \" $* \" == *' --max-time 10 '* ]] || return 99\n"
                    "  [[ \" $* \" == *\" --proto =https \"* ]] || return 99\n"
                    "  if [[ \" $* \" == *' https://api.ipify.org '* ]]; then\n"
                    f"    printf '%s' '{nat}'; return {exit_code}\n"
                    "  else\n"
                    "    [[ \" $* \" == *' --output /dev/null '* ]] || return 99\n"
                    f"    printf '%s' '{github}'; return 0\n"
                    "  fi\n}\n" + checks
                )
                result = subprocess.run(["bash"], input=script.encode("utf-8"),
                                        capture_output=True, check=False)
                self.assertEqual(result.returncode == 0, accepted, result.stderr.decode("utf-8"))
                self.assertEqual(result.stdout, b"")


if __name__ == "__main__":
    unittest.main()
