"""Run with: python3 -m unittest discover -s tests"""
import json
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from campfinder import config, db, scheduler, search, store
from campfinder.adapters import recgov, ridb, seed
from campfinder.adapters.base import AdapterDisabled, Agency, Campground, Campsite, SchemaError
from campfinder.fetch import RateLimiter, build_url

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


def memory_db():
    conn = db.connect(":memory:")
    db.init(conn)
    return conn


def make_campground(source_id="cg1", lat=40.0, lng=-105.3, sites=None, source="recgov", reservable=True):
    return Campground(
        source=source, source_id=source_id, name=f"Camp {source_id}",
        agency=Agency("Test Agency", "Recreation.gov"), lat=lat, lng=lng,
        reservable=reservable,
        campsites=sites if sites is not None else [
            Campsite("t1", "T1", type="tent", price_per_night=20, pets=True),
            Campsite("r1", "R1", type="rv", max_rv_length_ft=35, hookups={"electric_amps": 50, "water": True},
                     price_per_night=40, pets=False),
        ],
    )


class RidbNormalizeTest(unittest.TestCase):
    def test_facility(self):
        cg = ridb.normalize_facility(fixture("ridb_facility.json"))
        self.assertEqual(cg.name, "Moraine Park Campground")
        self.assertEqual(cg.agency.name, "National Park Service")
        self.assertEqual(cg.booking_url, "https://www.recreation.gov/camping/campgrounds/232463")
        self.assertIn("8,160 ft & is open", cg.description)
        self.assertNotIn("<p>", cg.description)
        self.assertEqual([p["url"] for p in cg.photos],
                         ["https://example.test/a.jpg", "https://example.test/b.jpg"])
        self.assertEqual(cg.amenities, ["Camping", "Hiking"])

    def test_campsites(self):
        sites = [ridb.normalize_campsite(s) for s in fixture("ridb_campsites.json")]
        standard, rv, tent, management, group = sites
        self.assertIsNone(management)

        self.assertEqual(standard.type, "rv")  # trailer allowed
        self.assertTrue(standard.attributes["tent_ok"])
        self.assertEqual(standard.max_rv_length_ft, 30)
        self.assertEqual(standard.max_people, 8)
        self.assertTrue(standard.pets)

        self.assertEqual(rv.type, "rv")
        self.assertEqual(rv.hookups, {"electric_amps": 50, "water": True})
        self.assertEqual(rv.max_rv_length_ft, 45)  # from Driveway Length
        self.assertTrue(rv.ada)
        self.assertFalse(rv.pets)

        self.assertEqual(tent.type, "tent")
        self.assertIsNone(tent.pets)
        self.assertEqual(group.type, "group")
        self.assertEqual(group.max_people, 40)

    def test_title_name(self):
        self.assertEqual(ridb.title_name("ANGEL OF SHAVANO GROUP"), "Angel of Shavano Group")
        self.assertEqual(ridb.title_name("AMPHITHEATER (CO)"), "Amphitheater (CO)")
        self.assertEqual(ridb.title_name("THE CRAGS"), "The Crags")

    def test_site_type_mapping(self):
        self.assertEqual(ridb.site_type("CABIN ELECTRIC", False), "cabin")
        self.assertEqual(ridb.site_type("YURT", False), "yurt")
        self.assertEqual(ridb.site_type("GROUP EQUESTRIAN", False), "group")
        self.assertEqual(ridb.site_type("EQUESTRIAN NONELECTRIC", False), "equestrian")
        self.assertEqual(ridb.site_type("BOAT IN", False), "boat-in")
        self.assertEqual(ridb.site_type("WALK TO", False), "tent")
        self.assertEqual(ridb.site_type("STANDARD NONELECTRIC", False), "tent")
        self.assertIsNone(ridb.site_type("SHELTER NONELECTRIC", False))


class RecgovAdapterTest(unittest.TestCase):
    def test_parse_month(self):
        result = recgov.parse_month(fixture("recgov_month.json"))
        self.assertEqual(result["1001"], {
            "2027-07-01": "available", "2027-07-02": "reserved", "2027-07-03": "fcfs"})
        self.assertEqual(result["1002"], {
            "2027-07-01": "not_released", "2027-07-02": "closed", "2027-07-03": "closed"})

    def test_schema_change_detected(self):
        with self.assertRaises(SchemaError):
            recgov.parse_month({"sites": []})
        with self.assertRaises(SchemaError):
            recgov.parse_month({"campsites": {"1": {"dates": {}}}})

    def test_disabled_by_default(self):
        with mock.patch.object(config, "RECGOV_AVAILABILITY_ENABLED", False), \
             mock.patch("campfinder.fetch.get_json") as get_json:
            with self.assertRaises(AdapterDisabled):
                recgov.fetch_month("232463", date(2027, 7, 1))
            get_json.assert_not_called()

    def test_start_date_is_url_encoded(self):
        url = build_url(recgov.MONTH_URL.format(facility_id=1), {"start_date": "2027-07-01T00:00:00.000Z"})
        self.assertIn("start_date=2027-07-01T00%3A00%3A00.000Z", url)


