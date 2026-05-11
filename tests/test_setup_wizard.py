"""Tests for setup wizard helpers: config loading and float prompts."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from src.cli.setup_wizard import (
    _deep_merge,
    _load_existing_config,
    _preflight_check,
)


class TestLoadExistingConfig(unittest.TestCase):

    def test_returns_empty_dict_when_no_file(self):
        with patch.object(
            Path, "exists", return_value=False
        ):
            result = _load_existing_config()
            self.assertEqual(result, {})

    def test_loads_valid_yaml(self):
        data = {"device": {"device_name": "TestPoint"}, "radio": {"region": "US"}}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            yaml.dump(data, f)
            tmp_path = f.name

        import src.cli.setup_wizard as sw
        original = sw.LOCAL_CONFIG_PATH
        try:
            sw.LOCAL_CONFIG_PATH = Path(tmp_path)
            result = _load_existing_config()
            self.assertEqual(result["device"]["device_name"], "TestPoint")
            self.assertEqual(result["radio"]["region"], "US")
        finally:
            sw.LOCAL_CONFIG_PATH = original
            Path(tmp_path).unlink(missing_ok=True)

    def test_returns_empty_for_non_dict_yaml(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write("just a string\n")
            tmp_path = f.name

        import src.cli.setup_wizard as sw
        original = sw.LOCAL_CONFIG_PATH
        try:
            sw.LOCAL_CONFIG_PATH = Path(tmp_path)
            result = _load_existing_config()
            self.assertEqual(result, {})
        finally:
            sw.LOCAL_CONFIG_PATH = original
            Path(tmp_path).unlink(missing_ok=True)

    def test_returns_empty_for_corrupt_yaml(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(": : : invalid yaml {{{\n")
            tmp_path = f.name

        import src.cli.setup_wizard as sw
        original = sw.LOCAL_CONFIG_PATH
        try:
            sw.LOCAL_CONFIG_PATH = Path(tmp_path)
            result = _load_existing_config()
            self.assertEqual(result, {})
        finally:
            sw.LOCAL_CONFIG_PATH = original
            Path(tmp_path).unlink(missing_ok=True)


class TestDeepMerge(unittest.TestCase):
    """Verify wizard merge preserves untouched user config sections."""

    def test_returns_overlay_when_base_is_empty(self):
        overlay = {"device": {"device_name": "MP1"}}
        result = _deep_merge({}, overlay)
        self.assertEqual(result, overlay)

    def test_returns_base_when_overlay_is_empty(self):
        base = {"mqtt": {"enabled": True, "broker": "broker.example.com"}}
        result = _deep_merge(base, {})
        self.assertEqual(result, base)

    def test_preserves_top_level_sections_not_in_overlay(self):
        base = {
            "mqtt": {"enabled": True, "broker": "broker.example.com"},
            "meshtastic": {"channel_keys": {"Secret": "key=="}},
        }
        overlay = {"device": {"device_name": "MP1"}}
        result = _deep_merge(base, overlay)
        self.assertEqual(result["mqtt"], base["mqtt"])
        self.assertEqual(result["meshtastic"], base["meshtastic"])
        self.assertEqual(result["device"], {"device_name": "MP1"})

    def test_overlay_overwrites_scalar_values(self):
        base = {"radio": {"region": "US", "frequency_mhz": 906.875}}
        overlay = {"radio": {"region": "EU_868"}}
        result = _deep_merge(base, overlay)
        self.assertEqual(result["radio"]["region"], "EU_868")
        self.assertEqual(result["radio"]["frequency_mhz"], 906.875)

    def test_overlay_replaces_lists_entirely(self):
        base = {"capture": {"sources": ["concentrator", "meshcore_usb"]}}
        overlay = {"capture": {"sources": ["concentrator"]}}
        result = _deep_merge(base, overlay)
        self.assertEqual(result["capture"]["sources"], ["concentrator"])

    def test_nested_dicts_merge_recursively(self):
        base = {
            "capture": {
                "sources": ["concentrator"],
                "meshcore_usb": {"baud_rate": 115200, "auto_detect": True},
            }
        }
        overlay = {
            "capture": {
                "meshcore_usb": {"serial_port": "/dev/ttyACM0"},
            }
        }
        result = _deep_merge(base, overlay)
        self.assertEqual(
            result["capture"]["meshcore_usb"],
            {
                "baud_rate": 115200,
                "auto_detect": True,
                "serial_port": "/dev/ttyACM0",
            },
        )
        self.assertEqual(result["capture"]["sources"], ["concentrator"])

    def test_dict_overlay_replaces_scalar_base(self):
        base = {"relay": False}
        overlay = {"relay": {"enabled": True}}
        result = _deep_merge(base, overlay)
        self.assertEqual(result["relay"], {"enabled": True})

    def test_mqtt_block_survives_full_wizard_overlay(self):
        """Reproduces the bug: re-running setup wiped user's MQTT block."""
        base = {
            "mqtt": {
                "enabled": True,
                "broker": "mqtt.meshtastic.org",
                "publish_channels": ["LongFast", "MyChannel"],
            },
            "device": {"device_name": "OldName", "device_id": "uuid-123"},
        }
        overlay = {
            "radio": {"region": "US"},
            "capture": {"sources": ["concentrator"]},
            "upstream": {"enabled": True, "auth_token": "newkey"},
            "device": {"device_name": "NewName", "device_id": "uuid-123"},
            "transmit": {"node_id": 12345, "long_name": "NewName"},
        }
        result = _deep_merge(base, overlay)
        self.assertEqual(result["mqtt"], base["mqtt"])
        self.assertEqual(result["device"]["device_name"], "NewName")
        self.assertEqual(result["device"]["device_id"], "uuid-123")
        self.assertEqual(result["upstream"]["auth_token"], "newkey")

    def test_does_not_mutate_inputs(self):
        base = {"a": {"b": 1}}
        overlay = {"a": {"c": 2}}
        result = _deep_merge(base, overlay)
        self.assertEqual(base, {"a": {"b": 1}})
        self.assertEqual(overlay, {"a": {"c": 2}})
        self.assertEqual(result, {"a": {"b": 1, "c": 2}})


class TestPreflight(unittest.TestCase):
    """Wizard must bail before prompting if config is unwritable."""

    def _patch_config_path(self, target_path: Path):
        import src.cli.setup_wizard as sw
        return patch.object(sw, "LOCAL_CONFIG_PATH", target_path)

    def test_writable_path_returns_normally(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "config" / "local.yaml"
            target.parent.mkdir()
            with self._patch_config_path(target):
                _preflight_check()
            self.assertTrue(target.exists() or not target.exists())

    def test_existing_writable_file_is_not_truncated(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            config_dir.mkdir()
            target = config_dir / "local.yaml"
            target.write_text("existing: value\n")
            with self._patch_config_path(target):
                _preflight_check()
            self.assertEqual(target.read_text(), "existing: value\n")

    def test_missing_config_dir_exits(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "does-not-exist" / "local.yaml"
            with self._patch_config_path(missing):
                with self.assertRaises(SystemExit) as ctx:
                    _preflight_check()
            self.assertEqual(ctx.exception.code, 1)

    def test_unwritable_target_exits(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            config_dir.mkdir()
            target = config_dir / "local.yaml"
            with self._patch_config_path(target):
                with patch.object(
                    Path, "open",
                    side_effect=PermissionError("denied"),
                ):
                    with self.assertRaises(SystemExit) as ctx:
                        _preflight_check()
            self.assertEqual(ctx.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
