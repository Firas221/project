#!/usr/bin/env python3
"""Start the hotel management system.

    python3 run.py                     # http://localhost:8000 with demo data
    python3 run.py --no-demo           # empty hotel; prints a one-time admin password
    python3 run.py --fresh-demo        # set the current database aside and start again with the demo hotel
    python3 run.py --host 0.0.0.0 --port 8443 --tls-cert cert.pem --tls-key key.pem
    python3 run.py --backup-now        # write a backup and exit
    python3 run.py --restore FILE      # replace the database with a backup and exit

All options can also be set with HOTEL_* environment variables (see README).
"""
import argparse
import datetime
import logging
import os
import webbrowser

from hotel.app import HotelApp
from hotel.config import Config
from hotel.db.seed import DEMO_PASSWORDS


def set_aside(db_path: str) -> None:
    """Renames the database (and its journal files) so the next start creates a new one. Nothing is deleted."""
    if not os.path.isfile(db_path):
        return
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    kept = f"{db_path}.before-demo-{stamp}"
    os.replace(db_path, kept)
    for suffix in ("-wal", "-shm"):
        if os.path.isfile(db_path + suffix):
            os.replace(db_path + suffix, kept + suffix)
    print(f"  The previous database was kept as {os.path.abspath(kept)}")


def main():
    p = argparse.ArgumentParser(description="Hotel management system")
    p.add_argument("--host")
    p.add_argument("--port", type=int)
    p.add_argument("--db")
    p.add_argument("--no-demo", action="store_true", help="start with an empty hotel instead of demo data")
    p.add_argument("--fresh-demo", action="store_true",
                   help="set the existing database aside (it is renamed, not deleted) and start with a new demo hotel: "
                        "rooms, guests and a demo login for every role")
    p.add_argument("--tls-cert", help="PEM certificate file to serve HTTPS directly")
    p.add_argument("--tls-key", help="PEM private key file")
    p.add_argument("--open", action="store_true", help="open the website in a browser")
    p.add_argument("--backup-now", action="store_true", help="create a database backup and exit")
    p.add_argument("--restore", metavar="FILE", help="restore a backup (a path, or a file name from the backup folder) "
                                                     "over the database and exit; the current data is backed up first")
    a = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    overrides = {k: v for k, v in {"host": a.host, "port": a.port, "db_path": a.db, "tls_cert": a.tls_cert,
                                   "tls_key": a.tls_key}.items() if v}
    if a.no_demo:
        overrides["seed_demo"] = False
    if a.tls_cert:
        overrides["secure_cookies"] = True
    if a.fresh_demo:
        overrides["seed_demo"] = True
        set_aside(Config.from_env(**overrides).db_path)
    app = HotelApp(Config.from_env(**overrides))
    if a.restore:
        path = a.restore if os.path.isfile(a.restore) else os.path.join(app.config.backup_dir, a.restore)
        try:
            result = app.restore_backup(path)
        except ValueError as e:
            raise SystemExit(f"Restore failed: {e}")
        print(f"Restored {result['restored']} into {os.path.abspath(app.config.db_path)}")
        if result["safety_backup"]:
            print(f"The data it replaced was saved first as {result['safety_backup']} in {app.config.backup_dir}")
        return
    info = app.initialize()
    if a.backup_now:
        print("Backup written:", app.backups.run()["file"])
        return

    cfg = app.config
    scheme = "https" if cfg.tls_cert else "http"
    url = f"{scheme}://{'localhost' if cfg.host in ('0.0.0.0', '127.0.0.1') else cfg.host}:{cfg.port}"
    print(f"\n  Hotel system running at {url}   (database: {os.path.abspath(cfg.db_path)})")
    print("  Portals: /  (guest website)  /login  /admin  /manager  /staff  /finance  /kitchen  /housekeeping")
    print("           /maintenance  /store  /restaurant  /account")
    if info.get("demo"):
        print("  This is the DEMO hotel: 24 rooms, sample guests and bookings.")
        print("  Demo logins: admin/AdminPass123  frontdesk/FrontDesk123  chef/ChefPass123  maid/MaidPass123")
        print("               manager/ManagerPass123  accountant/AccountPass123  supervisor/SuperPass123")
        print("               tech/TechPass123  store/StorePass123  waiter/WaiterPass123")
        print("               guest: amelia.hart@example.com / GuestPass123")
    elif info.get("admin_password"):
        print(f"  First start: sign in as 'admin' with the one-time password  {info['admin_password']}")
        print("  You will be asked to choose a new password immediately.")
    else:
        rooms, demo_users = app.describe()
        print(f"  Using the existing database: {rooms} room(s), {demo_users} of the {len(DEMO_PASSWORDS) - 1} demo staff logins present.")
        if rooms == 0 or demo_users < len(DEMO_PASSWORDS) - 1:
            print("  It is not the full demo hotel, so some demo logins will not work and there may be no rooms.")
            print("  For the demo hotel run:  python3 run.py --fresh-demo   (the current database is kept under another name)")
    if not cfg.tls_cert and cfg.host not in ("127.0.0.1", "localhost"):
        print("  WARNING: serving without HTTPS on a network interface. Use --tls-cert/--tls-key or a reverse proxy.")
    print()
    server = app.make_server()
    app.start_background_jobs()
    if a.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        app.stop()
        server.server_close()


if __name__ == "__main__":
    main()
