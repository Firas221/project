#!/usr/bin/env python3
"""Start the hotel management system.

    python3 run.py                      # http://127.0.0.1:8000
    python3 run.py --port 9000 --host 0.0.0.0 --db data/hotel.db
    python3 run.py --no-demo            # start with an empty hotel (admin user only)
"""
import argparse
import logging
import os
import webbrowser

from hotel.server import make_server


def main():
    p = argparse.ArgumentParser(description="Hotel reservation & inventory system")
    p.add_argument("--host", default=os.environ.get("HOTEL_HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(os.environ.get("HOTEL_PORT", "8000")))
    p.add_argument("--db", default=os.environ.get("HOTEL_DB", os.path.join("data", "hotel.db")))
    p.add_argument("--no-demo", action="store_true", help="do not load demo data into a new database")
    p.add_argument("--open", action="store_true", help="open the GUI in a web browser")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    server = make_server(args.db, args.host, args.port, seed=not args.no_demo)
    url = f"http://{'localhost' if args.host in ('0.0.0.0', '127.0.0.1') else args.host}:{args.port}"
    print(f"Hotel system running at {url}  (database: {os.path.abspath(args.db)})")
    print("Default logins: admin / admin123   frontdesk / front123 (demo data only)")
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
