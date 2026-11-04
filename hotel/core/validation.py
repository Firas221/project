"""Declarative input validation.

Define a schema as a class with :class:`Field` attributes and call
``MySchema.validate(data)``. Unknown keys are ignored (never passed to the
database), every value is type-checked, length-limited and normalised.

    class GuestSchema(Schema):
        first_name = Str(required=True, max_len=80)
        email = Email()
"""
import datetime as dt
import math
import re

from .errors import ValidationError

_MISSING = object()


class Field:
    def __init__(self, label: str = None, *, required: bool = False, default=_MISSING, nullable: bool = False):
        self.label = label
        self.required = required
        self.default = default
        self.nullable = nullable
        self.name = None

    def __set_name__(self, owner, name):
        self.name = name
        if self.label is None:
            self.label = name.replace("_", " ").capitalize()

    def fail(self, message: str):
        raise ValidationError(f"{self.label} {message}", field=self.name)

    def is_empty(self, value) -> bool:
        return value is None or (isinstance(value, str) and value.strip() == "")

    def clean(self, value):  # pragma: no cover - abstract
        raise NotImplementedError

    def resolve(self, data: dict, partial: bool):
        """Returns the cleaned value, or ``_MISSING`` when the key should be omitted."""
        if self.name not in data:
            if partial:
                return _MISSING
            if self.required:
                self.fail("is required")
            return _MISSING if self.default is _MISSING else self.default
        value = data[self.name]
        if self.is_empty(value):
            if self.required:
                self.fail("is required")
            if self.nullable:
                return None
            return self.empty_value()
        return self.clean(value)

    def empty_value(self):
        return None if self.default is _MISSING else self.default


class Str(Field):
    def __init__(self, label=None, *, max_len=200, min_len=0, pattern=None, choices=None, lower=False, upper=False,
                 multiline=False, **kw):
        kw.setdefault("default", "")
        super().__init__(label, **kw)
        self.max_len, self.min_len = max_len, min_len
        self.pattern = re.compile(pattern) if pattern else None
        self.choices = tuple(choices) if choices else None
        self.lower, self.upper, self.multiline = lower, upper, multiline

    def empty_value(self):
        return "" if not self.nullable else None

    def clean(self, value):
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            self.fail("must be text")
        value = str(value).strip()
        if not self.multiline and ("\n" in value or "\r" in value):
            value = " ".join(value.split())
        if any(ord(c) < 32 and c not in "\n\r\t" for c in value):
            self.fail("contains invalid characters")
        if len(value) > self.max_len:
            self.fail(f"must be at most {self.max_len} characters")
        if len(value) < self.min_len:
            self.fail(f"must be at least {self.min_len} characters")
        if self.lower:
            value = value.lower()
        if self.upper:
            value = value.upper()
        if self.choices and value not in self.choices:
            self.fail("has an invalid value")
        if self.pattern and not self.pattern.fullmatch(value):
            self.fail("has an invalid format")
        return value


class Email(Str):
    def __init__(self, label=None, **kw):
        kw.setdefault("max_len", 160)
        super().__init__(label, lower=True, pattern=r"[^@\s]+@[^@\s]+\.[^@\s]+", **kw)


class Phone(Str):
    def __init__(self, label=None, **kw):
        kw.setdefault("max_len", 40)
        super().__init__(label, pattern=r"[0-9+()\-.\s]{3,40}", **kw)


class Number(Field):
    def __init__(self, label=None, *, min_value=None, max_value=None, integer=False, places=None, **kw):
        super().__init__(label, **kw)
        self.min_value, self.max_value = min_value, max_value
        self.integer, self.places = integer, places

    def clean(self, value):
        if isinstance(value, bool):
            self.fail("must be a number")
        try:
            num = float(value)
        except (TypeError, ValueError):
            self.fail("must be a number")
        if math.isnan(num) or math.isinf(num):
            self.fail("must be a number")
        if self.integer:
            if num != int(num):
                self.fail("must be a whole number")
            num = int(num)
        elif self.places is not None:
            num = round(num, self.places)
        if self.min_value is not None and num < self.min_value:
            self.fail(f"must be at least {self.min_value:g}")
        if self.max_value is not None and num > self.max_value:
            self.fail(f"must be at most {self.max_value:g}")
        return num


class Int(Number):
    def __init__(self, label=None, **kw):
        super().__init__(label, integer=True, **kw)


class Money(Number):
    def __init__(self, label=None, **kw):
        kw.setdefault("min_value", 0)
        kw.setdefault("max_value", 10_000_000)
        super().__init__(label, places=2, **kw)


class Bool(Field):
    def __init__(self, label=None, **kw):
        kw.setdefault("default", False)
        super().__init__(label, **kw)

    def is_empty(self, value):
        return value is None or value == ""

    def clean(self, value):
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            v = value.strip().lower()
            if v in ("1", "true", "yes", "on"):
                return True
            if v in ("0", "false", "no", "off"):
                return False
        self.fail("must be true or false")


class Date(Field):
    def clean(self, value):
        try:
            return dt.date.fromisoformat(str(value)[:10]).isoformat()
        except (TypeError, ValueError):
            self.fail("must be a valid date (YYYY-MM-DD)")


class Time(Str):
    def __init__(self, label=None, **kw):
        super().__init__(label, max_len=5, pattern=r"([01]\d|2[0-3]):[0-5]\d", **kw)


class ListOf(Field):
    """A list of nested schema objects, e.g. order lines."""

    def __init__(self, schema, label=None, *, min_items=0, max_items=100, **kw):
        kw.setdefault("default", [])
        super().__init__(label, **kw)
        self.schema, self.min_items, self.max_items = schema, min_items, max_items

    def is_empty(self, value):
        return value is None

    def clean(self, value):
        if not isinstance(value, list):
            self.fail("must be a list")
        if len(value) < self.min_items:
            self.fail(f"needs at least {self.min_items} item(s)")
        if len(value) > self.max_items:
            self.fail(f"can have at most {self.max_items} items")
        return [self.schema.validate(v if isinstance(v, dict) else {}) for v in value]


class Schema:
    _fields: dict = {}

    def __init_subclass__(cls, **kw):
        super().__init_subclass__(**kw)
        fields = {}
        for base in reversed(cls.__mro__[1:]):
            fields.update(getattr(base, "_fields", {}))
        fields.update({k: v for k, v in cls.__dict__.items() if isinstance(v, Field)})
        cls._fields = fields

    @classmethod
    def validate(cls, data, *, partial: bool = False) -> dict:
        if not isinstance(data, dict):
            raise ValidationError("Request body must be a JSON object")
        out = {}
        for name, f in cls._fields.items():
            value = f.resolve(data, partial)
            if value is not _MISSING:
                out[name] = value
        return out
