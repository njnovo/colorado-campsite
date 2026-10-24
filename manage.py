#!/usr/bin/env python3
"""Command-line entry point. Run `python3 manage.py --help`."""
import argparse
import logging
import sys
from datetime import date, timedelta

from campfinder import config, db, demo, scheduler, server, store
from campfinder.adapters import ridb, seed
from campfinder.adapters.base import AdapterDisabled


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
        return conn.execute("SELECT id, name, source, watched FROM campgrounds WHERE id = ?",
                            (int(query),)).fetchall()
    words = query.split()
    return conn.execute(
        "SELECT id, name, source, watched FROM campgrounds WHERE "
        + " AND ".join("name LIKE ?" for _ in words) + " ORDER BY name",
        [f"%{w}%" for w in words],
    ).fetchall()


def cmd_watch(conn, args):
    db.init(conn)
    if args.action == "list":
        rows = conn.execute("SELECT id, name, source FROM campgrounds WHERE watched ORDER BY name").fetchall()
        for r in rows:
            print(f"  {r['id']:>4}  {r['name']}  [{r['source']}]")
        print(f"{len(rows)} watched. Polled {config.WATCH_DAYS} days ahead; "
              f"Recreation.gov polling is {'ON' if config.RECGOV_AVAILABILITY_ENABLED else 'OFF'}.")
        return
    if not args.names:
        sys.exit("Give one or more campground ids or names, e.g. watch add \"moraine park\"")
    for query in args.names:
        matches = find_campgrounds(conn, query)
        if not matches:
            print(f"  no campground matches '{query}'")
            continue
        if len(matches) > 1 and not args.all:
            print(f"  '{query}' matches {len(matches)} campgrounds; use an id, or --all:")
            for r in matches:
                print(f"    {r['id']:>4}  {r['name']}  [{r['source']}]")
            continue
        for r in matches:
            conn.execute("UPDATE campgrounds SET watched = ? WHERE id = ?", (args.action == "add", r["id"]))
            print(f"  {'watching' if args.action == 'add' else 'stopped watching'}: {r['name']}")
    conn.commit()


def cmd_seed_demo(conn, args):
    db.init(conn)
    demo.clear(conn)
    if args.clear:
        print("Removed demo data.")
        return
    print(f"Seeded {demo.seed(conn)} DEMO campgrounds (fake data, labelled in the UI).")


def cmd_poll(conn, args):
    db.init(conn)
    try:
        if args.loop:
            scheduler.worker_loop(conn)
        else:
            print(f"Ran {scheduler.run_due(conn, max_jobs=args.max_jobs)} poll jobs.")
    except AdapterDisabled as e:
        sys.exit(str(e))


def cmd_status(conn, _args):
    db.init(conn)
    meta = server.api_meta(conn, {})
    print(f"Campgrounds: {meta['campgrounds']}  Campsites: {meta['campsites']}  "
          f"Last availability check: {meta['last_checked'] or 'never'}")
    print(f"Recreation.gov availability polling: "
          f"{'ON' if config.RECGOV_AVAILABILITY_ENABLED else 'OFF'}")
    print(f"Poll jobs due now: {len(scheduler.due_jobs(conn))}")
    for s in server.api_health(conn, {})["sources"]:
        print(f"  {s['source']}: {s['ok_24h']}/{s['runs_24h']} ok in 24h, "
              f"last success {s['last_success']}, last error: {s['last_error']}")


def cmd_prune(conn, _args):
    removed = db.prune_old_availability(conn, (date.today() - timedelta(days=1)).isoformat())
    print(f"Removed {removed} old availability rows.")


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
    p = sub.add_parser("watch", help="manage which campgrounds get live availability checks")
    p.add_argument("action", choices=["add", "remove", "list"])
    p.add_argument("names", nargs="*", help="campground ids or name words")
    p.add_argument("--all", action="store_true", help="apply to every match")
    p = sub.add_parser("seed-demo", help="load fake demo campgrounds to try the UI")
    p.add_argument("--clear", action="store_true", help="remove demo data instead")
    p = sub.add_parser("poll", help="run due availability checks")
    p.add_argument("--max-jobs", type=int, default=20)
    p.add_argument("--loop", action="store_true", help="keep running as a worker")
    sub.add_parser("status", help="show data and source health")
    sub.add_parser("prune", help="delete availability rows for past dates")
    p = sub.add_parser("serve", help="run the website")
    p.add_argument("--host")
    p.add_argument("--port", type=int)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    commands = {
        "initdb": cmd_initdb, "import-ridb": cmd_import_ridb, "import-seed": cmd_import_seed,
        "seed-demo": cmd_seed_demo, "watch": cmd_watch,
        "poll": cmd_poll, "status": cmd_status, "prune": cmd_prune, "serve": cmd_serve,
    }
    conn = db.connect()
    try:
        commands[args.command](conn, args)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
