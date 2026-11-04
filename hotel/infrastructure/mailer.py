"""Delivers queued e-mails from the outbox via SMTP (or logs them when SMTP isn't configured)."""
import logging
import smtplib
import ssl
from email.message import EmailMessage

from ..core.clock import now_str
from ..repositories import Repositories

log = logging.getLogger("hotel.mail")


class MailDispatcher:
    def __init__(self, db, config):
        self.db, self.cfg = db, config

    def deliver_pending(self) -> int:
        with self.db.unit_of_work(write=True) as conn:
            outbox = Repositories(conn).outbox
            pending = outbox.queued()
            for msg in pending:
                if not self.cfg.smtp_host:
                    outbox.update(msg["id"], status="logged", sent_at=now_str())
                    log.info("E-mail (SMTP not configured) to %s: %s", msg["to_address"], msg["subject"])
                    continue
                try:
                    self._send(msg)
                    outbox.update(msg["id"], status="sent", sent_at=now_str(), attempts=msg["attempts"] + 1)
                except Exception as e:  # network errors are retried up to 5 times
                    status = "failed" if msg["attempts"] + 1 >= 5 else "queued"
                    outbox.update(msg["id"], status=status, attempts=msg["attempts"] + 1, error=str(e)[:300])
                    log.warning("E-mail to %s failed: %s", msg["to_address"], e)
            return len(pending)

    def _send(self, msg: dict) -> None:
        em = EmailMessage()
        em["From"], em["To"], em["Subject"] = self.cfg.smtp_from, msg["to_address"], msg["subject"]
        em.set_content(msg["body"])
        context = ssl.create_default_context()
        if self.cfg.smtp_port == 465:
            with smtplib.SMTP_SSL(self.cfg.smtp_host, self.cfg.smtp_port, context=context, timeout=20) as s:
                self._login_and_send(s, em)
        else:
            with smtplib.SMTP(self.cfg.smtp_host, self.cfg.smtp_port, timeout=20) as s:
                if self.cfg.smtp_starttls:
                    s.starttls(context=context)
                self._login_and_send(s, em)

    def _login_and_send(self, smtp, em):
        if self.cfg.smtp_user:
            smtp.login(self.cfg.smtp_user, self.cfg.smtp_password)
        smtp.send_message(em)
