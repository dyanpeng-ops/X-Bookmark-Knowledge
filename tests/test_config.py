"""`src/config.py` 的验收测试（Phase 6）。

覆盖范围
--------
示例配置可解析、本机配置可解析、相对路径解析为绝对路径、环境变量优先级、
版本与类型校验、未知键上报。

运行方式（项目根目录）::

    .venv\\Scripts\\python.exe -m unittest discover -s tests -t . -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import (  # noqa: E402  (path bootstrap must run first)
    ConfigError,
    default_project_root,
    load_config,
    resolve_path,
)

EXAMPLE = PROJECT_ROOT / "config" / "config.example.yaml"
REAL_CONFIG = PROJECT_ROOT / "config" / "config.yaml"


class ConfigTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="xbook-config-")
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def write_config(self, text: str, name: str = "config.yaml") -> Path:
        path = self.tmp / name
        path.write_text(text, encoding="utf-8")
        return path


class ShippedConfigTests(ConfigTestCase):
    """随仓库提供的两个配置文件都必须能被解析。"""

    def test_example_config_loads_without_unknown_keys(self):
        config = load_config(EXAMPLE, project_root=PROJECT_ROOT, env={})
        self.assertEqual(config.version, 1)
        self.assertEqual(config.unknown_keys, ())
        self.assertEqual(config.source_path, EXAMPLE)
        self.assertEqual(config.project_root, PROJECT_ROOT.resolve())

    def test_example_config_paths_are_absolute_and_resolved(self):
        config = load_config(EXAMPLE, project_root=PROJECT_ROOT, env={})
        for path in (
            config.paths.data_dir,
            config.paths.raw_dir,
            config.paths.state_dir,
            config.paths.log_dir,
            config.paths.knowledge_dir,
        ):
            self.assertTrue(path.is_absolute(), path)
            self.assertTrue(str(path).startswith(str(PROJECT_ROOT.resolve())), path)
        self.assertEqual(
            config.paths.knowledge_dir, PROJECT_ROOT.resolve() / "knowledge" / "X-Bookmarks"
        )
        self.assertEqual(config.paths.state_db_path, config.paths.state_dir / "state.db")
        self.assertEqual(config.paths.raw_json_path("123"), config.paths.raw_dir / "123.json")

    def test_example_config_collector_and_ingest_defaults(self):
        config = load_config(EXAMPLE, project_root=PROJECT_ROOT, env={})
        self.assertEqual(config.collector.provider, "fieldtheory")
        self.assertEqual(config.collector.executable, "fieldtheory.cmd")
        self.assertEqual(config.collector.executable_args, ())
        self.assertEqual(config.collector.command, ("fieldtheory.cmd",))
        self.assertTrue(config.collector.read_only)
        self.assertEqual(config.collector.auth.method, "firefox")
        self.assertEqual(config.collector.auth.browser, "firefox")
        self.assertEqual(config.collector.sync.max_minutes, 30)
        self.assertEqual(config.ingest.dedupe_key, "tweet_id")
        self.assertEqual(config.logging.level, "INFO")

    def test_real_config_points_upstream_into_project_data_dir(self):
        """本机 config.yaml（gitignore）已把上游目录迁到项目内 data/upstream。"""

        if not REAL_CONFIG.is_file():
            self.skipTest("config/config.yaml not present (gitignored)")
        config = load_config(REAL_CONFIG, project_root=PROJECT_ROOT, env={})
        self.assertEqual(
            config.collector.upstream_data_dir, PROJECT_ROOT.resolve() / "data" / "upstream"
        )
        self.assertEqual(config.unknown_keys, ())

    def test_sections_not_yet_modelled_are_still_reachable(self):
        config = load_config(EXAMPLE, project_root=PROJECT_ROOT, env={})
        self.assertEqual(config.section("media")["download"], True)
        self.assertIn("frontmatter", config.section("markdown"))
        self.assertEqual(config.section("safety")["forbid_writes_outside_project"], True)


class LoadConfigTests(ConfigTestCase):
    def test_missing_file_raises(self):
        with self.assertRaises(ConfigError) as ctx:
            load_config(self.tmp / "nope.yaml", project_root=self.tmp, env={})
        self.assertIn("config file not found", str(ctx.exception))

    def test_require_file_false_falls_back_to_defaults(self):
        config = load_config(
            self.tmp / "nope.yaml", project_root=self.tmp, env={}, require_file=False
        )
        self.assertIsNone(config.source_path)
        self.assertEqual(config.paths.data_dir, self.tmp / "data")
        self.assertEqual(config.collector.executable, "fieldtheory.cmd")

    def test_relative_paths_resolve_against_project_root(self):
        path = self.write_config("version: 1\npaths:\n  raw_dir: 'custom/raw'\n")
        config = load_config(path, project_root=self.tmp, env={})
        self.assertEqual(config.paths.raw_dir, self.tmp / "custom" / "raw")

    def test_absolute_paths_are_kept(self):
        absolute = (self.tmp / "abs").as_posix()
        path = self.write_config(f"version: 1\npaths:\n  raw_dir: '{absolute}'\n")
        config = load_config(path, project_root=self.tmp, env={})
        self.assertEqual(config.paths.raw_dir, self.tmp / "abs")

    def test_project_root_from_config_overrides_base(self):
        nested = self.tmp / "nested"
        nested.mkdir()
        path = self.write_config("version: 1\npaths:\n  project_root: 'nested'\n")
        config = load_config(path, project_root=self.tmp, env={})
        self.assertEqual(config.project_root, nested.resolve())
        self.assertEqual(config.paths.raw_dir, nested.resolve() / "data" / "raw")

    def test_config_value_beats_machine_env_var(self):
        """配置文件是本项目的权威来源；环境变量只在配置留空时回退。"""

        env_dir = self.tmp / "env-upstream"
        path = self.write_config(
            "version: 1\ncollector:\n  upstream_data_dir: 'data/upstream'\n"
        )
        config = load_config(path, project_root=self.tmp, env={"FT_DATA_DIR": str(env_dir)})
        self.assertEqual(config.collector.upstream_data_dir, self.tmp / "data" / "upstream")

    def test_env_var_used_when_config_leaves_dir_empty(self):
        env_dir = self.tmp / "env-upstream"
        path = self.write_config("version: 1\ncollector:\n  upstream_data_dir: ''\n")
        config = load_config(path, project_root=self.tmp, env={"FT_DATA_DIR": str(env_dir)})
        self.assertEqual(config.collector.upstream_data_dir, env_dir)

    def test_absent_env_and_config_leaves_dir_unset(self):
        path = self.write_config("version: 1\n")
        config = load_config(path, project_root=self.tmp, env={})
        self.assertIsNone(config.collector.upstream_data_dir)

    def test_executable_args_form_the_command_prefix(self):
        path = self.write_config(
            "version: 1\ncollector:\n  executable: 'python.exe'\n"
            "  executable_args: ['-B', 'stub.py']\n"
        )
        config = load_config(path, project_root=self.tmp, env={})
        self.assertEqual(config.collector.command, ("python.exe", "-B", "stub.py"))

    def test_unsupported_version_raises(self):
        path = self.write_config("version: 2\n")
        with self.assertRaises(ConfigError) as ctx:
            load_config(path, project_root=self.tmp, env={})
        self.assertIn("unsupported config version", str(ctx.exception))

    def test_non_mapping_top_level_raises(self):
        path = self.write_config("- a\n- b\n")
        with self.assertRaises(ConfigError):
            load_config(path, project_root=self.tmp, env={})

    def test_invalid_yaml_raises(self):
        path = self.write_config("version: 1\npaths: [oops\n")
        with self.assertRaises(ConfigError) as ctx:
            load_config(path, project_root=self.tmp, env={})
        self.assertIn("invalid YAML", str(ctx.exception))

    def test_wrong_type_raises(self):
        path = self.write_config(
            "version: 1\ningest:\n  mark_failed_after_attempts: 'three'\n"
        )
        with self.assertRaises(ConfigError) as ctx:
            load_config(path, project_root=self.tmp, env={})
        self.assertIn("mark_failed_after_attempts", str(ctx.exception))

    def test_boolean_must_be_boolean(self):
        path = self.write_config("version: 1\ncollector:\n  read_only: 'yes'\n")
        with self.assertRaises(ConfigError):
            load_config(path, project_root=self.tmp, env={})

    def test_unknown_top_level_keys_are_reported(self):
        path = self.write_config("version: 1\nsurprise: 1\n")
        config = load_config(path, project_root=self.tmp, env={})
        self.assertEqual(config.unknown_keys, ("surprise",))


class HelperTests(ConfigTestCase):
    def test_default_project_root_is_repo_root(self):
        self.assertEqual(default_project_root(), PROJECT_ROOT.resolve())

    def test_resolve_path_helper(self):
        self.assertEqual(
            resolve_path("data", Path("C:/x"), field_name="data"), Path("C:/x/data")
        )
        self.assertEqual(
            resolve_path("C:/abs", Path("C:/x"), field_name="data"), Path("C:/abs")
        )
        with self.assertRaises(ConfigError):
            resolve_path("  ", Path("C:/x"), field_name="data")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
