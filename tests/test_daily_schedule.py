import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from daily_schedule import next_check_delay


class DailyScheduleChecks(unittest.TestCase):
    def test_last_ten_seconds_wait_for_midnight_not_another_minute(self):
        self.assertEqual(next_check_delay(1000, now=990), 10)

    def test_normal_day_keeps_periodic_checks(self):
        self.assertEqual(next_check_delay(86400, now=1000), 60)

    def test_waking_after_midnight_checks_immediately(self):
        self.assertEqual(next_check_delay(1000, now=1200), 0)
