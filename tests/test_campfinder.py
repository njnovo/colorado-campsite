"""Run with: python3 -m unittest discover -s tests"""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from campfinder import db, search, server, store
from campfinder.adapters import ridb, seed
from campfinder.adapters.base import Agency, Campground, Campsite
from campfinder.fetch import RateLimiter

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

class SearchTest(unittest.TestCase):
    def setUp(self):
        self.conn = memory_db()
        self.start, self.end = date(2027, 7, 18), date(2027, 7, 20)
        store.upsert_campground(self.conn, make_campground("A", lat=40.0, lng=-105.3))
        store.upsert_campground(self.conn, make_campground("B", lat=38.0, lng=-107.0))
        store.upsert_campground(self.conn, make_campground("C", lat=39.0, lng=-105.0, sites=[]))
        store.upsert_campground(self.conn, make_campground("D", lat=39.5, lng=-105.5, reservable=False))

    def run_search(self, **kw):
        return {r["name"]: r for r in search.search(self.conn, self.start, self.end, **kw)}

    def test_reservable_only_by_default(self):
        self.assertEqual(set(self.run_search()), {"Camp A", "Camp B", "Camp C"})
        self.assertIn("Camp D", self.run_search(include_fcfs=True))

    def test_filters(self):
        results = self.run_search(types=["rv"], electric=True)
        self.assertEqual(set(results), {"Camp A", "Camp B"})
        self.assertEqual(results["Camp A"]["min_price"], 40)
        self.assertEqual(results["Camp A"]["matching_sites"], 1)
        self.assertEqual(self.run_search(min_rv_length=40), {})
        self.assertEqual(self.run_search(sewer=True), {})

    def test_radius_and_sort(self):
        results = search.search(self.conn, self.start, self.end, lat=39.74, lng=-104.99, radius_mi=60)
        self.assertEqual([r["name"] for r in results], ["Camp A", "Camp C"])
        by_price = search.search(self.conn, self.start, self.end, sort="price")
        self.assertEqual(by_price[-1]["name"], "Camp C")  # no price sorts last

    def test_bad_dates(self):
        with self.assertRaises(search.SearchError):
            search.search(self.conn, self.end, self.start)

    def test_campground_detail(self):
        cg_id = self.conn.execute("SELECT id FROM campgrounds WHERE source_id = 'A'").fetchone()[0]
        cg = search.get_campground(self.conn, cg_id)
        self.assertEqual({s["source_id"] for s in cg["sites"]}, {"t1", "r1"})
        self.assertIsNone(search.get_campground(self.conn, 9999))

    def test_find_by_name(self):
        self.assertEqual([r["name"] for r in search.find_by_name(self.conn, "camp b")], ["Camp B"])
        self.assertEqual(search.find_by_name(self.conn, "  "), [])

    def test_api_search_adds_booking_times(self):
        data = server.api_search(self.conn, {"start": "2027-07-18", "end": "2027-07-20", "sort": "opens"})
        self.assertTrue(all("booking" in r for r in data["results"]))


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

    def test_siteless_campgrounds_are_searchable(self):
        conn = memory_db()
        for _, cg, _ in seed.read_seed():
            if cg:
                store.upsert_campground(conn, cg)
        results = search.search(conn, date(2027, 7, 18), date(2027, 7, 20))
        self.assertEqual(len(results), 53)
        self.assertEqual({r["matching_sites"] for r in results}, {0})
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

    def test_drops_old_availability_tables(self):
        conn = db.connect(":memory:")
        conn.execute("CREATE TABLE availability (campsite_id INTEGER, date TEXT)")
        db.init(conn)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertNotIn("availability", tables)


class SharedRateLimiterTest(unittest.TestCase):
    def test_limit_shared_through_state_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            sleeps = []
            a = RateLimiter({"x": 10.0}, sleep=sleeps.append, state_dir=tmp)
            b = RateLimiter({"x": 10.0}, sleep=sleeps.append, state_dir=tmp)  # "another process"
            a.wait("x")
            b.wait("x")
            self.assertEqual(len(sleeps), 1)
            self.assertGreater(sleeps[0], 9.0)

if __name__ == "__main__":
    unittest.main()
