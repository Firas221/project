# Architecture

The system is a layered, object-oriented application. Each layer has one job and only talks to the layer directly below it. That makes any piece easy to find, test and change.

```
 Browser portals (static/)            Admin · Front desk · Kitchen · Housekeeping · Guest site & account
        │  JSON over HTTPS (session cookie + CSRF header)
 ┌──────▼─────────────────────────────────────────────────────────────────────────────┐
 │ hotel/http       RequestHandler — parses HTTP, serves portal pages, adds security   │
 │                  headers (CSP, HSTS, X-Frame-Options …)                              │
 │ hotel/api        Dispatcher — one pipeline for every API call:                      │
 │                  rate limit → route → body checks → transaction → session →         │
 │                  restricted-account gate → RBAC → CSRF/Origin → controller          │
 │                  Router + Controllers — declare URL, audience and permission         │
 ├────────────────────────────────────────────────────────────────────────────────────┤
 │ hotel/services   Business rules (one class per domain), validation schemas,         │
 │                  audit logging. Services collaborate inside one transaction.        │
 ├────────────────────────────────────────────────────────────────────────────────────┤
 │ hotel/repositories  All SQL lives here. One repository class per table/aggregate.  │
 │ hotel/db         Database (connections, unit of work, migrations), seed data       │
 ├────────────────────────────────────────────────────────────────────────────────────┤
 │ hotel/core       Cross-cutting: errors, validation, permissions/roles, security    │
 │                  (hashing, tokens, rate limiter), TOTP, clock                       │
 │ hotel/infrastructure  Background jobs: e-mail delivery, automatic backups           │
 └────────────────────────────────────────────────────────────────────────────────────┘
```

`hotel/app.py` (`HotelApp`) is the **composition root**: it builds the config, database, password hasher, rate limiter, router, dispatcher and background jobs, and hands them to each other.

## Folder map

| Path | What is inside |
|---|---|
| `hotel/config.py` | `Config` — every setting, read from `HOTEL_*` environment variables |
| `hotel/core/errors.py` | `AppError` hierarchy → HTTP status codes |
| `hotel/core/validation.py` | Declarative `Schema` / `Field` classes (`Str`, `Email`, `Money`, `Date`, `ListOf` …) |
| `hotel/core/permissions.py` | `Role`, `Perm`, permission catalog, default role permissions, `Principal` |
| `hotel/core/security.py` | `PasswordHasher` (PBKDF2), `PasswordPolicy`, `Tokens`, `RateLimiter` |
| `hotel/core/totp.py` | RFC 6238 one-time codes for two-factor authentication |
| `hotel/db/schema.py`, `schema_v2.py` … `schema_v4.py` | Versioned migrations (append-only) |
| `hotel/db/database.py` | `Database.unit_of_work()` — `BEGIN IMMEDIATE` … `COMMIT`/`ROLLBACK` |
| `hotel/db/seed.py` | Roles, Egyptian default settings, first admin, demo hotel |
| `hotel/repositories/base.py` | `BaseRepository` (generic CRUD with column whitelists), `QueryBuilder` |
| `hotel/repositories/*.py` | identity, rooms, guests, reservations, inventory, kitchen, operations, finance |
| `hotel/services/*.py` | auth, admin, front_office, reservations, billing, inventory, kitchen, operations, reports, portal, notifications |
| `hotel/api/router.py` | `@get/@post/@put/@delete` decorators, `Controller`, `Router` |
| `hotel/api/dispatcher.py` | The security pipeline described above |
| `hotel/api/controllers/*.py` | Thin HTTP adapters that call services |
| `static/js/core/` | `api.js` (fetch + CSRF), `ui.js` (escaping, modal, tables …), `shell.js` (portal frame, router, 2FA setup), `i18n.js` + `ar.js` (Arabic for the staff portals) |
| `static/js/views/` | Screens grouped by department |
| `static/js/portals/` | `catalog.js` (every staff screen, defined once) and `portals.js` (which screens each portal shows) |
| `static/js/site/` | Public website, sign-in/registration, guest account, English/Arabic strings |
| `tests/` | Unit, security and end-to-end workflow tests against the real server; `tests/browser/` drives the portals in Chromium |

## Request lifecycle (example: front desk checks a guest out)

