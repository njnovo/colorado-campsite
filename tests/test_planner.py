"""Booking-day planner tests. Run with: python3 -m unittest discover -s tests"""
import unittest
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from campfinder import planner, search, store
from campfinder.adapters.base import Campsite
from campfinder.planner import Rule
from test_campfinder import make_campground, memory_db

ET = ZoneInfo("America/New_York")
MT = ZoneInfo("America/Denver")
RECGOV = Rule("recgov", "*", "rolling_months", 6, time(10), "America/New_York", "each_night")
DAYS_180 = Rule("larimer", "*", "rolling_days", 180, None, "America/Denver", "arrival")
FCFS = Rule("recgov", "x", "fcfs")
NOW = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)


class OpeningTimeTest(unittest.TestCase):
    def test_mid_month(self):
        opens = planner.opening_time(date(2027, 8, 14), RECGOV)
        self.assertEqual(opens, datetime(2027, 2, 14, 10, tzinfo=ET))
        self.assertEqual(opens.astimezone(MT).hour, 8)
        self.assertEqual(planner.friendly(opens), "Sun, Feb 14, 2027 at 8:00 AM (Mountain Time)")

    def test_end_of_month_clamps(self):
        # No Feb 29-31 in 2027: Aug 29, 30 and 31 all open on Feb 28.
        for day in (28, 29, 30, 31):
            self.assertEqual(planner.opening_date(date(2027, 8, day), RECGOV), date(2027, 2, 28))

    def test_leap_year(self):
        self.assertEqual(planner.opening_date(date(2028, 8, 29), RECGOV), date(2028, 2, 29))
        self.assertEqual(planner.opening_date(date(2028, 8, 31), RECGOV), date(2028, 2, 29))
        self.assertEqual(planner.opening_date(date(2027, 8, 29), RECGOV), date(2027, 2, 28))

    def test_march_and_december(self):
        self.assertEqual(planner.opening_date(date(2027, 3, 31), RECGOV), date(2026, 9, 30))
        self.assertEqual(planner.opening_date(date(2027, 3, 30), RECGOV), date(2026, 9, 30))
        self.assertEqual(planner.opening_date(date(2027, 3, 29), RECGOV), date(2026, 9, 29))
        self.assertEqual(planner.opening_date(date(2027, 12, 31), RECGOV), date(2027, 6, 30))
        self.assertEqual(planner.opening_date(date(2027, 1, 15), RECGOV), date(2026, 7, 15))

    def test_dst(self):
        # DST starts Sun Mar 14, 2027; opening Mar 15 is 10:00 EDT = 14:00 UTC = 8:00 MDT.
        opens = planner.opening_time(date(2027, 9, 15), RECGOV)
        self.assertEqual(opens.astimezone(timezone.utc).hour, 14)
        self.assertEqual(opens.astimezone(MT).hour, 8)
        # DST ends Sun Nov 1, 2026; opening Nov 2 is 10:00 EST = 15:00 UTC = 8:00 MST.
        opens = planner.opening_time(date(2027, 5, 2), RECGOV)
        self.assertEqual(opens.astimezone(timezone.utc).hour, 15)
        self.assertEqual(opens.astimezone(MT).hour, 8)

    def test_rolling_days(self):
        self.assertEqual(planner.opening_date(date(2027, 8, 14), DAYS_180), date(2027, 2, 15))
        self.assertNotEqual(planner.opening_date(date(2027, 8, 14), DAYS_180),
                            planner.opening_date(date(2027, 8, 14), RECGOV))

    def test_fcfs_and_lottery(self):
        self.assertIsNone(planner.opening_time(date(2027, 8, 14), FCFS))
        stay = planner.stay_opening(date(2027, 8, 14), date(2027, 8, 16), FCFS, NOW)
        self.assertEqual(stay["status"], "no_reservations")
        lottery = Rule("x", "*", "lottery")
        self.assertEqual(planner.stay_opening(date(2027, 8, 14), date(2027, 8, 16), lottery, NOW)["status"],
                         "lottery")

    def test_fixed_date(self):
        rule = Rule("x", "*", "fixed_date", opens_on=date(2027, 3, 1), release_time=time(9))
        self.assertEqual(planner.opening_date(date(2027, 7, 4), rule), date(2027, 3, 1))


