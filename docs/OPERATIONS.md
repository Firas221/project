# Operations guide

## Going live

1. **Server.** Any small Linux VPS works (1 vCPU / 1 GB RAM is plenty for one hotel). Copy the project to `/opt/hotel`.
2. **Start with an empty hotel.** Run `python3 run.py --no-demo` once and note the one-time admin password.
3. **HTTPS.** Choose one:
   - **nginx + Let's Encrypt (recommended).** Install `deploy/nginx.conf`, run `certbot --nginx`, and use `deploy/hotel.service` for systemd.
   - **Docker.** Run `docker compose -f deploy/docker-compose.yml up -d --build`, behind nginx, Caddy or a cloud load balancer.
   - **Built-in TLS.** Run `python3 run.py --host 0.0.0.0 --port 443 --tls-cert fullchain.pem --tls-key privkey.pem`.
4. **Configuration.** Copy `deploy/hotel.env.example` to `deploy/hotel.env` and set the public URL and SMTP.
5. **Admin settings.** Sign in as `admin`, change the password, then go to **Settings**:
   - hotel name in English and Arabic, address, contact details;
   - tax registration number, commercial register and tourism licence;
   - check-in/out times, weekend uplift and the online-booking policy.
6. **Rooms & rates.** Create room types and rooms, and add photos to each room type (**Rooms & rates → Room types → Photos**); the first photo is the one shown on the booking website. Add seasons (high and low) and any promo codes.
7. **Staff accounts.** Create them under **Users**; each gets a one-time password. Adjust what each role may do under **Roles & permissions**.
8. **Two-factor authentication.** Turn it on under **My security**, then require it for admins in **Settings → Security**.
9. **Night audit.** Either run it by hand each night, or turn on **Settings → Operations → Run the night audit automatically** and choose the time.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `HOTEL_DB` | `data/hotel.db` | Database file |
| `HOTEL_HOST` / `HOTEL_PORT` | `127.0.0.1` / `8000` | Listen address |
| `HOTEL_SEED_DEMO` | `1` | Load demo data into a new database |
| `HOTEL_TLS_CERT` / `HOTEL_TLS_KEY` | — | Serve HTTPS directly |
| `HOTEL_SECURE_COOKIES` | `0` | Set to `1` when users reach the site over HTTPS |
| `HOTEL_TRUST_PROXY` | `0` | Use `X-Forwarded-For` (only behind your own proxy) |
| `HOTEL_PUBLIC_URL` | — | Used in e-mail links |
| `HOTEL_ALLOWED_ORIGINS` | — | Extra trusted origins (comma-separated) |
| `HOTEL_SMTP_HOST`, `_PORT`, `_USER`, `_PASSWORD`, `_FROM`, `_STARTTLS` | — | Outgoing e-mail. Without them, mails are kept in the admin outbox and new guests are not asked to confirm their address |
| `HOTEL_BACKUP_DIR` / `HOTEL_BACKUP_HOURS` / `HOTEL_BACKUP_KEEP` | `data/backups` / `24` / `14` | Automatic backups |
| `HOTEL_SESSION_IDLE_MINUTES` / `HOTEL_SESSION_HOURS` | `60` / `12` | Session lifetime |
| `HOTEL_PBKDF2_ITERATIONS` | `600000` | Password hashing cost |

## Backups and restore

- **Automatic backups.** Every 24 hours a consistent, integrity-checked copy is written to the backup folder (default: keep the newest 14). Admins can also click **Settings → Back up now** or run `python3 run.py --backup-now`.
- **Copies off the server.** Copy backups to another place daily with `deploy/backup-offsite.sh`, or rclone to cloud storage.
- **Restore.** Either way, the data being replaced is saved first as a new backup, so a restore can be undone by restoring that one.
  - *From the admin portal:* **Settings → Backups → Restore** next to the backup, then confirm with your password. Everyone is signed out and signs in again.
  - *From the command line:* `python3 run.py --restore hotel-20260101-030000.db` (a file name from the backup folder, or a full path). This works whether or not the service is running; restart the service afterwards so everyone signs in again.
  - A backup from an older version is upgraded automatically. A backup from a newer version is refused.

## Monitoring

`GET /api/health` answers `{"status": "ok", "schema": 3}` when the server and its database are working. Point your uptime monitor or load balancer at it; the Docker image already uses it as its health check.

## E-mail confirmation for guests

Once SMTP is configured, a guest who registers gets a link (valid 48 hours) and must open it before using their account. Until then they only see a "confirm your e-mail" page with a button to send the link again. Bookings made at the desk under the same e-mail address join the guest's account at that moment, not before. To turn the requirement off, untick **Settings → Security → Guests must confirm their e-mail address**.

## Daily routine

| When | Who | What |
|---|---|---|
| Morning | Front desk | Open a **cashier shift** with the cash float. Check arrivals and departures on the dashboard. |
| Morning | Housekeeping supervisor | **Generate stay-over tasks** and assign rooms to housekeepers. |
| All day | Housekeepers | Work through "My rooms". Report issues and log found items. |
| All day | Chef | Work the order board. Mark dishes unavailable when ingredients run out. Request supplies. |
| Check-out | Front desk | Settle the folio. The system issues the tax invoice and creates the cleaning task. |
| Evening | Front desk | Print or export the **guest register** for the authorities. Close the cashier shift with a cash count. |
| Night | Administrator | Run the **night audit**: no-shows are posted, the day's figures are locked in, and the business date moves forward. With the automatic night audit on, this happens by itself at the time you set (a time before noon closes the previous day; days missed while the server was off are caught up). |
| Monthly | Administrator | **Reports → VAT report**. Export it for the tax return. Review the audit log and inventory valuation. |

## Moving to PostgreSQL later

All SQL is inside `hotel/repositories` and `hotel/db`. To scale to several properties or heavy concurrency:
1. Swap `Database` for a PostgreSQL connection pool.
2. Translate the migrations.
3. Adjust a few SQLite-specific functions: `julianday` and `date()`.

The services, API and portals don't change.
