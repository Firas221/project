"""E-mail notifications, in the guest's language (English or Arabic).

Messages are queued in the outbox inside the business transaction and delivered afterwards by
:class:`hotel.infrastructure.mailer.MailDispatcher`.
"""
from .base import Service

MEALS = {
    "en": {"room_only": "Room only", "breakfast": "Breakfast included", "half_board": "Half board",
           "full_board": "Full board"},
    "ar": {"room_only": "الغرفة فقط", "breakfast": "شامل الإفطار", "half_board": "نصف إقامة", "full_board": "إقامة كاملة"},
}

TEXT = {
    "en": {
        "dear": "Dear {name},",
        "hello": "Hello {name},",
        "stay": ("Confirmation: {code}\nRoom type: {room_type}\nRate: {plan}\n"
                 "Arrival: {check_in} (from {check_in_time})\nDeparture: {check_out} (until {check_out_time})\n"
                 "Guests: {adults} adult(s), {children} child(ren)\n"
                 "Nightly rate: {rate:.2f} {currency} + {service}% service + {vat}% VAT"),
        "manage": "Manage your booking: {url}/account",
        "confirmation_subject": "Booking confirmation {code}",
        "confirmation": "Thank you for booking with {hotel}.",
        "changed_subject": "Your booking {code} was changed",
        "changed": "Your booking has been updated. Here are the new details.",
        "non_refundable": "This rate is non-refundable and cannot be changed or cancelled online.",
        "free_cancel": "You can change or cancel free of charge until {days} day(s) before arrival.",
        "reminder_subject": "See you soon — your stay starts {check_in}",
        "reminder": ("We are looking forward to welcoming you at {hotel}.\n\nPlease bring your passport or national ID: "
                     "we need it to register your stay.\nCheck-in is from {check_in_time}. Address: {address}"),
        "cancel_subject": "Booking cancelled — {code}",
        "cancel": "Your reservation {code} ({check_in} to {check_out}) has been cancelled.",
        "receipt_subject": "Your invoice {number}",
        "receipt": ("Thank you for staying with us. Your tax invoice {number} totals {total} {currency}. "
                    "You can view it any time in your account: {url}/account"),
        "reset_subject": "Reset your password",
        "reset": ("We received a request to reset your password. Use this link within 30 minutes:\n\n{link}\n\n"
                  "If you did not request this, you can ignore this e-mail; your password is unchanged."),
        "verify_subject": "Confirm your e-mail address",
        "verify": ("Welcome! Please confirm that this e-mail address is yours by opening this link within 48 hours:"
                   "\n\n{link}\n\nIf you did not create an account, you can ignore this e-mail."),
        "welcome_subject": "Welcome",
        "welcome": "Your account has been created. Sign in at {url}/login",
    },
    "ar": {
        "dear": "عزيزي/عزيزتي {name}،",
        "hello": "مرحبًا {name}،",
        "stay": ("رقم التأكيد: {code}\nنوع الغرفة: {room_type}\nالسعر: {plan}\n"
                 "الوصول: {check_in} (من الساعة {check_in_time})\nالمغادرة: {check_out} (حتى الساعة {check_out_time})\n"
                 "النزلاء: {adults} بالغ، {children} طفل\n"
                 "سعر الليلة: {rate:.2f} {currency} + {service}٪ خدمة + {vat}٪ ضريبة القيمة المضافة"),
        "manage": "لإدارة حجزك: {url}/account",
        "confirmation_subject": "تأكيد الحجز {code}",
        "confirmation": "شكرًا لحجزك لدى {hotel}.",
        "changed_subject": "تم تعديل حجزك {code}",
        "changed": "تم تحديث حجزك. إليك التفاصيل الجديدة.",
        "non_refundable": "هذا السعر غير قابل للاسترداد ولا يمكن تعديله أو إلغاؤه عبر الإنترنت.",
        "free_cancel": "يمكنك التعديل أو الإلغاء مجانًا حتى {days} يوم قبل الوصول.",
        "reminder_subject": "نراك قريبًا — تبدأ إقامتك في {check_in}",
        "reminder": ("نتطلع إلى الترحيب بك في {hotel}.\n\nيرجى إحضار جواز السفر أو بطاقة الرقم القومي، "
                     "فنحن نحتاجها لتسجيل إقامتك.\nتسجيل الوصول من الساعة {check_in_time}. العنوان: {address}"),
        "cancel_subject": "تم إلغاء الحجز — {code}",
        "cancel": "تم إلغاء حجزك {code} (من {check_in} إلى {check_out}).",
        "receipt_subject": "فاتورتك {number}",
        "receipt": ("شكرًا لإقامتك معنا. إجمالي فاتورتك الضريبية {number} هو {total} {currency}. "
                    "يمكنك الاطلاع عليها في أي وقت من حسابك: {url}/account"),
        "reset_subject": "إعادة تعيين كلمة المرور",
        "reset": ("تلقينا طلبًا لإعادة تعيين كلمة المرور. استخدم هذا الرابط خلال 30 دقيقة:\n\n{link}\n\n"
                  "إذا لم تطلب ذلك فتجاهل هذه الرسالة، ولن تتغير كلمة المرور."),
        "verify_subject": "أكّد بريدك الإلكتروني",
        "verify": ("مرحبًا بك! يرجى تأكيد أن هذا البريد الإلكتروني يخصك بفتح هذا الرابط خلال 48 ساعة:"
                   "\n\n{link}\n\nإذا لم تنشئ حسابًا فتجاهل هذه الرسالة."),
        "welcome_subject": "مرحبًا بك",
        "welcome": "تم إنشاء حسابك. سجّل الدخول من {url}/login",
    },
}


