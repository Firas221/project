# Security

## Access control

Access is permission-based, with ten roles. Every API route declares an audience and a permission (`hotel/api/controllers`). Services re-check permissions for sensitive operations (defence in depth).

| Role | Portal | Can do (defaults; the administrator can change every role's permissions except their own and the guest's) |
|---|---|---|
| Administrator | `/admin` (and every other staff portal) | Everything: users, roles and permissions, settings, audit log, night audit, voids and refunds, rates, purchasing, backups |
| Manager | `/manager` | Everything the departments do, plus rates and promotions, voids and refunds, purchasing, reports, the audit log and closing the day. Not users, role permissions, settings or backups |
| Front desk staff | `/staff` | Reservations, check-in/out, guests, folios and payments, cashier shift, housekeeping board, maintenance, guest requests, room service, lost & found, reviews |
| Accountant | `/finance` | Reports and VAT report, tax invoices, corporate accounts, cashier shifts and payments; reservations, guests and stock are read-only |
| Chef | `/kitchen` | Order board, menu and recipes, kitchen stock, supply requests, report issues |
| Housekeeping supervisor | `/housekeeping` | The housekeeping board: create, assign and inspect tasks, set room status, lost & found, report issues. No guest or billing data |
| Housekeeper | `/housekeeping` | Own and unassigned cleaning tasks, lost & found, supply requests, report issues |
| Maintenance technician | `/maintenance` | Repair tickets (assign, resolve, take rooms out of order), room list, found items, supply requests |
| Storekeeper | `/store` | Items, receiving and counts, suppliers, purchase orders, approving supply requests |
| Guest | `/` and `/account` | Own bookings only, online booking and cancellation, bill and invoice, room service, requests, reviews, profile, data export and account deletion |

**Object-level checks:**
- Guests can only reach their own reservations. Other guests' records return 404, so their existence isn't revealed.
- Housekeepers can only work on tasks assigned to them, or unassigned ones.
- A maintenance ticket can only be assigned to an active maintenance technician.
- Closing the business day has its own permission (`nightaudit.close`), held by default by the manager and the administrator.
- Cashiers only see their own shifts unless they have report access.
- Room numbers are hidden from guests until check-in.
- Guests can change or cancel only their own bookings, only before the free-cancellation limit, and never a non-refundable one. A change is re-priced by the server at current rates; the browser cannot supply a price.

## Authentication

- **Passwords.** PBKDF2-HMAC-SHA256 with 600,000 iterations and a per-user salt; old hashes are upgraded automatically at sign-in. The policy requires at least 10 characters with upper- and lower-case letters and a digit, rejects common passwords and passwords containing the username.
- **No user enumeration.** Unknown users and wrong passwords get the same message, and unknown users still pay the same hashing cost. Password-reset requests always give the same answer.
- **Lockout.** After 5 failed attempts the account is locked for 15 minutes; an admin can unlock it. On top of that, each IP is limited to 20 sign-ins per minute, and all API traffic and public endpoints are rate-limited per IP.
- **Two-factor authentication.** TOTP codes from an authenticator app, compatible with Google and Microsoft Authenticator. A used code cannot be replayed, and a sign-in attempt is discarded after 5 wrong codes. Administrators can be required to use 2FA (Settings → Security).
- **New accounts.** New and reset accounts get a one-time password and must change it before using anything else.
- **Password reset.** Single-use links valid for 30 minutes. Only a SHA-256 hash of the token is stored, and all sessions are revoked after a reset.
- **E-mail confirmation (guests).** When SMTP is configured, a new guest account can do nothing in the guest portal until its single-use link (48 hours, stored as a hash) is opened. A desk-made guest profile with the same e-mail address, and its bookings, is attached to the account only after confirmation, so registering with someone else's address reveals nothing.

## Sessions

- **Token.** A random 256-bit token in an `HttpOnly`, `SameSite=Strict` cookie, which becomes `__Host-` prefixed and `Secure` over HTTPS. Only its SHA-256 hash is stored.
- **Expiry.** Sessions end after 60 minutes idle, or 12 hours at most. Changing your password signs out your other sessions.
- **Forced sign-out.** Deactivating a user or changing their role signs them out everywhere; admins can also revoke a user's sessions manually.

## Request protection

- **CSRF.** Every state-changing call needs the per-session `X-CSRF-Token` header, and the Origin/Referer must match the host.
- **Strict CSP.** `script-src 'self'` with no inline scripts, `frame-ancestors 'none'`, `object-src 'none'` and `base-uri 'none'`. The other headers sent are `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`, COOP/CORP, and HSTS over HTTPS.
- **Validation.** Every input passes a typed schema: type, length, range, format and allowed values. Unknown fields are dropped, and request bodies are limited to 256 KB and must be JSON.
- **SQL injection.** All SQL is parameterised, and table and column names come only from repository class constants.
- **XSS.** All dynamic text is HTML-escaped in the browser (`esc()`).
- **Files and exports.**
  - Static files are served with path-traversal protection.
  - Errors never leak stack traces.
  - CSV exports neutralise spreadsheet formula injection.
  - Sign-in redirects only allow same-site paths.
  - Room photos must be JPEG, PNG or WebP. The type is read from the file's own bytes, not from what the browser claims; SVG and anything else is refused. Photos are limited to 1.5 MB and 8 per room type, and are served with `nosniff`.
  - Only the photo-upload route accepts bodies above 256 KB (about 2 MB), and only from users who may manage rooms.
- **Backup restore.** Only an administrator can restore, and must enter their password again. The file must be one of the listed backups, pass SQLite's integrity check and be a hotel database of the same or an older version. The current data is backed up first.

## Audit and privacy

- **Audit log.** Every sign-in (successful and failed), lockout, permission change and business action is recorded with the user, time and IP. Scheduled jobs (the automatic night audit, a restore) appear as the user `system`. It can be filtered and exported in Admin → Audit log.
- **One-time links.** Password-reset and e-mail-confirmation links are hidden from the outbox view.
- **Egyptian data protection law (Law 151/2020).** Consent is captured at registration. Guests can export their data and delete their account; staff can export or erase a guest's data on request. Financial records are kept anonymously, as tax law requires.

## Deployment checklist

1. Run behind HTTPS: use `--tls-cert/--tls-key` or the nginx config in `deploy/`. Set `HOTEL_SECURE_COOKIES=1`, plus `HOTEL_TRUST_PROXY=1` only behind your own proxy.
2. Start with `--no-demo` (or `HOTEL_SEED_DEMO=0`), sign in with the printed one-time admin password and change it.
3. Enable 2FA for every administrator, then turn on "Require two-factor authentication for administrators".
4. Configure SMTP so password-reset and booking e-mails are delivered.
5. Keep automatic backups on and copy them off the server (`deploy/backup-offsite.sh`).
6. Restrict file permissions on the `data/` folder (the service unit uses `UMask=0077`).
7. Review the audit log regularly for failed sign-ins and lockouts.
