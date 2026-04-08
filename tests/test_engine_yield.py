import unittest
from unittest.mock import patch

import engine


class EngineYieldTests(unittest.TestCase):
    def _analysis(
        self,
        market_id: str,
        edge: float,
        confidence: str = "medium",
        seconds_to_close: int = 30,
        liquidity: float = 15000.0,
        signal_source: str = "llm",
        is_crypto: bool = False,
        interval_minutes: int | None = None,
    ) -> dict:
        return {
            "market_id": market_id,
            "question": f"Q-{market_id}",
            "market_prob": 0.5,
            "claude_prob": 0.5 + edge,
            "edge": edge,
            "confidence": confidence,
            "is_crypto_5min": is_crypto,
            "seconds_to_close": seconds_to_close,
            "interval_minutes": interval_minutes,
            "liquidity": liquidity,
            "signal_source": signal_source,
            "cycle_phase": "t30" if is_crypto and interval_minutes == 5 else None,
            "display_direction": ("BUY_UP" if edge > 0 else "BUY_DOWN") if is_crypto else ("BUY_YES" if edge > 0 else "BUY_NO"),
            "reasoning": "test",
        }

    @patch("bankroll.get_progress", return_value={"drawdown": 0.0})
    @patch("bankroll.get_balance", return_value=10.0)
    def test_top_n_and_tiering(self, _mock_balance, _mock_progress):
        analyses = [
            self._analysis("m1", edge=0.08, confidence="high", seconds_to_close=15, signal_source="price+momentum", is_crypto=True, interval_minutes=5),
            self._analysis("m2", edge=0.05, confidence="medium", seconds_to_close=30, signal_source="llm"),
            self._analysis("m3", edge=0.03, confidence="medium", seconds_to_close=50, signal_source="llm"),
        ]
        trades = engine.evaluate_trades(analyses, existing_pending_trades=[], bucket_stats={})
        self.assertLessEqual(len(trades), 3)  # TOP_TRADES_PER_CYCLE default
        self.assertGreaterEqual(len(trades), 1)
        self.assertIn("trade_score", trades[0])
        self.assertIn("quality_tier", trades[0])
        self.assertIn(trades[0]["quality_tier"], {"A", "B"})

    @patch("bankroll.get_balance", return_value=10.0)
    def test_drawdown_multiplier_reduces_bet(self, _mock_balance):
        a = self._analysis(
            "m1",
            edge=0.08,
            confidence="high",
            seconds_to_close=15,
            signal_source="price+momentum",
            is_crypto=True,
            interval_minutes=5,
        )

        with patch("bankroll.get_progress", return_value={"drawdown": 0.0}):
            trades_normal = engine.evaluate_trades([a], existing_pending_trades=[], bucket_stats={})
        with patch("bankroll.get_progress", return_value={"drawdown": -0.15}):
            trades_dd = engine.evaluate_trades([a], existing_pending_trades=[], bucket_stats={})

        self.assertEqual(len(trades_normal), 1)
        self.assertEqual(len(trades_dd), 1)
        self.assertLess(trades_dd[0]["bet_size"], trades_normal[0]["bet_size"])

    @patch("bankroll.get_progress", return_value={"drawdown": 0.0})
    @patch("bankroll.get_balance", return_value=10.0)
    def test_auto_disable_negative_bucket(self, _mock_balance, _mock_progress):
        a = self._analysis(
            "m1",
            edge=0.08,
            confidence="high",
            seconds_to_close=15,
            signal_source="price+momentum",
            is_crypto=True,
            interval_minutes=5,
        )
        # Expected tier is A for this score profile.
        bucket = "price+momentum|5|A"
        stats = {bucket: {"count": 25, "pnl": -2.5}}
        trades = engine.evaluate_trades([a], existing_pending_trades=[], bucket_stats=stats)
        self.assertEqual(len(trades), 0)

    @patch("bankroll.get_progress", return_value={"drawdown": 0.0})
    @patch("bankroll.get_balance", return_value=10.0)
    def test_late_reentry_requires_signal_improvement(self, _mock_balance, _mock_progress):
        pending = [{
            "id": "parent-1",
            "market_id": "m1",
            "edge": "0.03",
            "status": "PENDING",
        }]
        weak_improve = self._analysis(
            "m1",
            edge=0.04,  # +0.01 improvement < MIN_SIGNAL_IMPROVEMENT (0.03)
            confidence="high",
            seconds_to_close=15,
            signal_source="price+momentum",
            is_crypto=True,
            interval_minutes=5,
        )
        strong_improve = self._analysis(
            "m1",
            edge=0.06,  # +0.03 improvement >= MIN_SIGNAL_IMPROVEMENT
            confidence="high",
            seconds_to_close=15,
            signal_source="price+momentum",
            is_crypto=True,
            interval_minutes=5,
        )
        trades_weak = engine.evaluate_trades([weak_improve], existing_pending_trades=pending, bucket_stats={})
        trades_strong = engine.evaluate_trades([strong_improve], existing_pending_trades=pending, bucket_stats={})
        self.assertEqual(len(trades_weak), 0)
        self.assertEqual(len(trades_strong), 1)
        self.assertEqual(trades_strong[0]["reentry_parent_trade_id"], "parent-1")

    @patch("bankroll.get_progress", return_value={"drawdown": 0.0})
    @patch("bankroll.get_balance", return_value=10.0)
    def test_side_concentration_penalizes_same_direction(self, _mock_balance, _mock_progress):
        all_trades = [
            {"direction": "BUY_UP"} for _ in range(8)
        ] + [
            {"direction": "BUY_DOWN"} for _ in range(2)
        ]
        analyses = [
            self._analysis("yes-market", edge=0.08, confidence="high", signal_source="underlying_window_llm", is_crypto=True, interval_minutes=5),
            self._analysis("no-market", edge=-0.08, confidence="high", signal_source="underlying_window_llm", is_crypto=True, interval_minutes=5),
        ]

        trades = engine.evaluate_trades(
            analyses,
            existing_pending_trades=[],
            bucket_stats={},
            all_trades=all_trades,
            current_cycle=20,
        )

        self.assertEqual(len(trades), 2)
        yes_trade = next(t for t in trades if t["direction"] == "BUY_YES")
        no_trade = next(t for t in trades if t["direction"] == "BUY_NO")
        self.assertTrue(yes_trade["side_concentration_penalty_applied"])
        self.assertFalse(no_trade["side_concentration_penalty_applied"])
        self.assertLess(yes_trade["trade_score"], no_trade["trade_score"])

    @patch("bankroll.get_progress", return_value={"drawdown": 0.0})
    @patch("bankroll.get_balance", return_value=10.0)
    def test_short_horizon_direction_bucket_disable_blocks_bleeding_bucket(self, _mock_balance, _mock_progress):
        analysis = self._analysis(
            "m-lossy",
            edge=0.08,
            confidence="high",
            seconds_to_close=15,
            signal_source="llm",
        )
        all_trades = [
            {
                "cycle": "4",
                "status": "LOST",
                "direction_bucket": "llm|na|BUY_YES|A",
                "direction": "BUY_YES",
            },
            {
                "cycle": "5",
                "status": "LOST",
                "direction_bucket": "llm|na|BUY_YES|A",
                "direction": "BUY_YES",
            },
            {
                "cycle": "6",
                "status": "LOST",
                "direction_bucket": "llm|na|BUY_YES|A",
                "direction": "BUY_YES",
            },
        ]

        trades = engine.evaluate_trades(
            [analysis],
            existing_pending_trades=[],
            bucket_stats={},
            direction_bucket_stats={},
            all_trades=all_trades,
            current_cycle=10,
        )

        self.assertEqual(trades, [])

    @patch("bankroll.get_progress", return_value={"drawdown": 0.0})
    @patch("bankroll.get_balance", return_value=10.0)
    def test_crypto_uses_tighter_tier_multiplier(self, _mock_balance, _mock_progress):
        analysis = self._analysis(
            "m-crypto",
            edge=0.05,
            confidence="medium",
            seconds_to_close=20,
            liquidity=15000.0,
            signal_source="momentum+net_move_fallback",
            is_crypto=True,
            interval_minutes=5,
        )

        trades = engine.evaluate_trades(
            [analysis],
            existing_pending_trades=[],
            bucket_stats={},
            all_trades=[],
            current_cycle=30,
        )

        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["quality_tier"], "B")
        self.assertAlmostEqual(trades[0]["tier_size_multiplier"], 0.55, places=6)

    @patch("bankroll.get_progress", return_value={"drawdown": 0.0})
    @patch("bankroll.get_balance", return_value=10.0)
    def test_crypto_tail_market_uses_lower_edge_threshold(self, _mock_balance, _mock_progress):
        analysis = {
            **self._analysis(
                "m-tail",
                edge=-0.01,
                confidence="medium",
                seconds_to_close=14,
                signal_source="market_tail_continuation",
                is_crypto=True,
                interval_minutes=5,
            ),
            "market_prob": 0.015,
            "claude_prob": 0.005,
        }

        trades = engine.evaluate_trades(
            [analysis],
            existing_pending_trades=[],
            bucket_stats={},
            all_trades=[],
            current_cycle=50,
        )

        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["direction"], "BUY_NO")

    @patch("bankroll.get_progress", return_value={"drawdown": 0.0})
    @patch("bankroll.get_balance", return_value=10.0)
    def test_extreme_crypto_tail_uses_tail_tier_and_lower_ev_floor(self, _mock_balance, _mock_progress):
        analysis = {
            **self._analysis(
                "m-tail-yes",
                edge=0.01,
                confidence="medium",
                seconds_to_close=14,
                liquidity=9000.0,
                signal_source="window_move",
                is_crypto=True,
                interval_minutes=5,
            ),
            "market_prob": 0.98,
            "claude_prob": 0.99,
        }

        trades = engine.evaluate_trades(
            [analysis],
            existing_pending_trades=[],
            bucket_stats={},
            all_trades=[],
            current_cycle=51,
        )

        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["quality_tier"], "B")
        self.assertEqual(trades[0]["direction"], "BUY_YES")

    @patch("bankroll.get_progress", return_value={"drawdown": 0.0})
    @patch("bankroll.get_balance", return_value=10.0)
    def test_general_crypto_market_uses_lower_crypto_edge_threshold(self, _mock_balance, _mock_progress):
        analysis = {
            **self._analysis(
                "m-crypto-edge",
                edge=0.015,
                confidence="high",
                seconds_to_close=5,
                liquidity=20000.0,
                signal_source="price+momentum",
                is_crypto=True,
                interval_minutes=5,
            ),
            "market_prob": 0.26,
            "claude_prob": 0.275,
        }

        trades = engine.evaluate_trades(
            [analysis],
            existing_pending_trades=[],
            bucket_stats={},
            all_trades=[],
            current_cycle=52,
        )

        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["direction"], "BUY_YES")

    @patch("bankroll.get_progress", return_value={"drawdown": 0.0})
    @patch("bankroll.get_balance", return_value=10.0)
    def test_crypto_same_side_stacking_is_limited(self, _mock_balance, _mock_progress):
        analyses = [
            self._analysis(
                "btc",
                edge=0.08,
                confidence="high",
                seconds_to_close=12,
                signal_source="price+momentum",
                is_crypto=True,
                interval_minutes=5,
            ),
            self._analysis(
                "eth",
                edge=0.07,
                confidence="high",
                seconds_to_close=12,
                signal_source="price+momentum",
                is_crypto=True,
                interval_minutes=5,
            ),
        ]

        trades = engine.evaluate_trades(
            analyses,
            existing_pending_trades=[],
            bucket_stats={},
            all_trades=[],
            current_cycle=40,
        )

        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["direction"], "BUY_YES")

    @patch("bankroll.get_progress", return_value={"drawdown": 0.0})
    @patch("bankroll.get_balance", return_value=10.0)
    def test_crypto_opposite_sides_can_both_trade(self, _mock_balance, _mock_progress):
        analyses = [
            self._analysis(
                "btc",
                edge=0.08,
                confidence="high",
                seconds_to_close=12,
                signal_source="price+momentum",
                is_crypto=True,
                interval_minutes=5,
            ),
            self._analysis(
                "eth",
                edge=-0.08,
                confidence="high",
                seconds_to_close=12,
                signal_source="price+momentum",
                is_crypto=True,
                interval_minutes=5,
            ),
        ]

        trades = engine.evaluate_trades(
            analyses,
            existing_pending_trades=[],
            bucket_stats={},
            all_trades=[],
            current_cycle=41,
        )

        self.assertEqual(len(trades), 2)
        self.assertEqual({t["direction"] for t in trades}, {"BUY_YES", "BUY_NO"})


if __name__ == "__main__":
    unittest.main()
