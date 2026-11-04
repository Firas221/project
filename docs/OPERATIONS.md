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
6. **Rooms & rates.** Create room types and rooms. Add seasons (high and low) and any promo codes.
7. **Staff accounts.** Create them under **Users**; each gets a one-time password. Adjust what each role may do under **Roles & permissions**.
8. **Two-factor authentication.** Turn it on under **My security**, then require it for admins in **Settings → Security**.

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
| `HOTEL_SMTP_HOST`, `_PORT`, `_USER`, `_PASSWORD`, `_FROM`, `_STARTTLS` | — | Outgoing e-mail. Without them, mails are kept in the admin outbox |
| `HOTEL_BACKUP_DIR` / `HOTEL_BACKUP_HOURS` / `HOTEL_BACKUP_KEEP` | `data/backups` / `24` / `14` | Automatic backups |
| `HOTEL_SESSION_IDLE_MINUTES` / `HOTEL_SESSION_HOURS` | `60` / `12` | Session lifetime |
| `HOTEL_PBKDF2_ITERATIONS` | `600000` | Password hashing cost |

## Backups and restore

- **Automatic backups.** Every 24 hours a consistent, integrity-checked copy is written to the backup folder (default: keep the newest 14). Admins can also click **Settings → Back up now** or run `python3 run.py --backup-now`.
- **Copies off the server.** Copy backups to another place daily with `deploy/backup-offsite.sh`, or rclone to cloud storage.
- **Restore.** Stop the service, copy a backup file over `hotel.db` (and delete `hotel.db-wal` / `hotel.db-shm` if present), then start the service.

## Daily routine

| When | Who | What |
|---|---|---|
| Morning | Front desk | Open a **cashier shift** with the cash float. Check arrivals and departures on the dashboard. |
| Morning | Housekeeping supervisor | **Generate stay-over tasks** and assign rooms to housekeepers. |
| All day | Housekeepers | Work through "My rooms". Report issues and log found items. |
| All day | Chef | Work the order board. Mark dishes unavailable when ingredients run out. Request supplies. |
| Check-out | Front desk | Settle the folio. The system issues the tax invoice and creates the cleaning task. |
| Evening | Front desk | Print or export the **guest register** for the authorities. Close the cashier shift with a cash count. |
| Night | Administrator | Run the **night audit**: no-shows are posted, the day's figures are locked in, and the business date moves forward. |
| Monthly | Administrator | **Reports → VAT report**. Export it for the tax return. Review the audit log and inventory valuation. |

## Moving to PostgreSQL later

All SQL is inside `hotel/repositories` and `hotel/db`. To scale to several properties or heavy concurrency:
1. Swap `Database` for a PostgreSQL connection pool.
2. Translate the migrations.
3. Adjust a few SQLite-specific functions: `julianday` and `date()`.

The services, API and portals don't change.
