"""Tests for CycleMetrics."""

import unittest
from datetime import datetime
from unittest.mock import patch

from src.common.metrics import CycleMetrics


class TestCycleMetrics(unittest.TestCase):
    def test_metrics_initial_values(self):
        metrics = CycleMetrics()
        self.assertEqual(metrics.posts_found, 0)
        self.assertEqual(metrics.posts_sent, 0)
        self.assertEqual(metrics.posts_skipped_processed, 0)
        self.assertEqual(metrics.posts_failed_send, 0)
        self.assertEqual(metrics.posts_no_store_links, 0)
        self.assertEqual(metrics.posts_no_steam_link, 0)
        self.assertEqual(metrics.posts_no_image, 0)
        self.assertIsInstance(metrics.cycle_start, datetime)

    def test_metrics_log_summary(self):
        metrics = CycleMetrics()
        metrics.posts_found = 10
        metrics.posts_sent = 7
        metrics.posts_skipped_processed = 2
        metrics.posts_failed_send = 1
        metrics.posts_no_store_links = 3
        metrics.posts_no_steam_link = 1
        metrics.posts_no_image = 2

        with patch("src.common.metrics.logger") as mock_logger:
            metrics.log_summary()
            mock_logger.info.assert_called_once()
            call_args = mock_logger.info.call_args
            # Verify format string and key values are present
            format_str = call_args[0][0]
            assert "Cycle summary" in format_str
            args = call_args[0][1:]
            self.assertEqual(args[0], 10)   # found
            self.assertEqual(args[1], 7)    # sent
            self.assertEqual(args[2], 2)    # skipped
            self.assertEqual(args[3], 1)    # failed
            self.assertEqual(args[4], 3)    # no_stores
            self.assertEqual(args[5], 1)    # no_steam
            self.assertEqual(args[6], 2)    # no_image

    def test_metrics_duration_positive(self):
        metrics = CycleMetrics()
        with patch("src.common.metrics.logger") as mock_logger:
            metrics.log_summary()
            args = mock_logger.info.call_args[0]
            duration = args[-1]  # last positional arg is duration
            self.assertGreaterEqual(duration, 0.0)


if __name__ == "__main__":
    unittest.main()
