"""Builds seed_campgrounds.csv: Colorado state-park, county and city campgrounds.

These systems have no public list API, so the rows are curated by hand.
Coordinates are approximate (park/campground center) and marked verified=no
until checked against the booking site.
"""
import csv

COLUMNS = [
    "name", "park_or_area", "operator", "booking_system", "booking_url",
    "source_id", "nearest_town", "lat", "lng", "camping_type",
    "reservable", "notes", "verified",
]

CPW = "Colorado Parks & Wildlife"
CPW_URL = "https://www.cpwshop.com/campinghome.page"

# name, nearest town, lat, lng, camping type, notes
STATE_PARKS = [
    ("Arkansas Headwaters Recreation Area", "Salida", 38.65, -106.07, "developed", "Several campgrounds along the river (e.g. Hecla Junction, Ruby Mountain, Rincon, Railroad Bridge)"),
    ("Bonny Lake State Park", "Burlington", 39.62, -102.18, "developed", "Reservoir largely drained; check which campgrounds are open"),
    ("Boyd Lake State Park", "Loveland", 40.43, -105.04, "developed", ""),
    ("Chatfield State Park", "Littleton", 39.53, -105.07, "developed", ""),
    ("Cherry Creek State Park", "Aurora", 39.63, -104.83, "developed", ""),
    ("Cheyenne Mountain State Park", "Colorado Springs", 38.73, -104.82, "developed", ""),
    ("Crawford State Park", "Crawford", 38.68, -107.60, "developed", ""),
    ("Eleven Mile State Park", "Lake George", 38.94, -105.50, "developed", ""),
    ("Elkhead Reservoir State Park", "Craig", 40.56, -107.38, "developed", ""),
    ("Fishers Peak State Park", "Trinidad", 37.10, -104.45, "backcountry", "Newer park; confirm whether camping is open"),
    ("Golden Gate Canyon State Park", "Golden", 39.84, -105.41, "developed", "Reverend's Ridge, Aspen Meadows, plus backcountry sites"),
    ("Highline Lake State Park", "Loma", 39.27, -108.84, "developed", ""),
    ("Jackson Lake State Park", "Orchard", 40.38, -104.09, "developed", ""),
    ("James M. Robb - Colorado River State Park", "Grand Junction", 39.07, -108.47, "developed", "Multiple sections (e.g. Fruita, Island Acres)"),
    ("John Martin Reservoir State Park", "Hasty", 38.07, -102.95, "developed", ""),
    ("Lake Pueblo State Park", "Pueblo", 38.26, -104.73, "developed", ""),
    ("Lathrop State Park", "Walsenburg", 37.60, -104.83, "developed", ""),
    ("Lory State Park", "Bellvue", 40.59, -105.18, "backcountry", "Backcountry sites only"),
    ("Mancos State Park", "Mancos", 37.40, -108.27, "developed", ""),
    ("Mueller State Park", "Divide", 38.88, -105.18, "developed", ""),
    ("Navajo State Park", "Arboles", 37.01, -107.41, "developed", ""),
    ("North Sterling State Park", "Sterling", 40.79, -103.27, "developed", ""),
    ("Paonia State Park", "Paonia", 38.95, -107.35, "primitive", ""),
    ("Pearl Lake State Park", "Clark", 40.79, -106.89, "developed", ""),
    ("Ridgway State Park", "Ridgway", 38.21, -107.73, "developed", ""),
    ("Rifle Falls State Park", "Rifle", 39.68, -107.70, "developed", ""),
    ("Rifle Gap State Park", "Rifle", 39.63, -107.76, "developed", ""),
    ("St. Vrain State Park", "Firestone", 40.17, -104.99, "developed", ""),
    ("Stagecoach State Park", "Oak Creek", 40.27, -106.86, "developed", ""),
    ("State Forest State Park", "Walden", 40.55, -106.00, "developed", "Many campgrounds, cabins and yurts; cpwshop parkID 50042"),
    ("Staunton State Park", "Pine", 39.50, -105.38, "developed", ""),
    ("Steamboat Lake State Park", "Clark", 40.80, -106.95, "developed", ""),
    ("Sylvan Lake State Park", "Eagle", 39.48, -106.73, "developed", ""),
    ("Trinidad Lake State Park", "Trinidad", 37.15, -104.57, "developed", ""),
    ("Vega State Park", "Collbran", 39.22, -107.80, "developed", ""),
    ("Yampa River State Park", "Hayden", 40.49, -107.31, "developed", ""),
]

