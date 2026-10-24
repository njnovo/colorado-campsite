#!/usr/bin/env python3
"""Command-line entry point. Run `python3 manage.py --help`."""
import argparse
import logging
import sys
from datetime import date, datetime, timedelta, timezone

from campfinder import config, db, planner, search, server, store
from campfinder.adapters import ridb, seed


def cmd_initdb(conn, _args):
    db.init(conn)
    print(f"Database ready at {config.DB_PATH}")


def cmd_import_ridb(conn, args):
    db.init(conn)
    count = sites = 0
    for cg in ridb.iter_colorado_campgrounds(limit=args.limit, with_campsites=not args.no_sites,
                                             grid=not args.no_grid):
        store.upsert_campground(conn, cg)
        count += 1
        sites += len(cg.campsites)
        print(f"  {cg.name} ({cg.agency.name}): {len(cg.campsites)} sites")
    print(f"Imported {count} campgrounds, {sites} campsites from RIDB.")


def cmd_import_seed(conn, args):
    db.init(conn)
    imported, skipped = 0, []
    for row, cg, reason in seed.read_seed(args.csv):
        if cg is None:
            skipped.append(f"{row['name']}: {reason}")
            continue
        exists = conn.execute("SELECT 1 FROM campgrounds WHERE source = ? AND source_id = ?",
                              (cg.source, cg.source_id)).fetchone()
        if cg.source == "recgov" and exists:
            skipped.append(f"{cg.name}: already imported from RIDB (RIDB data wins)")
            continue
        store.upsert_campground(conn, cg)
        imported += 1
        flag = "" if cg.extra["verified"] else "  (location unverified)"
        print(f"  [{cg.source}] {cg.name}{flag}")
    print(f"Imported {imported} campgrounds from {args.csv}.")
    for line in skipped:
        print(f"  skipped - {line}")


def find_campgrounds(conn, query):
    """Match by id, or by every word appearing in the name."""
    if query.isdigit():
        return conn.execute("SELECT id, name, source FROM campgrounds WHERE id = ?",
                            (int(query),)).fetchall()
    words = query.split()
    return conn.execute(
        "SELECT id, name, source FROM campgrounds WHERE "
        + " AND ".join("name LIKE ?" for _ in words) + " ORDER BY name",
        [f"%{w}%" for w in words],
    ).fetchall()


def _one_campground(conn, query):
    matches = find_campgrounds(conn, query)
    if len(matches) != 1:
        for r in matches:
            print(f"    {r['id']:>4}  {r['name']}  [{r['source']}]")
        sys.exit(f"'{query}' matches {len(matches)} campgrounds; use an id or more words.")
    return matches[0]


def cmd_plan(conn, args):
    db.init(conn)
    cg = _one_campground(conn, args.campground)
    if args.month:
        year, month = map(int, args.month.split("-"))
        stays = planner.weekends(year, month)
    else:
        if not (args.checkin and args.checkout):
            sys.exit("Give CHECKIN CHECKOUT (YYYY-MM-DD) or --month YYYY-MM")
        stays = [(date.fromisoformat(args.checkin), date.fromisoformat(args.checkout))]
    print(cg["name"])
    for checkin, checkout in stays:
        try:
            p = planner.plan(conn, cg["id"], checkin, checkout)
        except search.SearchError as e:
            print(f"  {checkin} to {checkout}: {e}")
            continue
        when = {"open": "already bookable", "no_reservations": "no reservations (first-come)",
                "lottery": "lottery"}.get(p["status"], p.get("opens_at_text"))
        extra = f"; last night opens {p['full_stay_opens_at_text']}" if p.get("full_stay_opens_at_text") else ""
        print(f"  {checkin} to {checkout}: {when}{extra}")
    if p.get("rule"):
        print(f"  Rule: {p['rule']['summary']} - "
              + (f"verified {p['rule']['verified_on']}" if p["verified"] else "UNVERIFIED, check the booking site"))
    if not args.month:
        for b in p["backups"]:
            print(f"  backup: {b['name']} ({b['distance_mi']} mi) "
                  f"{'already bookable' if b['status'] == 'open' else b['opens_at_text']}")


def cmd_openings(conn, args):
    db.init(conn)
    ids = [r["id"] for q in args.names for r in find_campgrounds(conn, q)]
    if not ids:
        sys.exit("No campgrounds match. Give ids or name words, e.g. openings \"moraine park\"")
    start = datetime.now(timezone.utc)
    openings = planner.openings_between(conn, ids, start, start + timedelta(days=args.days))
    for o in openings:
        print(f"  {planner.friendly(o['opens_at'], o['time_known'])}: {o['campground']}, "
              f"night of {o['night']:%a %b} {o['night'].day}")
    print(f"{len(openings)} nights open in the next {args.days} days.")


def cmd_status(conn, _args):
    db.init(conn)
    meta = server.api_meta(conn, {})
    print(f"Campgrounds: {meta['campgrounds']}  Campsites: {meta['campsites']}")
    for a in meta["agencies"]:
        print(f"  {a['name']}: {a['campgrounds']}")


def cmd_serve(conn, args):
    db.init(conn)
    conn.close()
    server.serve(args.host, args.port)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Colorado Campsite Finder")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("initdb", help="create the database tables")
    p = sub.add_parser("import-ridb", help="import Colorado campgrounds from RIDB (needs RIDB_API_KEY)")
    p.add_argument("--limit", type=int, help="stop after N campgrounds (for testing)")
    p.add_argument("--no-sites", action="store_true", help="skip per-campsite details")
    p.add_argument("--no-grid", action="store_true",
                   help="skip the radius-grid pass (faster; may miss a few campgrounds)")
    p = sub.add_parser("import-seed", help="import hand-curated state/county campgrounds from CSV")
    p.add_argument("--csv", default=seed.SEED_CSV, help="path to seed CSV")
    p = sub.add_parser("plan", help="when does a stay become bookable? (booking-day planner)")
    p.add_argument("campground", help="campground id or name words")
    p.add_argument("checkin", nargs="?")
    p.add_argument("checkout", nargs="?")
    p.add_argument("--month", help="YYYY-MM: plan every Fri-Sun weekend in that month instead")
    p = sub.add_parser("openings", help="nights that open for booking in the next few days")
    p.add_argument("names", nargs="+", help="campground ids or name words")
    p.add_argument("--days", type=int, default=7)
    sub.add_parser("status", help="show data counts")
    p = sub.add_parser("serve", help="run the website")
    p.add_argument("--host")
    p.add_argument("--port", type=int)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    commands = {
        "initdb": cmd_initdb, "import-ridb": cmd_import_ridb, "import-seed": cmd_import_seed,
        "plan": cmd_plan, "openings": cmd_openings, "status": cmd_status, "serve": cmd_serve,
    }
    conn = db.connect()
    try:
        commands[args.command](conn, args)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