1. **Browser.** `POST /api/reservations/42/checkout` is sent with the session cookie and `X-CSRF-Token`.
2. **Dispatcher.**
   - Checks the rate limit and finds the route.
   - Validates the JSON body and Origin.
   - Opens a write transaction.
   - Resolves the session (idle and absolute expiry).
   - Checks the route's permission (`frontdesk.checkin`) and the CSRF token.
3. **`ReservationController.check_out`** calls `ReservationService.check_out`.
4. **The service applies the rules.** No open room-service orders. Early departure shortens the stay. The balance is settled, or moved to the company ledger.
5. **It then hands off to the other departments.** It marks the room dirty, creates a housekeeping task, issues a numbered **tax invoice** (`InvoiceService`) and queues a receipt e-mail (`NotificationService`).
6. **Audit.** Every step writes to the audit log. The transaction commits, or rolls back as a whole on any error.

## Adding a feature

1. **Schema:** append a migration to `hotel/db/` and register it in `MIGRATIONS`.
2. **Data access:** add a repository class, then expose it in `repositories/__init__.py`.
3. **Rules:** add a service method that validates with a `Schema`, calls `self.require(Perm.X)` and `self.audit(...)`.
4. **API:** add a controller method with `@post("/path", perm=Perm.X)` and register the controller in `controllers/__init__.py`.
5. **Permission:** if it is new, add it to `Perm`, `PERMISSION_CATALOG` and `DEFAULT_ROLE_PERMISSIONS`. It appears in the admin matrix automatically.
   **Role:** to add a role, add it to `Role` (name, label, portal) and `DEFAULT_ROLE_PERMISSIONS` in `core/permissions.py`, to `ROLE_OPTIONS` in `views/admin.js`, and give it a portal in `portals/portals.js` (plus a page in `static/` and `PAGES` in `http/server.py` if the portal is new). Existing databases pick the role up at the next start.
6. **UI:** add a view in `static/js/views/`, list it in `portals/catalog.js` and add its key to the portals that should show it.
7. **Arabic:** add any new on-screen phrase to `static/js/core/ar.js` (staff portals) or `static/js/site/i18n.js` (guest pages).
8. **Tests:** add a test in `tests/`.

## Lists and background jobs

- **Paging.** List endpoints return the whole list by default. With `?page=2&per_page=50` they return `{items, total, page, per_page, pages}` instead (`page_of` in `repositories/base.py`). Screens that can grow without limit — reservations, guests, audit log, stock ledger, invoices — always ask for a page. CSV exports are never paged.
- **Self-refreshing screens.** A screen marked `live: <seconds>` in `portals/catalog.js` reloads its data on that interval (`Router.keepFresh` in `core/shell.js`), except while a dialog is open, a field in the screen has focus, or the tab is hidden.
- **Scheduled jobs.** `HotelApp._loop` runs every 15 seconds: e-mail delivery, backups, the automatic night audit, the daily stay-over tasks and arrival reminders. Each job reads its settings first and only opens a write transaction when there is work to do. They act as the user `system`.

## Languages

- **Guest pages** (website, sign-in, guest account) use keyed strings: `t('book')` looks the phrase up in `static/js/site/i18n.js`.
- **Staff portals** are written in English only. In Arabic mode `core/i18n.js` replaces each interface phrase with its entry in `core/ar.js` as it appears on screen (including dialogs, placeholders and messages) and switches the page to right-to-left. Phrases containing names or numbers are matched by the patterns at the end of `ar.js`. Hotel data is never in the dictionary, so guest names, room numbers and notes are shown as entered.
- The same overlay runs on the guest pages, so status labels and messages from the server appear in Arabic there too.
- The server always answers in English; its messages are in `ar.js` like any other phrase (with patterns for the ones that contain a room number, a field name and so on). A phrase that is missing from `ar.js` simply stays in English.
- E-mails are written on the server, in `hotel/services/notifications.py`, with one English and one Arabic text per message.

## Key design decisions

- **Derived, not stored.** Occupancy, folio totals, balances and low-stock flags are computed from source records, so they can never drift.
- **Serialised writes.** `BEGIN IMMEDIATE` makes availability checks and stock deduction race-free: no double bookings and no negative stock.
- **Immutable invoices.** At check-out a complete snapshot (lines, taxes, payments, hotel details) is stored with a sequential number.
- **Zero runtime dependencies.** Python standard library and SQLite only, so there is no supply-chain risk and setup is trivial. The data layer is isolated in repositories, so moving to PostgreSQL later only touches `hotel/db` and `hotel/repositories`.
