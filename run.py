#!/usr/bin/env python3
"""Start the hotel management system.

    python3 run.py                     # http://localhost:8000 with demo data
    python3 run.py --no-demo           # empty hotel; prints a one-time admin password
    python3 run.py --host 0.0.0.0 --port 8443 --tls-cert cert.pem --tls-key key.pem
    python3 run.py --backup-now        # write a backup and exit

All options can also be set with HOTEL_* environment variables (see README).
"""
import argparse
import logging
import os
import webbrowser

from hotel.app import HotelApp
from hotel.config import Config


def main():
    p = argparse.ArgumentParser(description="Hotel management system")
    p.add_argument("--host")
    p.add_argument("--port", type=int)
    p.add_argument("--db")
    p.add_argument("--no-demo", action="store_true", help="start with an empty hotel instead of demo data")
    p.add_argument("--tls-cert", help="PEM certificate file to serve HTTPS directly")
    p.add_argument("--tls-key", help="PEM private key file")
    p.add_argument("--open", action="store_true", help="open the website in a browser")
    p.add_argument("--backup-now", action="store_true", help="create a database backup and exit")
    a = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    overrides = {k: v for k, v in {"host": a.host, "port": a.port, "db_path": a.db, "tls_cert": a.tls_cert,
                                   "tls_key": a.tls_key}.items() if v}
    if a.no_demo:
        overrides["seed_demo"] = False
    if a.tls_cert:
        overrides["secure_cookies"] = True
    app = HotelApp(Config.from_env(**overrides))
    info = app.initialize()
    if a.backup_now:
        print("Backup written:", app.backups.run()["file"])
        return

    cfg = app.config
    scheme = "https" if cfg.tls_cert else "http"
    url = f"{scheme}://{'localhost' if cfg.host in ('0.0.0.0', '127.0.0.1') else cfg.host}:{cfg.port}"
    print(f"\n  Hotel system running at {url}   (database: {os.path.abspath(cfg.db_path)})")
    print("  Portals: /  (guest website)  /login  /admin  /staff  /kitchen  /housekeeping  /account")
    if info.get("demo"):
        print("  Demo logins: admin/AdminPass123  frontdesk/FrontDesk123  chef/ChefPass123  maid/MaidPass123")
        print("               guest: amelia.hart@example.com / GuestPass123")
    elif info.get("admin_password"):
        print(f"  First start: sign in as 'admin' with the one-time password  {info['admin_password']}")
        print("  You will be asked to choose a new password immediately.")
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
