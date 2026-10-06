import unittest
from pathlib import Path

from sparkle_gen2.cli import build_components


class Cycle77EngineeringBindingTests(unittest.TestCase):

    def test_build_components_binds_engineering_inspect_to_gen2(self):
        _, agent, _ = build_components(
            activate_external_connectors=False
        )

        gateway = agent.gen1
        base = gateway.base

        system = base.system
        registry = system.tools
        tools = registry._tools

        self.assertIn("engineering_inspect", tools)

        tool = tools["engineering_inspect"]
        service = tool.service

        expected_root = Path.cwd().resolve()

        self.assertEqual(
            Path(service.root).resolve(),
            expected_root,
        )

        self.assertEqual(
            Path(service.path).resolve(),
            (
                Path.home()
                / ".local"
                / "share"
                / "sparkle-gen2"
                / "engineering.sqlite3"
            ).resolve(),
        )

    def test_build_components_works_outside_repo_cwd(self):
        import os
        import tempfile

        original_cwd = Path.cwd()
        old_db = os.environ.get("SPARKLE_GEN2_DB")
        old_engineering_db = os.environ.get(
            "SPARKLE_GEN2_ENGINEERING_DB"
        )
        old_engineering_root = os.environ.get(
            "SPARKLE_GEN2_ENGINEERING_ROOT"
        )

        try:
            with tempfile.TemporaryDirectory() as tmp:
                temp_root = Path(tmp)
                os.environ["SPARKLE_GEN2_DB"] = str(
                    temp_root / "gen2.sqlite3"
                )
                os.environ["SPARKLE_GEN2_ENGINEERING_DB"] = str(
                    temp_root / "engineering.sqlite3"
                )
                os.environ.pop(
                    "SPARKLE_GEN2_ENGINEERING_ROOT",
                    None,
                )

                os.chdir(temp_root)

                _, agent, _ = build_components(
                    activate_external_connectors=False
                )

                service = agent.gen1.base.system.tools._tools[
                    "engineering_inspect"
                ].service

                self.assertEqual(
                    Path(service.root).resolve(),
                    original_cwd.resolve(),
                )

        finally:
            os.chdir(original_cwd)

            if old_db is None:
                os.environ.pop("SPARKLE_GEN2_DB", None)
            else:
                os.environ["SPARKLE_GEN2_DB"] = old_db

            if old_engineering_db is None:
                os.environ.pop(
                    "SPARKLE_GEN2_ENGINEERING_DB",
                    None,
                )
            else:
                os.environ["SPARKLE_GEN2_ENGINEERING_DB"] = (
                    old_engineering_db
                )

            if old_engineering_root is None:
                os.environ.pop(
                    "SPARKLE_GEN2_ENGINEERING_ROOT",
                    None,
                )
            else:
                os.environ["SPARKLE_GEN2_ENGINEERING_ROOT"] = (
                    old_engineering_root
                )

    def test_engineering_inspect_can_read_gen2_core(self):
        _, agent, _ = build_components(
            activate_external_connectors=False
        )

        observation = agent.gen1.invoke(
            "engineering_inspect",
            {
                "operation": "file",
                "path": "src/sparkle_gen2/core.py",
            },
        )

        self.assertTrue(observation.ok)
        self.assertIsInstance(observation.output, dict)

        self.assertEqual(
            observation.output.get("path"),
            "src/sparkle_gen2/core.py",
        )


if __name__ == "__main__":
    unittest.main()
