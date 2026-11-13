# Hotel Management System

A complete property-management system for a hotel in Egypt. There is a separate portal for each role:

- administrators
- managers
- front-desk staff
- accountants
- chefs
- housekeeping supervisors and housekeepers
- maintenance technicians
- storekeepers
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
| Housekeeping (supervisor) | http://localhost:8000/housekeeping | `supervisor` / `SuperPass123` |
| Management | http://localhost:8000/manager | `manager` / `ManagerPass123` |
| Accounting | http://localhost:8000/finance | `accountant` / `AccountPass123` |
| Maintenance | http://localhost:8000/maintenance | `tech` / `TechPass123` |
| Store | http://localhost:8000/store | `store` / `StorePass123` |

Everyone signs in at `/login` and is sent to their own portal automatically.

**If the demo logins do not work or there are no rooms**, the server is using a database that is not the demo hotel: one created with `--no-demo` (or by Docker, which starts empty), or one made by an older version before these roles existed. The start-up message says which. To get the full demo hotel, run:

```bash
python3 run.py --fresh-demo
```

The database you had is renamed and kept, not deleted.

**For real use** start with an empty hotel:

```bash
python3 run.py --no-demo
```

It prints a one-time admin password; you must change it at first sign-in. Then read [docs/OPERATIONS.md](docs/OPERATIONS.md) and [docs/SECURITY.md](docs/SECURITY.md).

## What each portal does

**Administrator** has everything below, plus:
- Users, including one-time passwords, unlocking accounts, signing users out everywhere and resetting 2FA.
- The **roles & permissions matrix**, which decides what each of the eight other staff roles may do.
- Hotel, tax and security settings.
- Audit log and e-mail outbox.
- Night audit (by hand, or automatically at a set time), backups and one-click restore.
- Room types with photos, rates, seasons, promo codes and **rate plans** (breakfast, half or full board; non-refundable rates).
- Purchasing, refunds and voids.

**Manager** runs the hotel day to day: every department's screens, rates and promotions, voids and refunds, purchasing, reports, the audit log and closing the day. Users, role permissions, settings and backups stay with the administrator.

**Accountant**
- Reports, the VAT report and exports, tax invoices, corporate accounts (city ledger) and cashier shifts.
- Reservations, guests and stock value are visible but cannot be changed.

**Housekeeping supervisor** runs the housekeeping board: creates and assigns cleaning tasks, inspects finished rooms, sets room status, handles lost & found.

**Maintenance technician** works the repair tickets (those assigned to them are marked), takes rooms out of order and back, and requests parts from the store.

**Storekeeper** keeps the stock: items, receiving, counts, suppliers, purchase orders, and approving the departments' supply requests.

**Front desk**
- Dashboard: arrivals, departures, occupancy and payments.
- Room calendar.
- Booking wizard: live availability and pricing, rate plans, corporate rates, promo codes and deposits.
- Long lists (reservations, guests, invoices) are paged, and the dashboard, housekeeping board and guest requests refresh by themselves.
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
- "My rooms" task cards, plus unassigned rooms they can take. Stay-over cleaning tasks can be created automatically every morning.
- Start → mark clean.
- Report a maintenance issue, log found items, request supplies, see completed work.

**Guest**
- On the website: see room photos, search dates, choose a rate (room only, with meals, or a cheaper non-refundable rate), see prices including 12% service and 14% VAT, use promo codes, and book online. The room is assigned automatically.
- New accounts confirm their e-mail address with a link before they can book (once outgoing e-mail is set up).
- In their account:
  - See, **change** (dates, guests or room type, with the new price shown first) and cancel bookings, within the free-cancellation window.
  - View their bill and download the tax invoice.
  - During the stay, order room service and send requests (towels, cleaning, maintenance, wake-up).
  - Review the stay afterwards.
  - Edit their profile, download their data, or delete their account.
- E-mails (confirmation, changes, a reminder before arrival, invoice) arrive in the guest's language, English or Arabic.

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

There are 97 Python tests. They start the real server on a temporary database and cover:
- security: sign-in, lockout, sessions, CSRF, cross-site requests, the full role matrix for all ten roles, guests' data isolation, 2FA, password reset, e-mail confirmation, privacy erasure, path traversal, SQL injection, CSV injection, photo-upload checks;
- every workflow across departments, plus backup restore, the scheduled jobs (night audit, stay-over tasks, arrival reminders), rate plans, paging and e-mail language;
- unit tests for validation, the tax maths and the TOTP test vectors.

There are also 27 browser tests that drive the real portals in headless Chromium: every screen of every staff portal for every role, the Arabic right-to-left mode (including messages from the server), photo upload, the delete buttons, backup restore, online booking with rate plans, guests changing a booking, paged lists, self-refreshing screens and e-mail confirmation. They are the only part of the project that needs Node.js:

```bash
npm install && npx playwright install chromium    # once
npm run test:browser
```

Both suites run on every push (`.github/workflows/tests.yml`).

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): how the code is organised and how to add features.
- [docs/SECURITY.md](docs/SECURITY.md): roles, protections and the deployment checklist.
- [docs/OPERATIONS.md](docs/OPERATIONS.md): going live, HTTPS, e-mail, backups, daily routines.
