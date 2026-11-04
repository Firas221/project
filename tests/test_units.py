"""Unit tests for core building blocks (no server needed)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hotel.core.errors import RateLimited, ValidationError  # noqa: E402
from hotel.core.security import PasswordHasher, PasswordPolicy, RateLimiter, Tokens  # noqa: E402
from hotel.core.totp import TOTP  # noqa: E402
from hotel.core.validation import Bool, Date, Email, Int, ListOf, Money, Schema, Str  # noqa: E402
from hotel.services.billing import TaxCalculator  # noqa: E402


class Line(Schema):
    item_id = Int(required=True)


class Sample(Schema):
    name = Str(required=True, max_len=10)
    email = Email()
    amount = Money()
    count = Int(min_value=1, max_value=5, default=1)
    when = Date(nullable=True, default=None)
    flag = Bool()
    lines = ListOf(Line, max_items=2)


class ValidationTests(unittest.TestCase):
    def test_valid_and_normalised(self):
        v = Sample.validate({"name": "  Nile ", "email": "A@B.CO", "amount": "12.345", "flag": "yes", "unknown": "dropped"})
        self.assertEqual(v["name"], "Nile")
        self.assertEqual(v["email"], "a@b.co")
        self.assertEqual(v["amount"], 12.35)
        self.assertTrue(v["flag"])
        self.assertNotIn("unknown", v)
        self.assertEqual(v["count"], 1)

    def test_rejections(self):
        bad = [{}, {"name": "x" * 11}, {"name": "ok", "email": "nope"}, {"name": "ok", "amount": -1},
               {"name": "ok", "count": 9}, {"name": "ok", "count": 1.5}, {"name": "ok", "when": "31/12/2026"},
               {"name": "ok", "amount": "NaN"}, {"name": "ok", "flag": "maybe"}, {"name": True},
               {"name": "ok", "lines": [{}, {}, {}]}, {"name": "ok", "lines": [{"item_id": "x"}]}, {"name": "a\x00b"}]
        for data in bad:
            with self.assertRaises(ValidationError, msg=data):
                Sample.validate(data)

    def test_partial_update(self):
        self.assertEqual(Sample.validate({"count": 3}, partial=True), {"count": 3})
        with self.assertRaises(ValidationError):
            Sample.validate([1, 2])


class SecurityPrimitiveTests(unittest.TestCase):
    def test_password_hashing(self):
        h = PasswordHasher(2000)
        stored = h.hash("Secret12345")
        self.assertTrue(h.verify("Secret12345", stored))
        self.assertFalse(h.verify("secret12345", stored))
        self.assertFalse(h.verify("x", "garbage"))
        self.assertNotEqual(stored, h.hash("Secret12345"))  # random salt
        self.assertTrue(PasswordHasher(5000).needs_rehash(stored))

    def test_password_policy(self):
        for weak in ("short1A", "alllowercase123", "ALLUPPER123", "NoDigitsHere", "Password1234"):
            with self.assertRaises(ValidationError, msg=weak):
                PasswordPolicy.validate(weak)
        with self.assertRaises(ValidationError):
            PasswordPolicy.validate("Johnsmith2026", username="johnsmith")
        PasswordPolicy.validate("Correct-Horse-9")
        PasswordPolicy.validate(Tokens.temporary_password())

    def test_tokens(self):
        a, b = Tokens.new(), Tokens.new()
        self.assertNotEqual(a, b)
        self.assertEqual(len(Tokens.digest(a)), 64)
        self.assertTrue(Tokens.equal("x", "x"))
        self.assertFalse(Tokens.equal("", ""))

    def test_rate_limiter(self):
        rl = RateLimiter()
        for _ in range(3):
            rl.check("k", 3, 60)
        with self.assertRaises(RateLimited):
            rl.check("k", 3, 60)
        rl.check("other", 3, 60)

    def test_totp_rfc6238_vector(self):
        secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # base32("12345678901234567890")
        self.assertEqual(TOTP.code_at(secret, 59), "287082")
        self.assertEqual(TOTP.code_at(secret, 1111111109), "081804")

    def test_totp_verify_and_replay(self):
        s = TOTP.new_secret()
        code = TOTP.code_at(s)
        step = TOTP.verify(s, code)
        self.assertIsNotNone(step)
        self.assertIsNone(TOTP.verify(s, code, last_step=step))  # replay blocked
        self.assertIsNone(TOTP.verify(s, "000000" if code != "000000" else "111111"))


class TaxTests(unittest.TestCase):
    def test_egyptian_hotel_tax(self):
        t = TaxCalculator({"service_charge_rate": "12", "vat_rate": "14", "city_tax_rate": "0"}).compute(1000)
        self.assertEqual(t["service_charge"], 120.0)
        self.assertEqual(t["vat"], 156.8)       # 14% of (1000 + 120)
        self.assertEqual(t["total"], 1276.8)

    def test_city_tax(self):
        t = TaxCalculator({"service_charge_rate": "0", "vat_rate": "0", "city_tax_rate": "1"}).compute(500)
        self.assertEqual(t["total"], 505.0)


if __name__ == "__main__":
    unittest.main()
