# Hotel Management System

A complete property-management system for a hotel in Egypt. There is a separate portal for each role:

- administrators
- front-desk staff
- chefs
- housekeepers
- guests (a public booking website, plus a guest account)

Every portal works in **English and Arabic** (right-to-left); each person switches with one click and the choice is remembered.

It needs nothing except **Python 3.9+**: no packages to install and no database server. The data lives in one SQLite file.

## Quick start

```bash
python3 run.py            # http://localhost:8000  (with a demo hotel)
python3 run.py --open     # also opens your browser
```

| Portal | URL | Demo login |
|---|---|---|
| Guest website (book online, English/Arabic) | http://localhost:8000/ | — |
| Guest account | http://localhost:8000/account | `amelia.hart@example.com` / `GuestPass123` |
| Administration (controls everything) | http://localhost:8000/admin | `admin` / `AdminPass123` |
| Front desk | http://localhost:8000/staff | `frontdesk` / `FrontDesk123` |
| Kitchen (chef) | http://localhost:8000/kitchen | `chef` / `ChefPass123` |
| Housekeeping (maids) | http://localhost:8000/housekeeping | `maid` / `MaidPass123` (also `maid2`) |

Everyone signs in at `/login` and is sent to their own portal automatically.

**For real use** start with an empty hotel:

```bash
python3 run.py --no-demo
```

It prints a one-time admin password; you must change it at first sign-in. Then read [docs/OPERATIONS.md](docs/OPERATIONS.md) and [docs/SECURITY.md](docs/SECURITY.md).

## What each portal does

**Administrator** has everything below, plus:
- Users, including one-time passwords, unlocking accounts, signing users out everywhere and resetting 2FA.
- The **roles & permissions matrix**, which decides what staff, chefs and housekeepers may do.
- Hotel, tax and security settings.
- Audit log and e-mail outbox.
- Night audit (by hand, or automatically at a set time), backups and one-click restore.
- Room types with photos, rates, seasons and promo codes.
- Purchasing, refunds and voids.

**Front desk**
- Dashboard: arrivals, departures, occupancy and payments.
- Room calendar.
- Booking wizard: live availability and pricing, corporate rates, promo codes and deposits.
- Group bookings.
- Check-in, with the passport/ID details Egypt requires for guest registration.
- Check-out, which issues a numbered tax invoice and sends the room to housekeeping.
- Early departure, room moves and folio charges (minibar items come out of stock).
- Payments, cashier shifts with cash count, corporate accounts (city ledger) and invoices.
- Guest profiles, the police guest register, guest requests, lost & found and review moderation.

**Chef**
- Live order board (new → cooking → ready → delivered). Starting an order deducts its recipe ingredients from stock, and delivering it charges the guest's bill.
- Menu & recipes, with dishes marked as unavailable when needed.
- Kitchen stock, supply requests to the store, and reporting issues.

**Housekeeper**
- "My rooms" task cards, plus unassigned rooms they can take.
- Start → mark clean.
- Report a maintenance issue, log found items, request supplies, see completed work.

**Guest**
- On the website: see room photos, search dates, see prices including 12% service and 14% VAT, use promo codes, and book online. The room is assigned automatically.
- New accounts confirm their e-mail address with a link before they can book (once outgoing e-mail is set up).
- In their account:
  - See and cancel bookings, within the free-cancellation window.
  - View their bill and download the tax invoice.
  - During the stay, order room service and send requests (towels, cleaning, maintenance, wake-up).
  - Review the stay afterwards.
  - Edit their profile, download their data, or delete their account.

## Built for Egypt

- **Currency and taxes.** Prices are in EGP. Every bill and invoice adds the **12% service charge** first, then **14% VAT** on subtotal + service. An optional city tax can be added.
- **Tax invoices.** Numbered in sequence (`INV-2026-000001`), in Arabic and English, with your tax registration and commercial register numbers. A VAT report and CSV export cover the monthly return.
- **Guest registration.** Nationality and ID/passport number are required before check-in. A daily **guest register** for the authorities lists foreign guests by default, with Egyptian nationals as an option, and can be printed or exported to CSV.
- **Pricing.** A Friday/Saturday weekend uplift, seasonal rates with minimum stays, promo codes and corporate discounts.
- **Data protection.** Built to Egypt's Personal Data Protection Law (151/2020): consent, data export, erasure and a privacy notice at `/privacy`.

> Integration with the Egyptian Tax Authority's e-invoice / e-receipt system needs your ETA credentials and isn't connected yet. The invoice data is stored in a structure ready for it. Online card payments (e.g. Paymob) and Booking.com/Expedia connections likewise need accounts with those companies. Payments are recorded at the desk today.

## Tests

```bash
cd tests && python3 -m unittest -v
```

There are 70 Python tests. They start the real server on a temporary database and cover:
- security: sign-in, lockout, sessions, CSRF, cross-site requests, the full role matrix, guests' data isolation, 2FA, password reset, e-mail confirmation, privacy erasure, path traversal, SQL injection, CSV injection, photo-upload checks;
- every workflow across departments, plus backup restore and the scheduled night audit;
- unit tests for validation, the tax maths and the TOTP test vectors.

There are also 12 browser tests that drive the real portals in headless Chromium: every screen of every staff portal, the Arabic right-to-left mode, photo upload, the delete buttons, backup restore, online booking and e-mail confirmation. They are the only part of the project that needs Node.js:

```bash
npm install && npx playwright install chromium    # once
npm run test:browser
```

Both suites run on every push (`.github/workflows/tests.yml`).

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): how the code is organised and how to add features.
- [docs/SECURITY.md](docs/SECURITY.md): roles, protections and the deployment checklist.
- [docs/OPERATIONS.md](docs/OPERATIONS.md): going live, HTTPS, e-mail, backups, daily routines.
