"""Tests for e-mail verification, room photos, deletions, backup restore, the scheduled night audit and health."""
import base64
import datetime as dt
import re
import sqlite3
import struct
import zlib

from support import AppTestCase, d  # first: puts the project on sys.path

from hotel.db.database import Database  # noqa: E402
from hotel.services.front_office import sniff_image  # noqa: E402


def png(width=2, height=2) -> bytes:
    """A tiny valid PNG, built by hand so the tests need no imaging library."""
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    rows = b"".join(b"\x00" + b"\x1f\x5f\xbf" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


class EmailVerificationTests(AppTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.app.config.smtp_host = "smtp.invalid"   # "e-mail is configured"; nothing is sent because no mail job runs

    def _token(self, email):
        db = sqlite3.connect(self.app.config.db_path)
        body = db.execute("SELECT body FROM email_outbox WHERE to_address=? AND subject LIKE 'Confirm%' ORDER BY id DESC LIMIT 1",
                          (email,)).fetchone()[0]
        db.close()
        return re.search(r"#verify=([A-Za-z0-9_\-]+)", body).group(1)

    def _register(self, email, password="Verify-Me-2026"):
        c = self.client()
        r = c.ok("POST", "/api/auth/register", {"first_name": "Vera", "last_name": "Fy", "email": email,
                                                "password": password, "accept_privacy": True})
        c.csrf = r["csrf_token"]
        return c, r

    def test_unverified_guest_is_gated_until_link_is_opened(self):
        c, r = self._register("vera@example.com")
        self.assertTrue(r["user"]["must_verify_email"])
        self.assertEqual(c.req("GET", "/api/portal/reservations")[0], 403)
        self.assertEqual(c.req("GET", "/api/portal/profile")[0], 403)
        self.assertEqual(self.client().req("POST", "/api/auth/verify-email", {"token": "bogus"})[0], 400)
        token = self._token("vera@example.com")
        self.client().ok("POST", "/api/auth/verify-email", {"token": token})   # works from any browser
        self.assertEqual(self.client().req("POST", "/api/auth/verify-email", {"token": token})[0], 400)  # single use
        self.assertFalse(c.ok("GET", "/api/auth/me")["user"]["must_verify_email"])
        c.ok("GET", "/api/portal/reservations")
        self.assertEqual(c.req("POST", "/api/auth/verify-email/resend")[0], 409)

    def test_resend_replaces_the_old_link(self):
        c, _ = self._register("resend@example.com")
        first = self._token("resend@example.com")
        c.ok("POST", "/api/auth/verify-email/resend")
        second = self._token("resend@example.com")
        self.assertNotEqual(first, second)
        self.assertEqual(self.client().req("POST", "/api/auth/verify-email", {"token": first})[0], 400)
        self.client().ok("POST", "/api/auth/verify-email", {"token": second})

    def test_existing_bookings_join_the_account_only_after_verification(self):
        desk = self.client("frontdesk")
        res = self.book(desk, 40, 42, guest={"first_name": "Walk", "last_name": "In", "email": "walkin@example.com",
                                             "nationality": "French", "id_number": "FR99"})
        # Someone registers with that guest's address: they must not see the booking yet.
        c, _ = self._register("walkin@example.com")
        self.assertEqual(c.req("GET", "/api/portal/reservations")[0], 403)
        self.client().ok("POST", "/api/auth/verify-email", {"token": self._token("walkin@example.com")})
        mine = c.ok("GET", "/api/portal/reservations")
        self.assertEqual([r["code"] for r in mine], [res["code"]])
        # the two profiles were merged into one, keeping the ID details taken at the desk
        profiles = self.client("admin").ok("GET", "/api/guests?q=walkin@example.com")
        self.assertEqual(len(profiles), 1)
        self.assertEqual(profiles[0]["id_number"], "FR99")

    def test_links_are_hidden_in_the_outbox_and_setting_can_turn_it_off(self):
        self._register("hidden@example.com")
        admin = self.client("admin")
        self.assertTrue(all("#verify=" not in m["body"] for m in admin.ok("GET", "/api/outbox")))
        admin.ok("PUT", "/api/settings", {"require_email_verification": False})
        try:
            c, r = self._register("free@example.com")
            self.assertFalse(r["user"]["must_verify_email"])
            c.ok("GET", "/api/portal/reservations")
        finally:
            admin.ok("PUT", "/api/settings", {"require_email_verification": True})

    def test_staff_and_existing_guests_are_not_affected(self):
        self.assertFalse(self.client().login("amelia.hart@example.com")["must_verify_email"])
        self.assertFalse(self.client().login("frontdesk")["must_verify_email"])


class RoomPhotoTests(AppTestCase):
    def _upload(self, c, type_id, raw):
        return c.req("POST", f"/api/room-types/{type_id}/photos", {"data": base64.b64encode(raw).decode()})

    def _refused(self, c, path, body) -> bool:
        """True when the server refuses an oversized body: with 413, or by hanging up before reading it all."""
        try:
            return c.req("POST", path, body)[0] == 413
        except (BrokenPipeError, ConnectionResetError):
            return True

    def test_sniffing(self):
        self.assertEqual(sniff_image(png()), "image/png")
        self.assertEqual(sniff_image(b"\xff\xd8\xff\xe0rest"), "image/jpeg")
        self.assertEqual(sniff_image(b"RIFF\x00\x00\x00\x00WEBPVP8 "), "image/webp")
        self.assertIsNone(sniff_image(b"<svg onload=alert(1)>"))
        self.assertIsNone(sniff_image(b"GIF89a"))

    def test_upload_serve_cover_delete(self):
        admin = self.client("admin")
        t = admin.ok("GET", "/api/room-types")[0]
        self.assertEqual(t["photos"], [])
        status, first = self._upload(admin, t["id"], png())
        self.assertEqual(status, 201)
        second = self._upload(admin, t["id"], png(3, 3))[1]
        anon = self.client()
        status, _ = anon.req("GET", f"/api/public/photos/{first['id']}")
        self.assertEqual(status, 200)
        headers = {k.lower(): v for k, v in anon.last_headers.items()}
        self.assertEqual(headers["content-type"], "image/png")
        self.assertIn("max-age", headers["cache-control"])
        self.assertEqual(headers["x-content-type-options"], "nosniff")
        info = next(x for x in anon.ok("GET", "/api/public/info")["room_types"] if x["id"] == t["id"])
        self.assertEqual(info["photos"], [first["id"], second["id"]])
        admin.ok("POST", f"/api/room-photos/{second['id']}/cover")
        info = next(x for x in anon.ok("GET", "/api/public/info")["room_types"] if x["id"] == t["id"])
        self.assertEqual(info["photos"], [second["id"], first["id"]])
        admin.ok("DELETE", f"/api/room-photos/{first['id']}")
        self.assertEqual(anon.req("GET", f"/api/public/photos/{first['id']}")[0], 404)

    def test_rejections(self):
        admin = self.client("admin")
        tid = admin.ok("GET", "/api/room-types")[0]["id"]
        self.assertEqual(self._upload(admin, tid, b"<svg xmlns='http://www.w3.org/2000/svg'/>")[0], 400)   # not an image
        self.assertEqual(admin.req("POST", f"/api/room-types/{tid}/photos", {"data": "not base64 !!"})[0], 400)
        self.assertEqual(self._upload(admin, tid, png() + b"\x00" * 1_600_000)[0], 400)                    # too large
        too_big = {"data": base64.b64encode(png() + b"\x00" * 3_000_000).decode()}
        self.assertTrue(self._refused(admin, f"/api/room-types/{tid}/photos", too_big))                    # over the wire limit
        self.assertEqual(self._upload(self.client("frontdesk"), tid, png())[0], 403)
        # the larger limit applies to the upload route only
        self.assertTrue(self._refused(admin, "/api/guests", {"notes": "x" * 400_000}))

    def test_limit_per_type_and_cascade(self):
        admin = self.client("admin")
        t = admin.ok("POST", "/api/room-types", {"name": "Photo Test", "base_rate": 100, "capacity": 2})
        for _ in range(8):
            self.assertEqual(self._upload(admin, t["id"], png())[0], 201)
        self.assertEqual(self._upload(admin, t["id"], png())[0], 409)
        pid = admin.ok("GET", "/api/room-types")
        pid = next(x for x in pid if x["id"] == t["id"])["photos"][0]
        admin.ok("DELETE", f"/api/room-types/{t['id']}")
        self.assertEqual(self.client().req("GET", f"/api/public/photos/{pid}")[0], 404)   # photos go with the type


class DeletionTests(AppTestCase):
    def test_promo_delete(self):
        admin = self.client("admin")
        p = admin.ok("POST", "/api/promos", {"code": "GONE5", "discount_pct": 5, "valid_from": d(-1), "valid_to": d(30)})
        self.assertEqual(self.client("frontdesk").req("DELETE", f"/api/promos/{p['id']}")[0], 403)
        admin.ok("DELETE", f"/api/promos/{p['id']}")
        self.assertNotIn("GONE5", [x["code"] for x in admin.ok("GET", "/api/promos")])
        self.assertEqual(admin.req("DELETE", f"/api/promos/{p['id']}")[0], 404)
        ci, co = d(20), d(22)
        tid = admin.ok("GET", "/api/room-types")[0]["id"]
        self.assertEqual(admin.req("GET", f"/api/quote?room_type_id={tid}&check_in={ci}&check_out={co}&promo_code=GONE5")[0], 400)

    def test_guest_room_type_and_season_delete_rules(self):
        admin = self.client("admin")
        g = admin.ok("POST", "/api/guests", {"first_name": "No", "last_name": "Stays"})
        admin.ok("DELETE", f"/api/guests/{g['id']}")
        booked = self.book(admin, 50, 52)
        self.assertEqual(admin.req("DELETE", f"/api/guests/{booked['guest_id']}")[0], 409)   # has a reservation
        used = admin.ok("GET", "/api/room-types")[0]
        self.assertEqual(admin.req("DELETE", f"/api/room-types/{used['id']}")[0], 409)       # rooms still use it
        s = admin.ok("POST", "/api/seasons", {"name": "Temp", "start_date": d(60), "end_date": d(70), "adjust_pct": 10})
        admin.ok("DELETE", f"/api/seasons/{s['id']}")
        self.assertNotIn(s["id"], [x["id"] for x in admin.ok("GET", "/api/seasons")])


class BackupRestoreTests(AppTestCase):
    def test_restore_brings_back_deleted_data_and_keeps_a_safety_copy(self):
        admin = self.client("admin")
        g = admin.ok("POST", "/api/guests", {"first_name": "Keep", "last_name": "Me"})
        backup = admin.ok("POST", "/api/backups")["file"]
        admin.ok("DELETE", f"/api/guests/{g['id']}")
        admin.ok("POST", "/api/guests", {"first_name": "Made", "last_name": "Later"})
        self.assertEqual(admin.req("POST", "/api/backups/restore", {"file": backup, "password": "wrong"})[0], 400)
        self.assertEqual(admin.req("POST", "/api/backups/restore", {"file": "../test.db", "password": "AdminPass123"})[0], 404)
        self.assertEqual(self.client("frontdesk").req("POST", "/api/backups/restore", {"file": backup})[0], 403)
        result = admin.ok("POST", "/api/backups/restore", {"file": backup, "password": "AdminPass123"})
        self.assertEqual(result["restored"], backup)
        admin = self.client("admin")   # sessions come from the backup, so sign in again
        names = [x["last_name"] for x in admin.ok("GET", "/api/guests?q=Me")]
        self.assertIn("Me", names)
        self.assertFalse(admin.ok("GET", "/api/guests?q=Later"))
        self.assertIn(result["safety_backup"], [b["file"] for b in admin.ok("GET", "/api/backups")])
        self.assertTrue(any(a["action"] == "backup_restored" for a in admin.ok("GET", "/api/audit")))
        # the safety copy still holds what was there just before the restore
        safety = sqlite3.connect(f"{self.app.config.backup_dir}/{result['safety_backup']}")
        self.assertEqual(safety.execute("SELECT COUNT(*) FROM guests WHERE last_name='Later'").fetchone()[0], 1)
        safety.close()

    def test_rejects_files_that_are_not_backups(self):
        import os
        os.makedirs(self.app.config.backup_dir, exist_ok=True)
        junk = os.path.join(self.app.config.backup_dir, "hotel-19990101-000000.db")
        with open(junk, "wb") as f:
            f.write(b"this is not a database")
        admin = self.client("admin")
        status, err = admin.req("POST", "/api/backups/restore", {"file": "hotel-19990101-000000.db", "password": "AdminPass123"})
        self.assertEqual(status, 400)
        self.assertIn("not a hotel database", err["error"])
        admin.ok("GET", "/api/guests")   # the live data is untouched and the session still works
        os.remove(junk)


class ScheduledNightAuditTests(AppTestCase):
    def _at(self, day_offset, clock):
        h, m = map(int, clock.split(":"))
        return dt.datetime.combine(dt.date.today() + dt.timedelta(days=day_offset), dt.time(h, m))

    def _rewind_business_date(self, iso):
        db = sqlite3.connect(self.app.config.db_path)
        db.execute("UPDATE settings SET value=? WHERE key='business_date'", (iso,))
        db.commit()
        db.close()

    def test_schedule(self):
        admin = self.client("admin")
        run = self.app.run_scheduled_night_audit
        self.assertEqual(run(self._at(1, "04:00")), [])                  # off by default: nothing happens
        self.assertEqual(admin.req("PUT", "/api/settings", {"night_audit_time": "25:00"})[0], 400)
        # an evening time closes the same day
        admin.ok("PUT", "/api/settings", {"auto_night_audit": True, "night_audit_time": "23:30"})
        late = self.book(admin, 0, 2)                                    # arrives today and never shows up
        self.assertEqual(run(self._at(0, "23:29")), [])
        self.assertEqual(run(self._at(0, "23:30")), [d(0)])
        self.assertEqual(run(self._at(0, "23:31")), [])                  # only once
        self.assertEqual(admin.ok("GET", f"/api/reservations/{late['id']}")["status"], "no_show")
        day = admin.ok("GET", "/api/night-audit")
        self.assertEqual(day["business_date"], d(1))
        self.assertEqual(day["history"][0]["notes"], "Automatic night audit")
        entry = next(a for a in admin.ok("GET", "/api/audit") if a["action"] == "night_audit")
        self.assertEqual(entry["username"], "system")
        # a morning time closes yesterday, and days missed while the server was off are caught up in one go
        admin.ok("PUT", "/api/settings", {"night_audit_time": "03:00"})
        self.assertEqual(run(self._at(1, "04:00")), [])                  # today was already closed
        self._rewind_business_date(d(-3))
        self.assertEqual(run(self._at(0, "02:59")), [d(-3), d(-2)])      # yesterday waits for 03:00
        self.assertEqual(run(self._at(0, "03:00")), [d(-1)])
        # turning it off stops it
        admin.ok("PUT", "/api/settings", {"auto_night_audit": False})
        self._rewind_business_date(d(-9))
        self.assertEqual(run(self._at(0, "12:00")), [])


class HealthTests(AppTestCase):
    def test_health_is_public_and_minimal(self):
        status, body = self.client().req("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(body, {"status": "ok", "schema": Database.latest_version()})
        for _ in range(80):   # probes are not throttled like other public endpoints
            self.assertEqual(self.client().req("GET", "/api/health")[0], 200)