class StayOpeningTest(unittest.TestCase):
    def test_already_open(self):
        stay = planner.stay_opening(date(2026, 11, 1), date(2026, 11, 3), RECGOV, NOW)
        self.assertEqual(stay["status"], "open")
        self.assertEqual(stay["seconds_until"], 0)

    def test_too_far_out_still_works(self):
        stay = planner.stay_opening(date(2028, 7, 4), date(2028, 7, 6), RECGOV, NOW)
        self.assertEqual(stay["status"], "upcoming")
        self.assertTrue(stay["opens_at_text"].startswith("Tue, Jan 4, 2028"))

    def test_each_night_reports_last_night(self):
        stay = planner.stay_opening(date(2027, 8, 30), date(2027, 9, 2), RECGOV, NOW)
        self.assertEqual(stay["opens_at"][:10], "2027-02-28")
        self.assertEqual(stay["full_stay_opens_at"][:10], "2027-03-01")  # night of Sep 1

    def test_arrival_basis_has_one_time(self):
        stay = planner.stay_opening(date(2027, 8, 14), date(2027, 8, 20), DAYS_180, NOW)
        self.assertIsNone(stay["full_stay_opens_at"])
        self.assertFalse(stay["time_known"])
        self.assertEqual(stay["opens_at_text"], "Mon, Feb 15, 2027")

    def test_bad_dates(self):
        with self.assertRaises(search.SearchError):
            planner.stay_opening(date(2027, 8, 14), date(2027, 8, 14), RECGOV, NOW)


class RulesTest(unittest.TestCase):
    def test_csv_loads_and_matches(self):
        rules = planner.load_rules()
        moraine = planner.rule_for("recgov", "232463", rules=rules)
        self.assertFalse(moraine.is_default)
        self.assertEqual(planner.rule_for("recgov", "10317461", rules=rules).window_type, "fcfs")
        other = planner.rule_for("recgov", "999", rules=rules)
        self.assertTrue(other.is_default)
        self.assertEqual(other.window_amount, 6)
        self.assertEqual(planner.rule_for("larimer", "whatever", rules=rules).window_type, "rolling_days")
        self.assertIsNone(planner.rule_for("nowhere", "1", rules=rules))
        self.assertEqual(planner.rule_for("recgov", "999", reservable=False, rules=rules).window_type, "fcfs")


class BackupsTest(unittest.TestCase):
    def setUp(self):
        self.conn = memory_db()
        self.rules = {("recgov", "*"): RECGOV, ("larimer", "*"): DAYS_180}
        tent = [Campsite("t", "T", type="tent")]
        rv = [Campsite("r", "R", type="rv")]
        add = lambda cg: store.upsert_campground(self.conn, cg)
        self.origin = add(make_campground("home", 40.0, -105.3, sites=tent))
        self.near = add(make_campground("near", 40.05, -105.3, sites=tent))
        self.rv_only = add(make_campground("rvonly", 40.02, -105.3, sites=rv))
        self.state = add(make_campground("state", 40.1, -105.3, sites=[], source="larimer"))
        self.far = add(make_campground("far", 41.0, -105.3, sites=tent))
        self.walkup = add(make_campground("walkup", 40.03, -105.3, sites=tent, reservable=False))
        self.nocoords = add(make_campground("nocoords", None, None, sites=tent))

    def ids(self, results):
        return [r["id"] for r in results]

    def test_backups(self):
        got = planner.backups(self.conn, self.origin, date(2027, 8, 14), date(2027, 8, 16),
                              now=NOW, rules=self.rules)
        self.assertEqual(self.ids(got), [self.near, self.state])  # sorted by distance
        self.assertEqual(got[0]["compared_to_first_choice"], "same")
        self.assertEqual(got[1]["compared_to_first_choice"], "later")  # 180 days opens a day later
        self.assertFalse(got[1]["site_types_known"])

    def test_no_coordinates(self):
        self.assertEqual(planner.backups(self.conn, self.nocoords, date(2027, 8, 14), date(2027, 8, 16),
                                         now=NOW, rules=self.rules), [])

    def test_plan(self):
        p = planner.plan(self.conn, self.origin, date(2027, 8, 14), date(2027, 8, 16), now=NOW, rules=self.rules)
        self.assertEqual(p["status"], "upcoming")
        self.assertFalse(p["verified"])  # matched the default row
        self.assertEqual(len(p["backups"]), 2)
        with self.assertRaises(search.SearchError):
            planner.plan(self.conn, self.origin, date(2026, 1, 1), date(2026, 1, 3), now=NOW, rules=self.rules)


