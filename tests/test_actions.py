import os
import subprocess
import sys
import unittest
from unittest.mock import patch

from test_configuration import ROOT

import action_runtime


class PublicationActionTests(unittest.TestCase):
    def test_actions_run_packaged_code_with_quoted_environment_inputs(self):
        for name, command in (("prepare-release", "prepare"), ("finalize-release", "finalize")):
            with self.subTest(action=name):
                text = (ROOT / "actions" / name / "action.yml").read_text(encoding="utf-8")
                self.assertIn("using: composite", text)
                self.assertIn('python-version: "3.13"', text)
                self.assertIn("shell: bash", text)
                self.assertIn("ACTION_PATH: ${{ github.action_path }}", text)
                self.assertIn(f'run: python -I "$ACTION_PATH/../../toolkit/action_runtime.py" {command}', text)
                self.assertIn("GH_TOKEN: ${{ inputs.token }}", text)
                self.assertIn("GH_HOST: github.com", text)
                self.assertNotIn("always()", text)
                self.assertNotIn("continue-on-error", text)
                self.assertNotIn("checkout", text)
                self.assertNotIn("eval", text)
                for line in text.splitlines():
                    if line.strip().startswith("run:"):
                        self.assertNotIn("${{", line)
                    if "uses:" in line:
                        self.assertRegex(line, r"@[0-9a-f]{40}(?: |$)")

    def test_actions_have_only_data_inputs_and_documented_outputs(self):
        prepare = (ROOT / "actions" / "prepare-release" / "action.yml").read_text(encoding="utf-8")
        finalize = (ROOT / "actions" / "finalize-release" / "action.yml").read_text(encoding="utf-8")
        for name in ("tag", "version", "sha", "release-id", "release-url", "already-published", "context"):
            self.assertIn(f"value: ${{{{ steps.prepare.outputs.{name} }}}}", prepare)
        self.assertIn("CONFIG_PATH: ${{ inputs.config-path }}", prepare)
        self.assertIn("RELEASE_CONTEXT: ${{ inputs.context }}", finalize)
        self.assertNotIn("config-path:", finalize)
        self.assertNotIn("tooling-ref", prepare + finalize)
        self.assertNotIn("script:", prepare + finalize)
        self.assertNotIn("steps:", prepare.split("runs:")[0] + finalize.split("runs:")[0])

    def test_runtime_installs_only_bundled_requirements_in_temporary_environment(self):
        for command in ("prepare", "finalize"):
            with self.subTest(command=command), patch("sys.argv", ["action_runtime.py", command]), patch(
                "action_runtime.venv.EnvBuilder",
            ) as builder, patch("action_runtime.subprocess.run") as run:
                action_runtime.main()
                builder.assert_called_once_with(with_pip=True)
                environment = builder.return_value.create.call_args.args[0]
                self.assertFalse(environment.exists())
                install, execute = [call.args[0] for call in run.call_args_list]
                self.assertEqual(install[1:4], ["-I", "-m", "pip"])
                self.assertEqual(install[-2:], ["-r", str(ROOT / "toolkit" / "requirements.txt")])
                self.assertEqual(execute, [
                    install[0], "-I", str(ROOT / "toolkit" / "publish.py"), command,
                ])
                for call in run.call_args_list:
                    self.assertTrue(call.kwargs["check"])

    def test_runtime_refuses_commands_or_script_inputs(self):
        for args in ([], ["publish"], ["prepare", "echo unsafe"], ["finalize;echo unsafe"]):
            with self.subTest(args=args), patch("sys.argv", ["action_runtime.py", *args]), patch(
                "action_runtime.venv.EnvBuilder",
            ) as builder, self.assertRaises(ValueError):
                action_runtime.main()
            builder.assert_not_called()

    def test_isolated_entrypoint_ignores_consumer_pythonpath(self):
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(ROOT / "tests" / "fixtures")
        result = subprocess.run(
            [sys.executable, "-I", str(ROOT / "toolkit" / "publish.py"), "--help"],
            cwd=ROOT / "tests", env=environment, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("{prepare,finalize}", result.stdout)


if __name__ == "__main__":
    unittest.main()
