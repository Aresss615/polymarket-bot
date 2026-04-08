import datetime
import unittest

import main


class MainScheduleTests(unittest.TestCase):
    def test_next_cycle_prefers_t45_when_before_first_phase(self):
        # At 12:04:10, T-45 wake (12:04:15) is 5s away
        now = datetime.datetime(2026, 4, 8, 12, 4, 10)

        wait, phase, boundary = main.next_cycle_schedule(now)

        self.assertEqual(phase, "t45")
        self.assertEqual(boundary, datetime.datetime(2026, 4, 8, 12, 5, 0))
        self.assertAlmostEqual(wait, 5.0, places=3)

    def test_next_cycle_uses_t30_for_same_boundary(self):
        # At 12:04:20, T-45 has passed; T-30 wake (12:04:30) is 10s away
        now = datetime.datetime(2026, 4, 8, 12, 4, 20)

        wait, phase, boundary = main.next_cycle_schedule(now)

        self.assertEqual(phase, "t30")
        self.assertEqual(boundary, datetime.datetime(2026, 4, 8, 12, 5, 0))
        self.assertAlmostEqual(wait, 10.0, places=3)

    def test_next_cycle_rolls_forward_after_t30_passes(self):
        # At 12:04:40, both T-45 and T-30 for 12:05 have passed; next is T-45 for 12:10
        now = datetime.datetime(2026, 4, 8, 12, 4, 40)

        wait, phase, boundary = main.next_cycle_schedule(now)

        self.assertEqual(phase, "t45")
        self.assertEqual(boundary, datetime.datetime(2026, 4, 8, 12, 10, 0))
        self.assertAlmostEqual(wait, 275.0, places=3)


if __name__ == "__main__":
    unittest.main()
