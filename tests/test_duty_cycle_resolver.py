"""Tests for ``resolve_max_duty_percent`` and ``MESHPOINT_DUTY_DEFAULTS``.

The resolver lets ``transmit.max_duty_cycle_percent`` default to ``None``
in config and pick a sensible per-region value at runtime. An explicit
user value always overrides.
"""

from __future__ import annotations

import unittest

from src.transmit.duty_cycle import (
    MESHPOINT_DUTY_DEFAULTS,
    resolve_max_duty_percent,
)


class TestResolveMaxDutyPercent(unittest.TestCase):
    def test_explicit_value_wins_over_region_default(self):
        self.assertEqual(resolve_max_duty_percent("US", 5.0), 5.0)
        self.assertEqual(resolve_max_duty_percent("EU_868", 0.5), 0.5)
        self.assertEqual(resolve_max_duty_percent("ANZ", 25.0), 25.0)

    def test_us_default_is_ten_percent(self):
        self.assertEqual(resolve_max_duty_percent("US", None), 10.0)

    def test_eu_default_is_one_percent(self):
        self.assertEqual(resolve_max_duty_percent("EU_868", None), 1.0)

    def test_in_default_is_one_percent(self):
        self.assertEqual(resolve_max_duty_percent("IN", None), 1.0)

    def test_anz_default_is_ten_percent(self):
        self.assertEqual(resolve_max_duty_percent("ANZ", None), 10.0)

    def test_kr_default_is_ten_percent(self):
        self.assertEqual(resolve_max_duty_percent("KR", None), 10.0)

    def test_sg_default_is_ten_percent(self):
        self.assertEqual(resolve_max_duty_percent("SG_923", None), 10.0)

    def test_unknown_region_falls_back_safely(self):
        # 1% is the strictest civilian limit globally, so it's the
        # safe choice when the region tag isn't recognized.
        self.assertEqual(resolve_max_duty_percent("MARS", None), 1.0)
        self.assertEqual(resolve_max_duty_percent("", None), 1.0)

    def test_explicit_zero_is_respected(self):
        # 0.0 is a valid (if absurd) explicit override; the resolver
        # must not treat it as falsy and re-derive.
        self.assertEqual(resolve_max_duty_percent("US", 0.0), 0.0)


class TestMeshpointDutyDefaults(unittest.TestCase):
    def test_covers_all_supported_regions(self):
        from src.cli.setup_wizard import SUPPORTED_REGIONS

        for region in SUPPORTED_REGIONS:
            with self.subTest(region=region):
                self.assertIn(region, MESHPOINT_DUTY_DEFAULTS)

    def test_restricted_regions_match_regulatory_ceiling(self):
        # EU_868 and IN have a 1% regulatory cap, so the Meshpoint
        # default cannot exceed it.
        self.assertEqual(MESHPOINT_DUTY_DEFAULTS["EU_868"], 1.0)
        self.assertEqual(MESHPOINT_DUTY_DEFAULTS["IN"], 1.0)

    def test_unrestricted_regions_well_under_ceiling(self):
        # US/ANZ/KR/SG_923 have no duty cycle rule. The Meshpoint
        # default stays conservative (10%) to be a good neighbor on
        # shared spectrum, well under the 100% regulatory ceiling.
        for region in ("US", "ANZ", "KR", "SG_923"):
            with self.subTest(region=region):
                self.assertEqual(MESHPOINT_DUTY_DEFAULTS[region], 10.0)


if __name__ == "__main__":
    unittest.main()
