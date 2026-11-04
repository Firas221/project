# Hotel Manager — Reservations & Inventory

A complete hotel property-management system with a web GUI. It covers the front desk, reservations, guests, rooms, housekeeping, inventory, billing and reports.

It has **no dependencies.** It runs on Python 3.9+ using only the standard library: an HTTP server and SQLite. The GUI is a single-page app in plain JavaScript with no build step.

## Run it

```bash
python3 run.py            # then open http://localhost:8000
python3 run.py --open     # also opens your browser
```

| User | Password | Role |
|------|----------|------|
| `admin` | `admin123` | Administrator |
| `frontdesk` | `front123` | Staff (demo data only) |

**Change these passwords** in Settings before real use.

Options: `--host 0.0.0.0` (serve on your network), `--port 9000`, `--db path/to/hotel.db`, `--no-demo` (start with an empty hotel that has only the admin user). The same options can be set with the environment variables `HOTEL_HOST`, `HOTEL_PORT` and `HOTEL_DB`. All data lives in one SQLite file (default `data/hotel.db`), so to back up, copy that file.

## Features

**Front desk**
- Dashboard: occupancy, in-house guests, arrivals and departures with one-click check-in/out, payments today and this month, room-status summary, low-stock alerts, upcoming arrivals and an activity feed.
- Room calendar (tape chart): rooms × days, colour-coded bookings. Click an empty day to book that room.
- New reservation wizard: pick an existing guest or create one inline, then search live availability by dates, guest count and room type. Choose a room, set the rate and source, and take an optional deposit.
- Double-booking is impossible. Every write runs in a serialized transaction, and stays are checked as `[check_in, check_out)`, so back-to-back stays are allowed.
- Reservation lifecycle: booked → checked in → checked out, or cancelled (optional fee) or no-show (optional fee). You can edit dates, guests and rate, change room, extend a stay, and handle an early departure (the stay is shortened and billed correctly).
- Check-in rules: no future arrivals, and no rooms that are under maintenance or still occupied. A dirty room needs explicit confirmation.
- Check-out requires a settled balance. The final payment can be taken in the check-out dialog, and the room is set to *dirty* automatically.

**Billing**
- Guest folio: room nights, posted charges (inventory items or free-text services and discounts), configurable tax, payments and refunds, and the balance.
- Printable invoice (print or save as PDF).

**Guests**: profiles with VIP flag, ID/passport, notes, stay history and lifetime value.

**Rooms & housekeeping**: room types with rates and capacity, rooms per floor, and a housekeeping board (clean / dirty / maintenance with notes).

**Inventory**
- Items with SKU, category, unit, reorder level, cost, sale price and supplier.
- Receive stock (with weighted-average costing), issue stock, and stock counts/adjustments (a reason is required).
- Full movement ledger and low-stock alerts.
- Posting a chargeable item (e.g. minibar) to a guest folio **deducts it from stock automatically**. Voiding the charge returns it to stock. Stock can never go negative.
- Supplier management.

**Reports**: occupancy, ADR, RevPAR, room and extras revenue, payments by method, booking sources, top-selling items, internal consumption, inventory valuation and a daily chart with a table. CSV export for reservations, guests, items, movements and the daily report.

**Administration**
- Users with roles. *Admin* manages rooms, rates, users, settings and deletions; *staff* run daily operations.
- Hotel settings (name, address, currency, tax rate, check-in/out times).
- Password change and a full activity/audit log.

**Security**
- PBKDF2 password hashing.
- HttpOnly + SameSite=Strict session cookies.
- Login lockout after 5 failed attempts.
- Server-side validation on every field.
- Parameterised SQL.
- Protection against path traversal and CSV formula injection.

## Tests

```bash
python3 -m unittest discover tests
```

The tests start the real server on a temporary database. They exercise the full API: authentication and roles, booking and overlap rules, the check-in/out lifecycle, folio and tax math, inventory movements and stock deduction, reports and exports.

## Project layout

```
run.py              launcher
hotel/db.py         schema + demo data
hotel/api.py        business logic & JSON API
hotel/server.py     HTTP server (API + static GUI)
hotel/auth.py       password hashing
static/             GUI (index.html, app.js, styles.css)
tests/test_api.py   end-to-end API tests
```
