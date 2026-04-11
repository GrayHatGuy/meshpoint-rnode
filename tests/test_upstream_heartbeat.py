"""Tests for the enriched heartbeat payload in upstream_client.py."""

import unittest

from src.analytics.stats_reporter import StatsReporter
from src.api.upstream_client import UpstreamClient
from src.config import UpstreamConfig
from src.models.device_identity import DeviceIdentity


class TestBuildHeartbeat(unittest.TestCase):
    def setUp(self):
        self.config = UpstreamConfig(
            enabled=True,
            url="wss://test.example.com",
            auth_token="test-token",
        )
        self.identity = DeviceIdentity(device_id="test-device-123")

    def test_heartbeat_without_stats_reporter(self):
        client = UpstreamClient(self.config, self.identity)
        heartbeat = client._build_heartbeat()
        self.assertEqual(heartbeat["type"], "heartbeat")
        self.assertEqual(heartbeat["device_id"], "test-device-123")
        self.assertIn("timestamp", heartbeat)
        self.assertNotIn("stats", heartbeat)
        self.assertNotIn("nodes", heartbeat)

    def test_heartbeat_with_stats_reporter_empty(self):
        reporter = StatsReporter()
        client = UpstreamClient(self.config, self.identity, stats_reporter=reporter)
        heartbeat = client._build_heartbeat()
        self.assertEqual(heartbeat["type"], "heartbeat")
        self.assertIn("stats", heartbeat)
        self.assertEqual(heartbeat["stats"]["total_packets"], 0)
        self.assertEqual(heartbeat["packets_since_last"], 0)
        self.assertNotIn("nodes", heartbeat)

    def test_heartbeat_includes_stats(self):
        reporter = StatsReporter()
        reporter.record_packet("meshtastic", "text", -90.0, 5.0, 3, 3)
        reporter.record_packet("meshcore", "position", -100.0, -2.0, 0, 0)

        client = UpstreamClient(self.config, self.identity, stats_reporter=reporter)
        heartbeat = client._build_heartbeat()

        stats = heartbeat["stats"]
        self.assertEqual(stats["total_packets"], 2)
        self.assertEqual(stats["protocols"]["meshtastic"], 1)
        self.assertEqual(stats["protocols"]["meshcore"], 1)
        self.assertEqual(heartbeat["packets_since_last"], 2)

    def test_heartbeat_includes_nodes(self):
        reporter = StatsReporter()
        reporter.record_node({"node_id": "abc123", "long_name": "TestNode"})

        client = UpstreamClient(self.config, self.identity, stats_reporter=reporter)
        heartbeat = client._build_heartbeat()

        self.assertIn("nodes", heartbeat)
        self.assertEqual(len(heartbeat["nodes"]), 1)
        self.assertEqual(heartbeat["nodes"][0]["node_id"], "abc123")

    def test_heartbeat_no_nodes_key_when_empty(self):
        reporter = StatsReporter()
        client = UpstreamClient(self.config, self.identity, stats_reporter=reporter)
        heartbeat = client._build_heartbeat()
        self.assertNotIn("nodes", heartbeat)

    def test_heartbeat_includes_rssi_histogram(self):
        reporter = StatsReporter()
        reporter.record_packet("meshtastic", "text", -70.0, 5.0, 3, 3)
        reporter.record_packet("meshtastic", "text", -95.0, 3.0, 3, 3)
        reporter.record_packet("meshtastic", "text", -110.0, -1.0, 3, 3)
        reporter.record_packet("meshtastic", "text", -120.0, -5.0, 3, 3)

        client = UpstreamClient(self.config, self.identity, stats_reporter=reporter)
        heartbeat = client._build_heartbeat()

        hist = heartbeat["stats"]["rssi_histogram"]
        self.assertEqual(hist["excellent"], 1)
        self.assertEqual(hist["good"], 1)
        self.assertEqual(hist["fair"], 1)
        self.assertEqual(hist["weak"], 1)

    def test_heartbeat_includes_farthest_direct(self):
        reporter = StatsReporter()
        reporter.record_farthest_direct(
            source_id="far_node",
            rssi=-95.0,
            device_lat=40.0, device_lon=-74.0,
            node_lat=41.0, node_lon=-75.0,
            hop_start=3, hop_limit=3,
        )

        client = UpstreamClient(self.config, self.identity, stats_reporter=reporter)
        heartbeat = client._build_heartbeat()

        fd = heartbeat["stats"]["farthest_direct"]
        self.assertGreater(fd["miles"], 0)
        self.assertEqual(fd["node_id"], "far_node")


class TestHeartbeatResetAfterSend(unittest.TestCase):
    def test_reset_called_on_successful_send(self):
        reporter = StatsReporter()
        reporter.record_packet("meshtastic", "text", -90.0, 5.0, 3, 3)

        config = UpstreamConfig(
            enabled=True,
            url="wss://test.example.com",
            auth_token="test-token",
        )
        identity = DeviceIdentity(device_id="test-device-123")
        UpstreamClient(config, identity, stats_reporter=reporter)

        self.assertEqual(reporter.total_packets, 1)
        reporter.reset()
        self.assertEqual(reporter.total_packets, 0)


if __name__ == "__main__":
    unittest.main()
