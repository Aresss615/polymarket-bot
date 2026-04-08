import unittest
from datetime import datetime, timezone

import price_feed


class PriceFeedWindowTests(unittest.TestCase):
    def setUp(self):
        price_feed.clear_price_buffers()

    def tearDown(self):
        price_feed.clear_price_buffers()

    def test_stream_window_summary_detects_late_reversal(self):
        samples = [
            ("2026-04-07T12:25:00+00:00", 100.0),
            ("2026-04-07T12:26:00+00:00", 101.0),
            ("2026-04-07T12:27:00+00:00", 102.0),
            ("2026-04-07T12:28:45+00:00", 103.0),
            ("2026-04-07T12:29:15+00:00", 102.0),
            ("2026-04-07T12:29:30+00:00", 101.5),
            ("2026-04-07T12:29:45+00:00", 101.0),
        ]
        for iso_ts, price in samples:
            ts_ms = int(datetime.fromisoformat(iso_ts).timestamp() * 1000)
            price_feed.record_price_sample("BTC", price, ts_ms)

        window_start = datetime(2026, 4, 7, 12, 25, 0, tzinfo=timezone.utc)
        current_time = datetime(2026, 4, 7, 12, 29, 45, tzinfo=timezone.utc)
        summary = price_feed.get_window_summary("BTC", window_start=window_start, current_time=current_time)

        self.assertIsNotNone(summary)
        self.assertAlmostEqual(summary["window_start_price"], 100.0, places=6)
        self.assertAlmostEqual(summary["window_current_price"], 101.0, places=6)
        self.assertAlmostEqual(summary["window_high"], 103.0, places=6)
        self.assertAlmostEqual(summary["window_move_pct"], 0.01, places=6)
        self.assertLess(summary["last30_move_pct"], 0.0)
        self.assertLess(summary["last15_move_pct"], 0.0)
        self.assertEqual(summary["pattern"], "reversal")
        self.assertEqual(summary["data_source"], "rtds")


if __name__ == "__main__":
    unittest.main()
