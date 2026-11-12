"""Waitlist for full dates, and the controls on what the website may sell.

Every reservation holds a real room, so the hotel can never be overbooked. What the hotel controls instead is
how much of its stock the website is allowed to sell: rooms held back per room type, and stop-sell dates.
"""
from ..core.clock import now_str, today_iso
from ..core.errors import Conflict, ValidationError
from ..core.permissions import Perm
from ..core.validation import Date, Email, Int, Phone, Schema, Str
from .base import Service


class WaitlistSchema(Schema):
    guest_id = Int("Guest", nullable=True, default=None)
    name = Str(max_len=160)
    phone = Phone()
    email = Email()
    room_type_id = Int("Room type", nullable=True, default=None)
    check_in = Date(required=True)
    check_out = Date(required=True)
    adults = Int(min_value=1, max_value=20, default=1)
    children = Int(min_value=0, max_value=20, default=0)
    notes = Str(max_len=500, multiline=True)


class StopSellSchema(Schema):
    room_type_id = Int("Room type", nullable=True, default=None)
    start_date = Date(required=True)
    end_date = Date(required=True)
    reason = Str(max_len=200)


class WaitlistService(Service):
    def _free(self, entry: dict) -> int:
        """Rooms that could take this entry right now."""
        return len(self.repos.rooms.available(entry["check_in"], entry["check_out"], entry["adults"] + entry["children"],
                                              entry["room_type_id"]))

    def list(self, status: str = "waiting") -> list:
        self.require(Perm.RESERVATIONS_VIEW)
        rows = self.repos.waitlist.search(status or None)
        for r in rows:
            r["rooms_free"] = self._free(r) if r["status"] == "waiting" and r["check_out"] > today_iso() else 0
        return rows

    def add(self, data: dict, *, online_guest_id: int = None) -> dict:
        if not online_guest_id:
            self.require(Perm.RESERVATIONS_MANAGE)
        v = WaitlistSchema.validate(data)
        if online_guest_id:
            v["guest_id"] = online_guest_id
        if v["check_out"] <= v["check_in"]:
            raise ValidationError("Check-out must be after check-in", field="check_out")
        if v["check_in"] < today_iso():
            raise ValidationError("Arrival date cannot be in the past", field="check_in")
        if v["room_type_id"]:
            self.repos.room_types.require(v["room_type_id"], "Room type")
        if v["guest_id"]:
            g = self.repos.guests.require(v["guest_id"], "Guest")
            v["name"] = v["name"] or f"{g['first_name']} {g['last_name']}"
            v["phone"], v["email"] = v["phone"] or g["phone"], v["email"] or g["email"]
        if not v["name"]:
            raise ValidationError("Name is required", field="name")
        if not (v["phone"] or v["email"]):
            raise ValidationError("Add a phone number or an e-mail address so the guest can be reached", field="phone")
        if online_guest_id and len(self.repos.waitlist.search("waiting", guest_id=online_guest_id)) >= 5:
            raise Conflict("You are already on the waiting list for several dates. Please contact the hotel.")
        wid = self.repos.waitlist.insert(**v, source="online" if online_guest_id else "desk", created_by=self.actor_id)
        self.audit("waitlist_add", "waitlist", wid, f"{v['name']} {v['check_in']}→{v['check_out']}")
        if online_guest_id:
            self.alert("A guest joined the waiting list", f"{v['name']} · {v['check_in']} → {v['check_out']}", "#/waitlist",
                       permission=Perm.RESERVATIONS_MANAGE)
        return self.repos.waitlist.get(wid)

    def close(self, entry_id: int, status: str, reservation_id: int = None) -> dict:
        """Marks an entry as booked (optionally linking the reservation) or cancelled."""
        self.require(Perm.RESERVATIONS_MANAGE)
        entry = self.repos.waitlist.require(entry_id)
        if status not in ("booked", "cancelled"):
            raise ValidationError("Invalid status")
        if entry["status"] != "waiting":
            raise Conflict("This waiting-list entry is already closed")
        if reservation_id:
            self.repos.reservations.require(reservation_id, "Reservation")
        self.repos.waitlist.update(entry_id, status=status, reservation_id=reservation_id if status == "booked" else None)
        self.audit(f"waitlist_{status}", "waitlist", entry_id, entry["name"])
        return self.repos.waitlist.get(entry_id)

    def room_freed(self, check_in: str, check_out: str) -> int:
        """Called when a booking is cancelled, shortened or becomes a no-show: tells the desk, once per entry,
        about people on the waiting list who can now be offered a room."""
        told = 0
        for entry in self.repos.waitlist.waiting_between(check_in, check_out):
            if entry["alerted_at"] or entry["check_in"] < today_iso() or not self._free(entry):
                continue
            self.repos.waitlist.update(entry["id"], alerted_at=now_str())
            self.alert("A room is free for the waiting list", f"{entry['name']} · {entry['check_in']} → {entry['check_out']}",
                       "#/waitlist", permission=Perm.RESERVATIONS_MANAGE)
            told += 1
        return told

    # ------------------------------------------------------------ online sale controls
    def stop_sells(self) -> list:
        self.require(Perm.ROOMS_VIEW)
        return [s for s in self.repos.stop_sells.all() if s["end_date"] >= today_iso()]

    def add_stop_sell(self, data: dict) -> dict:
        self.require(Perm.ROOMS_MANAGE)
        v = StopSellSchema.validate(data)
        if v["end_date"] < v["start_date"]:
            raise ValidationError("End date must be on or after the start date", field="end_date")
        if v["room_type_id"]:
            self.repos.room_types.require(v["room_type_id"], "Room type")
        sid = self.repos.stop_sells.insert(**v, created_by=self.actor_id)
        self.audit("stop_sell_add", "stop_sell", sid, f"{v['start_date']}→{v['end_date']} type={v['room_type_id'] or 'all'}")
        return self.repos.stop_sells.get(sid)

    def delete_stop_sell(self, stop_id: int) -> None:
        self.require(Perm.ROOMS_MANAGE)
        self.repos.stop_sells.require(stop_id)
        self.repos.stop_sells.delete(stop_id)
        self.audit("stop_sell_delete", "stop_sell", stop_id)

    def sellable_online(self, check_in: str, check_out: str, guests: int) -> dict:
        """room type id → rooms the website may still sell for these dates (after hold-backs and stop-sells)."""
        blocked = self.repos.stop_sells.blocked_types(check_in, check_out)
        if None in blocked:
            return {}
        counts = {}
        for room in self.repos.rooms.available(check_in, check_out, guests):
            counts[room["type_id"]] = counts.get(room["type_id"], 0) + 1
        held = {t["id"]: t["online_hold_back"] for t in self.repos.room_types.all()}
        return {tid: n - held.get(tid, 0) for tid, n in counts.items() if tid not in blocked and n - held.get(tid, 0) > 0}
