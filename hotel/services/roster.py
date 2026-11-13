"""Staff rosters (planned shifts) and attendance (clock in / clock out)."""
import datetime as dt

from ..core.clock import add_days, now_str, today_iso
from ..core.errors import Conflict, NotFound, ValidationError
from ..core.permissions import Perm, Role
from ..core.validation import Date, Int, Schema, Str, Time
from .base import Service

STAMP = "%Y-%m-%d %H:%M:%S"


class ShiftSchema(Schema):
    user_id = Int("Staff member", required=True)
    work_date = Date(required=True)
    start_time = Time(required=True)
    end_time = Time(required=True)
    note = Str(max_len=200)


def shift_hours(start: str, end: str) -> float:
    """Length of a planned shift; an end before the start means it runs past midnight."""
    a = int(start[:2]) * 60 + int(start[3:])
    b = int(end[:2]) * 60 + int(end[3:])
    return round(((b - a) % (24 * 60) or 24 * 60) / 60, 2)


def worked_hours(clock_in: str, clock_out) -> float:
    if not clock_out:
        return 0.0
    seconds = (dt.datetime.strptime(clock_out, STAMP) - dt.datetime.strptime(clock_in, STAMP)).total_seconds()
    return round(max(0, seconds) / 3600, 2)


class RosterService(Service):
    def _staff(self) -> list:
        return [{"id": u["id"], "full_name": u["full_name"], "role": u["role"], "role_label": Role.LABELS.get(u["role"], u["role"])}
                for u in self.repos.users.search() if u["role"] != Role.GUEST and u["active"]]

    @staticmethod
    def _week(start: str, days) -> tuple:
        try:
            start = dt.date.fromisoformat(start or today_iso()).isoformat()
            days = max(1, min(int(days or 7), 31))
        except (TypeError, ValueError):
            raise ValidationError("Invalid date range")
        return start, add_days(start, days - 1), days

    # ------------------------------------------------------------ planning
    def week(self, start: str = None, days=7) -> dict:
        self.require(Perm.ROSTER_MANAGE)
        start, end, days = self._week(start, days)
        shifts = self.repos.roster.between(start, end)
        for s in shifts:
            s["hours"] = shift_hours(s["start_time"], s["end_time"])
        return {"from": start, "to": end, "days": days, "staff": self._staff(), "shifts": shifts,
                "attendance": self.attendance(start, end)}

    def _checked(self, data: dict) -> dict:
        v = ShiftSchema.validate(data)
        user = self.repos.users.get(v["user_id"])
        if not user or user["role"] == Role.GUEST or not user["active"]:
            raise ValidationError("Choose an active member of staff", field="user_id")
        if v["start_time"] == v["end_time"]:
            raise ValidationError("A shift must have a length", field="end_time")
        return v

    def add(self, data: dict) -> dict:
        self.require(Perm.ROSTER_MANAGE)
        v = self._checked(data)
        sid = self.repos.roster.insert(**v, created_by=self.actor_id)
        self.audit("roster_add", "roster", sid, f"user {v['user_id']} {v['work_date']} {v['start_time']}-{v['end_time']}")
        if v["work_date"] >= today_iso():
            self.alert("You have a new shift", f"{v['work_date']} · {v['start_time']} – {v['end_time']}", "#/my-shifts",
                       user_id=v["user_id"])
        return self.repos.roster.get(sid)

    def update(self, shift_id: int, data: dict) -> dict:
        self.require(Perm.ROSTER_MANAGE)
        old = self.repos.roster.require(shift_id)
        v = self._checked(data)
        self.repos.roster.update(shift_id, **v)
        self.audit("roster_update", "roster", shift_id, f"user {v['user_id']} {v['work_date']} {v['start_time']}-{v['end_time']}")
        if v["work_date"] >= today_iso():
            self.alert("Your shift was changed", f"{v['work_date']} · {v['start_time']} – {v['end_time']}", "#/my-shifts",
                       user_id=v["user_id"])
        if old["user_id"] != v["user_id"] and old["work_date"] >= today_iso():
            self.alert("A shift of yours was removed", f"{old['work_date']} · {old['start_time']} – {old['end_time']}",
                       "#/my-shifts", user_id=old["user_id"])
        return self.repos.roster.get(shift_id)

    def delete(self, shift_id: int) -> None:
        self.require(Perm.ROSTER_MANAGE)
        old = self.repos.roster.require(shift_id)
        self.repos.roster.delete(shift_id)
        self.audit("roster_delete", "roster", shift_id, f"user {old['user_id']} {old['work_date']}")
        if old["work_date"] >= today_iso():
            self.alert("A shift of yours was removed", f"{old['work_date']} · {old['start_time']} – {old['end_time']}",
                       "#/my-shifts", user_id=old["user_id"])

    def copy_week(self, source_start: str, target_start: str) -> dict:
        """Repeats one week's plan in another week (same weekdays, same times). Days that already have a
        shift for that person at that time are left alone."""
        self.require(Perm.ROSTER_MANAGE)
        source_start, source_end, _ = self._week(source_start, 7)
        target_start, target_end, _ = self._week(target_start, 7)
        if source_start == target_start:
            raise ValidationError("Choose two different weeks")
        existing = {(s["user_id"], s["work_date"], s["start_time"]) for s in self.repos.roster.between(target_start, target_end)}
        offset = (dt.date.fromisoformat(target_start) - dt.date.fromisoformat(source_start)).days
        copied = 0
        for s in self.repos.roster.between(source_start, source_end):
            day = add_days(s["work_date"], offset)
            if (s["user_id"], day, s["start_time"]) in existing:
                continue
            self.repos.roster.insert(user_id=s["user_id"], work_date=day, start_time=s["start_time"], end_time=s["end_time"],
                                     note=s["note"], created_by=self.actor_id)
            copied += 1
        self.audit("roster_copy", "roster", None, f"{source_start} -> {target_start}: {copied} shifts")
        return {"copied": copied}

    # ------------------------------------------------------------ my own shifts and clock
    def mine(self) -> dict:
        today = today_iso()
        shifts = self.repos.roster.between(today, add_days(today, 13), self.actor.id)
        for s in shifts:
            s["hours"] = shift_hours(s["start_time"], s["end_time"])
        recent = self.repos.attendance.between(add_days(today, -13), today, self.actor.id)
        for r in recent:
            r["hours"] = worked_hours(r["clock_in"], r["clock_out"])
        return {"today": today, "open": self.repos.attendance.open_for(self.actor.id), "shifts": shifts, "attendance": recent[:20]}

    def clock_in(self) -> dict:
        if self.repos.attendance.open_for(self.actor.id):
            raise Conflict("You are already clocked in")
        self.repos.attendance.insert(user_id=self.actor.id, clock_in=now_str())
        self.audit("clock_in", "attendance", None, self.actor.username)
        return self.mine()

    def clock_out(self) -> dict:
        open_record = self.repos.attendance.open_for(self.actor.id)
        if not open_record:
            raise Conflict("You are not clocked in")
        self.repos.attendance.update(open_record["id"], clock_out=now_str())
        self.audit("clock_out", "attendance", open_record["id"], self.actor.username)
        return self.mine()

    # ------------------------------------------------------------ attendance for managers
    def attendance(self, start: str, end: str) -> dict:
        """Per person: hours planned, hours worked, and who is on the clock right now."""
        self.require(Perm.ROSTER_MANAGE)
        records = self.repos.attendance.between(start, end)
        planned, worked, on_clock = {}, {}, set()
        for s in self.repos.roster.between(start, end):
            planned[s["user_id"]] = planned.get(s["user_id"], 0) + shift_hours(s["start_time"], s["end_time"])
        for r in records:
            r["hours"] = worked_hours(r["clock_in"], r["clock_out"])
            worked[r["user_id"]] = worked.get(r["user_id"], 0) + r["hours"]
            if not r["clock_out"]:
                on_clock.add(r["user_id"])
        totals = [{"user_id": u["id"], "full_name": u["full_name"], "role_label": u["role_label"],
                   "planned_hours": round(planned.get(u["id"], 0), 2), "worked_hours": round(worked.get(u["id"], 0), 2),
                   "on_the_clock": u["id"] in on_clock}
                  for u in self._staff() if u["id"] in planned or u["id"] in worked]
        return {"totals": totals, "records": records[:300]}

    def correct(self, record_id: int, clock_in: str, clock_out: str) -> dict:
        """A manager fixes a record, e.g. when someone forgot to clock out."""
        self.require(Perm.ROSTER_MANAGE)
        rec = self.repos.attendance.get(record_id)
        if not rec:
            raise NotFound("Attendance record not found")
        try:
            start = dt.datetime.strptime((clock_in or "").replace("T", " ")[:16], "%Y-%m-%d %H:%M")
            end = dt.datetime.strptime((clock_out or "").replace("T", " ")[:16], "%Y-%m-%d %H:%M") if clock_out else None
        except ValueError:
            raise ValidationError("Enter the times as date and time")
        if end and end <= start:
            raise ValidationError("Clock-out must be after clock-in", field="clock_out")
        if end and (end - start).total_seconds() > 24 * 3600:
            raise ValidationError("A single record cannot be longer than 24 hours", field="clock_out")
        self.repos.attendance.update(record_id, clock_in=start.strftime(STAMP), clock_out=end.strftime(STAMP) if end else None,
                                     edited_by=self.actor_id)
        self.audit("attendance_correct", "attendance", record_id, f"{rec['user_name']}: {start} – {end}")
        return self.repos.attendance.get(record_id)
