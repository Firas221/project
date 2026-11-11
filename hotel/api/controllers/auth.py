"""Sign-in, sessions, passwords, 2FA and guest registration."""
from ...http.messages import SessionCookie
from ...services import AuthService, SettingsService
from ..router import Controller, get, post


class AuthController(Controller):
    def _session_result(self, result: dict):
        if result.get("two_factor_required"):
            return {"two_factor_required": True, "challenge": result["challenge"]}
        s = result["session"]
        return SessionCookie({"user": result["user"], "csrf_token": s["csrf_token"]}, s["token"], s["max_age"])

    @post("/auth/login", audience="public", csrf=False, limit="login")
    def login(self):
        return self._session_result(self.svc(AuthService).login(self.body.get("username"), self.body.get("password"),
                                                                self.req.user_agent))

    @post("/auth/2fa", audience="public", csrf=False, limit="login")
    def second_factor(self):
        return self._session_result(self.svc(AuthService).verify_second_factor(
            self.body.get("challenge"), self.body.get("code"), self.req.user_agent))

    @post("/auth/register", audience="public", csrf=False, limit="register")
    def register(self):
        return self._session_result(self.svc(AuthService).register_guest(self.body, self.req.user_agent))

    @post("/auth/logout", audience="public", csrf=False)
    def logout(self):
        # Logout is deliberately CSRF-exempt: the worst a forged request can do is sign the user out.
        self.svc(AuthService).logout(self.req.session_token)
        return SessionCookie({"ok": True}, clear=True)

    @get("/auth/me", audience="user", allow_restricted=True)
    def me(self):
        user = self.req.user.to_dict()
        user["totp_enabled"] = bool(self.req.ctx.repos.users.get(user["id"])["totp_enabled"])
        return {"user": user, "csrf_token": self.req.session["csrf_token"],
                "settings": self.svc(SettingsService).public()}

    @post("/auth/password", audience="user", allow_restricted=True)
    def change_password(self):
        self.svc(AuthService).change_password(self.body.get("current_password"), self.body.get("new_password"))
        return {"ok": True}

    @post("/auth/forgot", audience="public", csrf=False, limit="reset")
    def forgot(self):
        self.svc(AuthService).request_password_reset(self.body.get("identifier"))
        return {"ok": True, "message": "If an account matches, a reset link has been sent to its e-mail address."}

    @post("/auth/reset", audience="public", csrf=False, limit="reset")
    def reset(self):
        self.svc(AuthService).reset_password(self.body.get("token"), self.body.get("new_password"))
        return {"ok": True}

    @post("/auth/verify-email", audience="public", csrf=False, limit="login")
    def verify_email(self):
        self.svc(AuthService).verify_email(self.body.get("token"))
        return {"ok": True}

    @post("/auth/verify-email/resend", audience="user", limit="reset")
    def resend_verification(self):
        self.svc(AuthService).resend_verification()
        return {"ok": True, "message": "We sent a new confirmation link to your e-mail address."}

    @post("/auth/2fa/setup", audience="user", allow_restricted=True)
    def setup_2fa(self):
        return self.svc(AuthService).start_2fa()

    @post("/auth/2fa/confirm", audience="user", allow_restricted=True)
    def confirm_2fa(self):
        self.svc(AuthService).confirm_2fa(self.body.get("code"))
        return {"ok": True}

    @post("/auth/2fa/disable", audience="user")
    def disable_2fa(self):
        self.svc(AuthService).disable_2fa(self.body.get("password"))
        return {"ok": True}
