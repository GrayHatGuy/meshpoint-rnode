"""Tests for the meshpoint meshcore-radio CLI helpers."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from src.cli import meshcore_radio_command as mrc


class TestEnableAutoDetect(unittest.TestCase):
    """The post-reconfig path should never pin a transient ACM number."""

    def setUp(self) -> None:
        import tempfile

        self._tmpdir = tempfile.TemporaryDirectory()
        self.cfg_path = Path(self._tmpdir.name) / "local.yaml"
        self._patcher = patch.object(mrc, "_LOCAL_CONFIG_PATH", self.cfg_path)
        self._patcher.start()

    def tearDown(self) -> None:
        self._patcher.stop()
        self._tmpdir.cleanup()

    def _read(self) -> dict:
        with open(self.cfg_path) as fh:
            return yaml.safe_load(fh) or {}

    def test_pinned_port_gets_unpinned_and_auto_detect_enabled(self):
        self.cfg_path.write_text(yaml.safe_dump({
            "capture": {
                "meshcore_usb": {
                    "auto_detect": False,
                    "serial_port": "/dev/ttyACM0",
                },
            },
        }))

        mrc._enable_auto_detect()

        result = self._read()
        mc = result["capture"]["meshcore_usb"]
        self.assertTrue(mc["auto_detect"])
        self.assertNotIn("serial_port", mc)

    def test_already_auto_detect_no_pinned_port_is_noop(self):
        original = {
            "capture": {
                "meshcore_usb": {
                    "auto_detect": True,
                },
            },
        }
        self.cfg_path.write_text(yaml.safe_dump(original))
        mtime_before = self.cfg_path.stat().st_mtime

        mrc._enable_auto_detect()

        # File should not have been rewritten when nothing needs to change.
        self.assertEqual(self.cfg_path.stat().st_mtime, mtime_before)

    def test_missing_config_file_is_safe(self):
        self.assertFalse(self.cfg_path.exists())
        mrc._enable_auto_detect()
        self.assertFalse(self.cfg_path.exists())

    def test_other_config_keys_preserved(self):
        self.cfg_path.write_text(yaml.safe_dump({
            "device": {"name": "RAK-test"},
            "capture": {
                "sources": ["concentrator", "meshcore_usb"],
                "meshcore_usb": {
                    "auto_detect": False,
                    "serial_port": "/dev/ttyACM5",
                    "baud_rate": 115200,
                },
            },
        }))

        mrc._enable_auto_detect()

        result = self._read()
        self.assertEqual(result["device"]["name"], "RAK-test")
        self.assertIn("concentrator", result["capture"]["sources"])
        self.assertIn("meshcore_usb", result["capture"]["sources"])
        mc = result["capture"]["meshcore_usb"]
        self.assertTrue(mc["auto_detect"])
        self.assertEqual(mc["baud_rate"], 115200)
        self.assertNotIn("serial_port", mc)


if __name__ == "__main__":
    unittest.main()
