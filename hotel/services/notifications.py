"""E-mail notifications. Messages are queued in the outbox inside the business transaction
and delivered afterwards by :class:`hotel.infrastructure.mailer.MailDispatcher`."""
from .base import Service


class NotificationService(Service):
    def queue(self, to: str, subject: str, body: str) -> None:
        if not to or "@" not in to:
            return
        self.repos.outbox.insert(to_address=to, subject=subject[:200], body=body[:20000])

    def _base_url(self) -> str:
        cfg = self.ctx.app.config if self.ctx.app else None
        return (cfg.public_url if cfg and cfg.public_url else "http://localhost:8000")

    def _sign(self) -> str:
        s = self.settings()
        return f"\n\n{s.get('hotel_name', 'Hotel')}\n{s.get('address', '')}\n{s.get('phone', '')}"

    def password_reset(self, user: dict, token: str) -> None:
        link = f"{self._base_url()}/login#reset={token}"
        self.queue(user["email"], "Reset your password",
                   f"Hello {user['full_name']},\n\nWe received a request to reset your password. "
                   f"Use this link within 30 minutes:\n\n{link}\n\n"
                   "If you did not request this, you can ignore this e-mail; your password is unchanged." + self._sign())

    def booking_confirmation(self, res: dict, email: str) -> None:
        s = self.settings()
        self.queue(email, f"Booking confirmed — {res['code']}",
                   f"Dear {res['guest_name']},\n\nThank you for booking with {s.get('hotel_name')}.\n\n"
                   f"Confirmation: {res['code']}\nRoom type: {res['room_type']}\n"
                   f"Arrival: {res['check_in']} (from {s.get('check_in_time')})\n"
                   f"Departure: {res['check_out']} (until {s.get('check_out_time')})\n"
                   f"Nightly rate: {res['rate']:.2f} {s.get('currency')} + {s.get('service_charge_rate')}% service "
                   f"+ {s.get('vat_rate')}% VAT\n\nManage your booking: {self._base_url()}/account" + self._sign())

    def cancellation(self, res: dict, email: str) -> None:
        self.queue(email, f"Booking cancelled — {res['code']}",
                   f"Dear {res['guest_name']},\n\nYour reservation {res['code']} "
                   f"({res['check_in']} to {res['check_out']}) has been cancelled." + self._sign())

    def receipt(self, res: dict, email: str, invoice_number: str, total: float) -> None:
        s = self.settings()
        self.queue(email, f"Your invoice {invoice_number}",
                   f"Dear {res['guest_name']},\n\nThank you for staying with us. Your tax invoice {invoice_number} "
                   f"totals {total:,.2f} {s.get('currency')}. You can view it any time in your account: "
                   f"{self._base_url()}/account" + self._sign())

    def verify_email(self, user: dict, token: str) -> None:
        link = f"{self._base_url()}/login#verify={token}"
        self.queue(user["email"], "Confirm your e-mail address",
                   f"Hello {user['full_name']},\n\nWelcome! Please confirm that this e-mail address is yours by opening "
                   f"this link within 48 hours:\n\n{link}\n\n"
                   "If you did not create an account, you can ignore this e-mail." + self._sign())

    def welcome(self, user: dict) -> None:
        self.queue(user["email"], "Welcome", f"Hello {user['full_name']},\n\nYour account has been created. "
                   f"Sign in at {self._base_url()}/login" + self._sign())