LARIMER_URL = "https://larimercamping.com"
LARIMER = "Larimer County Natural Resources"
# name, park/area, lat, lng, type, notes
LARIMER_CGS = [
    ("South Bay Campground", "Horsetooth Reservoir", 40.52, -105.15, "developed", ""),
    ("Inlet Bay Campground", "Horsetooth Reservoir", 40.56, -105.16, "developed", "Seasonal closures"),
    ("Carter Knolls Campground", "Carter Lake", 40.34, -105.20, "developed", ""),
    ("Eagle Campground", "Carter Lake", 40.35, -105.21, "developed", "Construction on main road"),
    ("Sky View Campground", "Carter Lake", 40.33, -105.20, "developed", ""),
    ("South Shore Campground", "Carter Lake", 40.31, -105.21, "developed", ""),
    ("North Pines Campground", "Carter Lake", 40.36, -105.21, "developed", "Closed until further notice"),
    ("Big Thompson Campground", "Carter Lake", 40.36, -105.22, "developed", "Converted to day-use parking; no camping"),
    ("Flatiron Campground", "Flatiron Reservoir", 40.36, -105.23, "developed", ""),
    ("Pinewood Campground", "Pinewood Reservoir", 40.37, -105.29, "developed", ""),
    ("Hermit's Hollow (campground #1)", "Hermit Park Open Space", 40.35, -105.46, "developed", ""),
    ("Bobcat (campground #2)", "Hermit Park Open Space", 40.35, -105.46, "developed", ""),
    ("Kruger Equestrian (campground #3)", "Hermit Park Open Space", 40.35, -105.47, "equestrian", ""),
    ("Granite Gulch (campground #4)", "Hermit Park Open Space", 40.34, -105.47, "developed", ""),
]

OTHER = [
    # name, park/area, operator, booking system, url, town, lat, lng, type, notes
    ("Sawmill Hiker Campground", "White Ranch Park", "Jefferson County Open Space", "rec1 (Jeffco catalog)",
     "https://www.jeffco.us/1636/Reserve-a-Campsite", "Golden", 39.82, -105.27, "backcountry",
     "Tent-only; book 90 days to 24 h ahead; $12/night"),
    ("Sourdough Springs Campground", "White Ranch Park", "Jefferson County Open Space", "rec1 (Jeffco catalog)",
     "https://www.jeffco.us/1636/Reserve-a-Campsite", "Golden", 39.83, -105.28, "backcountry",
     "Tent-only; closed Nov 1 - Mar 31"),
    ("Reynolds Park Campground", "Reynolds Park", "Jefferson County Open Space", "rec1 (Jeffco catalog)",
     "https://www.jeffco.us/1636/Reserve-a-Campsite", "Conifer", 39.46, -105.24, "backcountry",
     "Tent-only; book 90 days to 24 h ahead; $12/night"),
    ("Chief Hosa Campground", "Denver Mountain Parks", "City and County of Denver", "unknown - verify",
     "https://denvergov.org/Government/Agencies-Departments-Offices/Agencies-Departments-Offices-Directory/Parks-Recreation/Urban-Parks-Trails/Chief-Hosa-Campground",
     "Golden", 39.72, -105.36, "developed", "Booking system not confirmed"),
]


def main():
    rows = []
    for name, town, lat, lng, typ, notes in STATE_PARKS:
        rows.append(dict(name=name, park_or_area=name, operator=CPW, booking_system="cpwshop (Aspira)",
                         booking_url=CPW_URL, source_id="50042" if name.startswith("State Forest") else "",
                         nearest_town=town, lat=lat, lng=lng, camping_type=typ, reservable="yes",
                         notes=notes, verified="no"))
    rows.append(dict(name="Sweetwater Campground", park_or_area="Sweetwater Lake State Park",
                     operator="CPW with US Forest Service", booking_system="recreation.gov",
                     booking_url="https://www.recreation.gov/camping/campgrounds/232715", source_id="232715",
                     nearest_town="Gypsum", lat=39.80, lng=-107.16, camping_type="developed", reservable="yes",
                     notes="State park, but books on Recreation.gov; the federal script will also find it",
                     verified="no"))
    for name, area, lat, lng, typ, notes in LARIMER_CGS:
        rows.append(dict(name=name, park_or_area=area, operator=LARIMER, booking_system="larimercamping (Aspira)",
                         booking_url=LARIMER_URL, source_id="", nearest_town="Fort Collins / Loveland / Estes Park",
                         lat=lat, lng=lng, camping_type=typ,
                         reservable="no" if ("Closed" in notes or "no camping" in notes) else "yes",
                         notes=notes, verified="no"))
    for name, area, op, system, url, town, lat, lng, typ, notes in OTHER:
        rows.append(dict(name=name, park_or_area=area, operator=op, booking_system=system, booking_url=url,
                         source_id="", nearest_town=town, lat=lat, lng=lng, camping_type=typ,
                         reservable="yes", notes=notes, verified="no"))
    with open("seed_campgrounds.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows")


if __name__ == "__main__":
    main()