class RateLimiterTest(unittest.TestCase):
    def test_waits_between_requests(self):
        now = [100.0]
        sleeps = []
        limiter = RateLimiter({"x": 10.0}, sleep=lambda s: sleeps.append(s), clock=lambda: now[0])
        limiter.wait("x")
        self.assertEqual(sleeps, [])
        now[0] += 2
        limiter.wait("x")
        self.assertEqual(len(sleeps), 1)
        self.assertGreaterEqual(sleeps[0], 8.0)


class StoreTest(unittest.TestCase):
    def test_upsert_is_idempotent(self):
        conn = memory_db()
        first = store.upsert_campground(conn, make_campground())
        second = store.upsert_campground(conn, make_campground())
        self.assertEqual(first, second)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM campsites").fetchone()[0], 2)

    def test_status_changes_are_logged(self):
        conn = memory_db()
        cg_id = store.upsert_campground(conn, make_campground())
        rows, changes = store.save_availability(conn, cg_id, {"t1": {"2027-07-01": "reserved"}})
        self.assertEqual((rows, changes), (1, 0))
        rows, changes = store.save_availability(
            conn, cg_id, {"t1": {"2027-07-01": "available"}, "unknown-site": {"2027-07-01": "available"}})
        self.assertEqual((rows, changes), (1, 1))
        event = conn.execute("SELECT old_status, new_status FROM availability_events").fetchone()
        self.assertEqual(tuple(event), ("reserved", "available"))


class SearchTest(unittest.TestCase):
    def setUp(self):
        self.conn = memory_db()
        self.start, self.end = date(2027, 7, 18), date(2027, 7, 20)
        nights = ["2027-07-18", "2027-07-19"]
        # A: tent open both nights; rv open one night
        a = store.upsert_campground(self.conn, make_campground("A", lat=40.0, lng=-105.3))
        store.save_availability(self.conn, a, {
            "t1": dict.fromkeys(nights, "available"),
            "r1": {"2027-07-18": "available", "2027-07-19": "reserved"},
        })
        # B: everything reserved, farther away
        b = store.upsert_campground(self.conn, make_campground("B", lat=38.0, lng=-107.0))
        store.save_availability(self.conn, b, {
            "t1": dict.fromkeys(nights, "reserved"), "r1": dict.fromkeys(nights, "reserved")})
        # C: never checked
        store.upsert_campground(self.conn, make_campground("C", lat=39.0, lng=-105.0))
        # D: first-come only
        store.upsert_campground(self.conn, make_campground("D", lat=39.5, lng=-105.5, reservable=False))

    def run_search(self, **kw):
        return {r["name"]: r for r in search.search(self.conn, self.start, self.end, **kw)}

    def test_statuses(self):
        results = self.run_search()
        self.assertEqual(results["Camp A"]["status"], "open")
        self.assertEqual(results["Camp A"]["open_sites"], 1)
        self.assertEqual(results["Camp A"]["partial_sites"], 1)
        self.assertEqual(results["Camp B"]["status"], "full")
        self.assertEqual(results["Camp C"]["status"], "unknown")
        self.assertNotIn("Camp D", results)
        self.assertEqual(self.run_search(include_fcfs=True)["Camp D"]["status"], "fcfs")

    def test_walkup_only_is_fcfs_not_full(self):
        e = store.upsert_campground(self.conn, make_campground("E", lat=39.0, lng=-105.5))
        store.save_availability(self.conn, e, {
            "t1": dict.fromkeys(["2027-07-18", "2027-07-19"], "fcfs"),
            "r1": dict.fromkeys(["2027-07-18", "2027-07-19"], "reserved")})
        self.assertEqual(self.run_search()["Camp E"]["status"], "fcfs")

    def test_filters(self):
        results = self.run_search(types=["rv"], electric=True)
        self.assertEqual(results["Camp A"]["status"], "partial")
        self.assertEqual(results["Camp A"]["min_price"], 40)
        self.assertEqual(self.run_search(min_rv_length=40), {})
        self.assertEqual(self.run_search(pets=True)["Camp A"]["status"], "open")
        self.assertEqual(self.run_search(sewer=True), {})

    def test_radius_and_sort(self):
        results = search.search(self.conn, self.start, self.end, lat=39.74, lng=-104.99, radius_mi=60)
        self.assertEqual([r["name"] for r in results], ["Camp A", "Camp C"])
        by_availability = search.search(self.conn, self.start, self.end, sort="availability")
        self.assertEqual(by_availability[0]["name"], "Camp A")

    def test_bad_dates(self):
        with self.assertRaises(search.SearchError):
            search.search(self.conn, self.end, self.start)

    def test_campground_detail(self):
        cg_id = self.conn.execute("SELECT id FROM campgrounds WHERE source_id = 'A'").fetchone()[0]
        cg = search.get_campground(self.conn, cg_id, self.start, self.end)
        self.assertEqual(cg["dates"], ["2027-07-18", "2027-07-19", "2027-07-20"])
        tent = next(s for s in cg["sites"] if s["source_id"] == "t1")
        self.assertEqual(tent["availability"]["2027-07-18"], "available")
        self.assertIsNone(search.get_campground(self.conn, 9999, self.start, self.end))