class NotificationService(Service):
    def queue(self, to: str, subject: str, body: str) -> None:
        if not to or "@" not in to:
            return
        self.repos.outbox.insert(to_address=to, subject=subject[:200], body=body[:20000])

    def _base_url(self) -> str:
        cfg = self.ctx.app.config if self.ctx.app else None
        return (cfg.public_url if cfg and cfg.public_url else "http://localhost:8000")

    # ------------------------------------------------------------ language
    def _lang_of_guest(self, guest_id) -> str:
        guest = self.repos.guests.get(guest_id) if guest_id else None
        return "ar" if guest and guest.get("language") == "ar" else "en"

    def _hotel(self, lang: str) -> str:
        s = self.settings()
        return (s.get("hotel_name_ar") if lang == "ar" else "") or s.get("hotel_name") or "Hotel"

    def _sign(self, lang: str = "en") -> str:
        s = self.settings()
        return f"\n\n{self._hotel(lang)}\n{s.get('address', '')}\n{s.get('phone', '')}"

    def _send(self, to: str, lang: str, subject_key: str, greeting: str, name: str, parts: list, **values) -> None:
        t = TEXT[lang]
        body = t[greeting].format(name=name) + "\n\n" + "\n\n".join(p.format(**values) for p in parts if p)
        self.queue(to, t[subject_key].format(**values), body + self._sign(lang))

    def _stay_values(self, res: dict, lang: str) -> dict:
        s = self.settings()
        plan = MEALS[lang].get(res.get("meal_plan") or "room_only", "")
        if res.get("rate_plan_name"):
            plan = f"{res['rate_plan_name']} ({plan})"
        return {"code": res["code"], "room_type": res["room_type"], "plan": plan, "check_in": res["check_in"],
                "check_out": res["check_out"], "check_in_time": s.get("check_in_time"),
                "check_out_time": s.get("check_out_time"), "adults": res["adults"], "children": res["children"],
                "rate": res["rate"], "currency": s.get("currency"), "service": s.get("service_charge_rate"),
                "vat": s.get("vat_rate"), "hotel": self._hotel(lang), "url": self._base_url(),
                "address": s.get("address", ""), "days": s.get("free_cancellation_days") or 0}

    def _policy(self, res: dict, lang: str) -> str:
        return TEXT[lang]["free_cancel" if res.get("refundable", 1) else "non_refundable"]

    # ------------------------------------------------------------ bookings
    def booking_confirmation(self, res: dict, email: str) -> None:
        lang, t = self._lang_of_guest(res["guest_id"]), None
        t = TEXT[lang]
        self._send(email, lang, "confirmation_subject", "dear", res["guest_name"],
                   [t["confirmation"], t["stay"], self._policy(res, lang), t["manage"]], **self._stay_values(res, lang))

    def booking_changed(self, res: dict, email: str) -> None:
        lang = self._lang_of_guest(res["guest_id"])
        t = TEXT[lang]
        self._send(email, lang, "changed_subject", "dear", res["guest_name"],
                   [t["changed"], t["stay"], self._policy(res, lang), t["manage"]], **self._stay_values(res, lang))

    def arrival_reminder(self, res: dict, email: str) -> None:
        lang = self._lang_of_guest(res["guest_id"])
        t = TEXT[lang]
        self._send(email, lang, "reminder_subject", "dear", res["guest_name"], [t["reminder"], t["stay"], t["manage"]],
                   **self._stay_values(res, lang))

    def cancellation(self, res: dict, email: str) -> None:
        lang = self._lang_of_guest(res["guest_id"])
        self._send(email, lang, "cancel_subject", "dear", res["guest_name"], [TEXT[lang]["cancel"]],
                   code=res["code"], check_in=res["check_in"], check_out=res["check_out"])

    def receipt(self, res: dict, email: str, invoice_number: str, total: float) -> None:
        lang = self._lang_of_guest(res["guest_id"])
        self._send(email, lang, "receipt_subject", "dear", res["guest_name"], [TEXT[lang]["receipt"]],
                   number=invoice_number, total=f"{total:,.2f}", currency=self.settings().get("currency"),
                   url=self._base_url())

    # ------------------------------------------------------------ accounts
    def password_reset(self, user: dict, token: str) -> None:
        lang = self._lang_of_guest(user.get("guest_id"))
        self._send(user["email"], lang, "reset_subject", "hello", user["full_name"], [TEXT[lang]["reset"]],
                   link=f"{self._base_url()}/login#reset={token}")

    def verify_email(self, user: dict, token: str) -> None:
        lang = self._lang_of_guest(user.get("guest_id"))
        self._send(user["email"], lang, "verify_subject", "hello", user["full_name"], [TEXT[lang]["verify"]],
                   link=f"{self._base_url()}/login#verify={token}")

    def welcome(self, user: dict) -> None:
        lang = self._lang_of_guest(user.get("guest_id"))
        self._send(user["email"], lang, "welcome_subject", "hello", user["full_name"], [TEXT[lang]["welcome"]],
                   url=self._base_url())