class IcsTest(unittest.TestCase):
    def test_ics(self):
        conn = memory_db()
        cg_id = store.upsert_campground(conn, make_campground("x" * 90))
        p = planner.plan(conn, cg_id, date(2027, 8, 14), date(2027, 8, 16), now=NOW,
                         rules={("recgov", "*"): RECGOV})
        text = planner.ics(p, now=NOW)
        self.assertTrue(text.startswith("BEGIN:VCALENDAR\r\n"))
        self.assertTrue(text.endswith("END:VCALENDAR\r\n"))
        self.assertNotIn("\n", text.replace("\r\n", ""))
        self.assertIn("DTSTART:20270214T150000Z\r\n", text)
        self.assertIn("TRIGGER:-PT15M", text)
        for line in text.split("\r\n"):
            self.assertLessEqual(len(line.encode()), 75)
        unfolded = text.replace("\r\n ", "")
        self.assertIn("SUMMARY:Book Camp " + "x" * 90, unfolded)

    def test_fold_multibyte(self):
        folded = planner.ics_fold("DESCRIPTION:" + "é" * 80)
        for line in folded.split("\r\n"):
            self.assertLessEqual(len(line.encode()), 75)
        self.assertEqual(folded.replace("\r\n ", ""), "DESCRIPTION:" + "é" * 80)

    def test_escape(self):
        self.assertEqual(planner.ics_escape("a,b;c\\d\ne"), "a\\,b\\;c\\\\d\\ne")


class BookingCalendarTest(unittest.TestCase):
    def test_events_sorted_and_past_skipped(self):
        conn = memory_db()
        a = store.upsert_campground(conn, make_campground("a"))
        b = store.upsert_campground(conn, make_campground("b", source="larimer"))
        walk = store.upsert_campground(conn, make_campground("w", reservable=False))
        rules = {("recgov", "*"): RECGOV, ("larimer", "*"): DAYS_180}
        stays = [(date(2026, 1, 1), date(2026, 1, 3))] + planner.weekends(2027, 7)
        cal = planner.booking_events(conn, [b, a, walk, 999, a], stays, now=NOW, rules=rules)
        self.assertEqual([c["id"] for c in cal["campgrounds"]], [b, a, walk])
        self.assertEqual(len(cal["events"]), 3 * 5)  # the 2026 stay is in the past
        upcoming = [e for e in cal["events"] if e["status"] == "upcoming"]
        self.assertEqual(upcoming[0]["campground"]["id"], a)  # Jan 2 8 AM before Larimer's Jan 3
        self.assertEqual(cal["events"][-1]["status"], "no_reservations")
        text = planner.ics(upcoming, now=NOW)
        self.assertEqual(text.count("BEGIN:VEVENT"), 10)


class StretchTest(unittest.TestCase):
    def test_weekends(self):
        july = planner.weekends(2027, 7)
        self.assertEqual(july[0], (date(2027, 7, 2), date(2027, 7, 4)))
        self.assertEqual(len(july), 5)


if __name__ == "__main__":
    unittest.main()