class SchedulerTest(unittest.TestCase):
    def test_tiers(self):
        today = date(2027, 5, 1)
        self.assertEqual(scheduler.tier_for(True, False, date(2027, 6, 1), today), "hot")
        self.assertEqual(scheduler.tier_for(False, True, date(2027, 6, 1), today), "hot")
        self.assertEqual(scheduler.tier_for(False, False, date(2027, 6, 1), today), "warm")
        self.assertEqual(scheduler.tier_for(True, False, date(2027, 10, 1), today), "warm")
        self.assertEqual(scheduler.tier_for(False, False, date(2027, 10, 1), today), "cold")

    def test_month_starts(self):
        months = list(scheduler.month_starts(date(2027, 1, 31), 50))
        self.assertEqual(months, [date(2027, 1, 1), date(2027, 2, 1), date(2027, 3, 1)])

    def test_due_jobs_respect_last_success(self):
        conn = memory_db()
        cg = make_campground()
        cg.booking_window_days = 20
        cg_id = store.upsert_campground(conn, cg)
        store.upsert_campground(conn, make_campground("demo1", source="demo"))  # no adapter
        store.upsert_campground(conn, make_campground("unwatched"))
        now = datetime(2027, 5, 10, 12, tzinfo=timezone.utc)
        self.assertEqual(scheduler.due_jobs(conn, now), [])  # nothing watched yet
        conn.execute("UPDATE campgrounds SET watched = 1 WHERE source_id IN ('cg1', 'demo1')")
        jobs = scheduler.due_jobs(conn, now)
        self.assertEqual([(j.campground_id, j.month) for j in jobs], [(cg_id, date(2027, 5, 1))])

        conn.execute("INSERT INTO poll_runs (source, campground_id, month, started_at, ok) VALUES (?,?,?,?,1)",
                     ("recgov", cg_id, "2027-05-01", (now - timedelta(minutes=5)).isoformat()))
        self.assertEqual(scheduler.due_jobs(conn, now), [])
        self.assertEqual(len(scheduler.due_jobs(conn, now + timedelta(hours=2))), 1)

    def test_watch_days_limits_months(self):
        conn = memory_db()
        store.upsert_campground(conn, make_campground())
        conn.execute("UPDATE campgrounds SET watched = 1, booking_window_days = 180")
        now = datetime(2027, 5, 10, 12, tzinfo=timezone.utc)
        with mock.patch.object(config, "WATCH_DAYS", 60):
            months = [j.month for j in scheduler.due_jobs(conn, now)]
        self.assertEqual(months, [date(2027, 5, 1), date(2027, 6, 1), date(2027, 7, 1)])

    def test_run_job_records_failures(self):
        conn = memory_db()
        cg_id = store.upsert_campground(conn, make_campground())
        job = scheduler.Job("recgov", cg_id, "cg1", date(2027, 7, 1), "warm", None)

        def boom(*_):
            raise SchemaError("shape changed")

        with mock.patch.dict(scheduler.AVAILABILITY_ADAPTERS, {"recgov": boom}):
            self.assertFalse(scheduler.run_job(conn, job))
        run = conn.execute("SELECT ok, error FROM poll_runs").fetchone()
        self.assertEqual(run["ok"], 0)
        self.assertIn("shape changed", run["error"])

        fake = lambda *_: (200, {"t1": {"2027-07-01": "available"}})
        with mock.patch.dict(scheduler.AVAILABILITY_ADAPTERS, {"recgov": fake}):
            self.assertTrue(scheduler.run_job(conn, job))


