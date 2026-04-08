import unittest
from types import SimpleNamespace
from unittest.mock import patch

import analyzer


class _FakeClient:
    def __init__(self, payload: str):
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **kwargs: SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=payload))]
                )
            )
        )


class AnalyzerCryptoTests(unittest.TestCase):
    def _market(self, **overrides) -> dict:
        market = {
            "id": "m1",
            "slug": "btc-updown-5m-123",
            "question": "Bitcoin Up or Down - April 7, 10:30AM-10:35AM ET",
            "outcomes": ["Up", "Down"],
            "yes_price": 0.55,
            "market_implied_up_prob": 0.55,
            "up_outcome_index": 0,
            "end_date": "2026-04-07T14:35:00Z",
            "seconds_to_close": 14,
            "interval_minutes": 5,
            "cycle_phase": "t30",
            "is_crypto_5min": True,
            "liquidity": 9000.0,
            "volume": 1000.0,
            "market_spread": 0.02,
            "best_bid": 0.54,
            "best_ask": 0.56,
            "last_trade_price": 0.55,
        }
        market.update(overrides)
        return market

    @patch("price_feed.get_window_summary")
    def test_crypto_window_llm_uses_underlying_path_and_display_direction(self, mock_summary):
        mock_summary.return_value = {
            "window_start_price": 100.0,
            "window_current_price": 101.0,
            "window_high": 103.0,
            "window_low": 100.0,
            "window_move_pct": 0.01,
            "last60_move_pct": -0.008,
            "last30_move_pct": -0.01,
            "last15_move_pct": -0.006,
            "distance_from_high_pct": -0.0194,
            "distance_from_low_pct": 0.01,
            "pattern": "reversal",
            "data_source": "rtds",
            "completeness": "full",
        }
        client = _FakeClient('{"direction":"DOWN","probability_up":0.31,"confidence":"medium","pattern":"reversal","reasoning":"Late fade into close."}')

        result = analyzer._analyze_crypto_5min(self._market(), client=client)

        self.assertIsNotNone(result)
        self.assertEqual(result["display_direction"], "BUY_DOWN")
        self.assertEqual(result["predicted_direction"], "DOWN")
        self.assertAlmostEqual(result["probability_up"], 0.31, places=6)
        self.assertAlmostEqual(result["claude_prob"], 0.31, places=6)
        self.assertLess(result["edge"], 0)
        self.assertEqual(result["signal_source"], "underlying_window_llm")
        self.assertEqual(result["data_source"], "rtds")

    @patch("price_feed.get_window_summary")
    def test_t45_observe_only_skips_5m_crypto(self, mock_summary):
        mock_summary.return_value = {
            "window_start_price": 100.0,
            "window_current_price": 101.0,
            "window_high": 101.0,
            "window_low": 100.0,
            "window_move_pct": 0.01,
            "last60_move_pct": 0.003,
            "last30_move_pct": 0.002,
            "last15_move_pct": 0.001,
            "distance_from_high_pct": 0.0,
            "distance_from_low_pct": 0.01,
            "pattern": "continuation",
            "data_source": "rtds",
            "completeness": "full",
        }
        client = _FakeClient('{"direction":"UP","probability_up":0.68,"confidence":"medium","pattern":"continuation","reasoning":"Strong close."}')

        analyzer.reset_skip_events()
        results = analyzer.analyze_markets(client, [self._market(cycle_phase="t45")])

        self.assertEqual(results, [])
        self.assertEqual(analyzer.get_skip_summary().get("analysis:observe_only_phase"), 1)

    @patch("price_feed.get_window_summary")
    def test_up_outcome_index_one_maps_buy_up_to_internal_no_side(self, mock_summary):
        mock_summary.return_value = {
            "window_start_price": 100.0,
            "window_current_price": 101.0,
            "window_high": 101.0,
            "window_low": 99.5,
            "window_move_pct": 0.01,
            "last60_move_pct": 0.004,
            "last30_move_pct": 0.003,
            "last15_move_pct": 0.002,
            "distance_from_high_pct": 0.0,
            "distance_from_low_pct": 0.015,
            "pattern": "continuation",
            "data_source": "rtds",
            "completeness": "full",
        }
        client = _FakeClient('{"direction":"UP","probability_up":0.65,"confidence":"medium","pattern":"continuation","reasoning":"Path is still rising."}')

        result = analyzer._analyze_crypto_5min(
            self._market(yes_price=0.60, market_implied_up_prob=0.40, up_outcome_index=1),
            client=client,
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["display_direction"], "BUY_UP")
        self.assertAlmostEqual(result["probability_up"], 0.65, places=6)
        self.assertAlmostEqual(result["claude_prob"], 0.35, places=6)
        self.assertLess(result["edge"], 0)

    @patch("price_feed.get_window_summary")
    def test_no_trade_model_skips_crypto_market(self, mock_summary):
        mock_summary.return_value = {
            "window_start_price": 100.0,
            "window_current_price": 100.01,
            "window_high": 100.05,
            "window_low": 99.98,
            "window_move_pct": 0.0001,
            "last60_move_pct": 0.00002,
            "last30_move_pct": -0.00001,
            "last15_move_pct": 0.00001,
            "distance_from_high_pct": -0.0004,
            "distance_from_low_pct": 0.0003,
            "pattern": "chop",
            "data_source": "rtds",
            "completeness": "full",
        }
        client = _FakeClient('{"direction":"NO_TRADE","probability_up":0.50,"confidence":"low","pattern":"chop","reasoning":"Too noisy."}')

        result = analyzer._analyze_crypto_5min(self._market(), client=client)

        self.assertIsNone(result)

    @patch("price_feed.get_window_summary", return_value=None)
    @patch("price_feed.get_window_move_pct", return_value=0.002)
    def test_missing_window_summary_falls_back_to_legacy_window_move(self, _mock_window_move, _mock_summary):
        result = analyzer._analyze_crypto_5min(self._market(), client=None)

        self.assertIsNotNone(result)
        self.assertEqual(result["signal_source"], "legacy_window_move")
        self.assertEqual(result["display_direction"], "BUY_UP")

    def test_llm_delta_calibration_is_symmetric(self):
        up_prob, up_before, up_after = analyzer._calibrate_llm_probability(
            market_prob=0.50,
            raw_probability=0.70,
            confidence="medium",
            reasoning="YES has momentum, NO looks overextended, YES slightly stronger.",
        )
        down_prob, down_before, down_after = analyzer._calibrate_llm_probability(
            market_prob=0.50,
            raw_probability=0.30,
            confidence="medium",
            reasoning="YES looks overextended, NO has momentum, NO slightly stronger.",
        )

        self.assertAlmostEqual(up_before, 0.20, places=6)
        self.assertAlmostEqual(down_before, -0.20, places=6)
        self.assertAlmostEqual(abs(up_after), abs(down_after), places=6)
        self.assertGreater(up_prob, 0.50)
        self.assertLess(down_prob, 0.50)


if __name__ == "__main__":
    unittest.main()