class SeedAdapterTest(unittest.TestCase):
    def rows(self):
        return {row["name"]: (cg, reason) for row, cg, reason in seed.read_seed()}

    def test_real_seed_csv(self):
        rows = self.rows()
        self.assertEqual(len(rows), 55)
        cg, _ = rows["State Forest State Park"]
        self.assertEqual((cg.source, cg.source_id), ("cpw", "state-forest-state-park"))
        self.assertEqual(cg.extra["booking_id"], "50042")
        self.assertEqual(cg.agency.booking_system, "cpwshop.com")
        self.assertFalse(cg.extra["verified"])

        sweetwater, _ = rows["Sweetwater Campground"]
        self.assertEqual((sweetwater.source, sweetwater.source_id), ("recgov", "232715"))

        closed, reason = rows["North Pines Campground"]
        self.assertIsNone(closed)
        self.assertIn("Closed", reason)

        hosa, _ = rows["Chief Hosa Campground"]
        self.assertEqual(hosa.source, "other")
        self.assertEqual(rows["Reynolds Park Campground"][0].source, "jeffco")
        self.assertEqual(rows["Pinewood Campground"][0].source, "larimer")

    def test_siteless_campgrounds_show_as_unknown(self):
        conn = memory_db()
        for _, cg, _ in seed.read_seed():
            if cg:
                store.upsert_campground(conn, cg)
        results = search.search(conn, date(2027, 7, 18), date(2027, 7, 20))
        self.assertEqual(len(results), 53)
        self.assertEqual({r["status"] for r in results}, {"unknown"})
        # site-level filters need site data
        self.assertEqual(search.search(conn, date(2027, 7, 18), date(2027, 7, 20), types=["tent"]), [])


class RidbDiscoveryTest(unittest.TestCase):
    def test_in_colorado(self):
        self.assertTrue(ridb.in_colorado({"FacilityLatitude": 39.5, "FacilityLongitude": -105.5}))
        self.assertFalse(ridb.in_colorado({"FacilityLatitude": 40.5, "FacilityLongitude": -111.0}))
        self.assertTrue(ridb.in_colorado({"FacilityLatitude": 0, "FacilityLongitude": 0,
                                          "FACILITYADDRESS": [{"AddressStateCode": "CO"}]}))

    def test_grid_covers_state(self):
        points = list(ridb.grid_points())
        self.assertEqual(len(points), 4 * 7)
        self.assertTrue(all(ridb.CO_LAT[0] < lat < ridb.CO_LAT[1] for lat, _ in points))

    def test_two_pass_dedupes(self):
        fac = {"FacilityID": 1, "FacilityName": "A", "FacilityTypeDescription": "Campground",
               "FacilityLatitude": 39.5, "FacilityLongitude": -105.5}
        lodge = dict(fac, FacilityID=2, FacilityTypeDescription="Lodging")
        with mock.patch.object(ridb, "paginate", return_value=[fac, lodge]) as pag:
            found = ridb.find_colorado_facilities("key", log=lambda *_: None)
        self.assertEqual(list(found), ["1"])
        self.assertEqual(pag.call_count, 1 + 28)


class MigrationTest(unittest.TestCase):
    def test_adds_extra_column_to_old_db(self):
        conn = db.connect(":memory:")
        conn.execute("CREATE TABLE campgrounds (id INTEGER PRIMARY KEY, source TEXT, source_id TEXT, name TEXT)")
        db.init(conn)
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(campgrounds)")}
        self.assertIn("extra", cols)



class ClosedMonthTest(unittest.TestCase):
    def test_empty_response_marks_month_closed(self):
        conn = memory_db()
        cg_id = store.upsert_campground(conn, make_campground())
        job = scheduler.Job("recgov", cg_id, "cg1", date(2027, 2, 1), "hot", None)
        with mock.patch.dict(scheduler.AVAILABILITY_ADAPTERS, {"recgov": lambda *_: (200, {})}):
            self.assertTrue(scheduler.run_job(conn, job))
        rows = conn.execute("SELECT status, COUNT(*), MIN(date), MAX(date) FROM availability GROUP BY status").fetchall()
        self.assertEqual([tuple(r) for r in rows], [("closed", 2 * 28, "2027-02-01", "2027-02-28")])

if __name__ == "__main__":
    unittest.main()
