"""Hotel operations: housekeeping, maintenance, guest requests, lost & found, reviews."""
from ..core.clock import now_str, today_iso
from ..core.errors import Conflict, PermissionDenied, ValidationError
from ..core.permissions import Perm, Role
from ..core.validation import Bool, Date, Int, Schema, Str
from .base import Service

PRIORITIES = ("low", "normal", "high", "urgent")
TASK_KINDS = ("checkout_clean", "stayover", "deep_clean", "turndown", "guest_request")


class TaskSchema(Schema):
    room_id = Int("Room", required=True)
    kind = Str(choices=TASK_KINDS, default="stayover")
    priority = Str(choices=PRIORITIES, default="normal")
    assigned_to = Int("Housekeeper", nullable=True, default=None)
    due_date = Date(default=None, nullable=True)
    notes = Str(max_len=500, multiline=True)


class TicketSchema(Schema):
    room_id = Int("Room", nullable=True, default=None)
    location = Str(max_len=120)
    title = Str(required=True, max_len=120)
    description = Str(max_len=2000, multiline=True)
    priority = Str(choices=PRIORITIES, default="normal")
    out_of_order = Bool()


class TicketUpdateSchema(Schema):
    status = Str(choices=("open", "in_progress", "resolved", "closed"))
    priority = Str(choices=PRIORITIES)
    assigned_to = Int("Assignee", nullable=True)
    resolution = Str(max_len=2000, multiline=True)
    out_of_order = Bool()


class LostItemSchema(Schema):
    room_id = Int("Room", nullable=True, default=None)
    location = Str(max_len=120)
    description = Str(required=True, max_len=300)
    notes = Str(max_len=500)


class HousekeepingService(Service):
    def board(self, status=None, mine=False):
        """Supervisors see everything; housekeepers see their own and unassigned open tasks."""
        statuses = (status,) if status else ("open", "in_progress", "done")
        if self.actor.can(Perm.HOUSEKEEPING_MANAGE) and not mine:
            return self.repos.housekeeping.search(statuses=statuses)
        self.require(Perm.HOUSEKEEPING_WORK)
        return self.repos.housekeeping.search(statuses=statuses or ("open", "in_progress"),
                                              unassigned_or_mine=self.actor_id)

    def history(self, limit=200):
        if self.actor.can(Perm.HOUSEKEEPING_MANAGE):
            return self.repos.housekeeping.search(statuses=("done", "inspected", "cancelled"), limit=limit)
        self.require(Perm.HOUSEKEEPING_WORK)
        return self.repos.housekeeping.search(statuses=("done", "inspected"), assigned_to=self.actor_id, limit=limit)

    def create(self, data: dict) -> dict:
        self.require(Perm.HOUSEKEEPING_MANAGE)
        v = TaskSchema.validate(data)
        self.repos.rooms.require(v["room_id"], "Room")
        if v["assigned_to"]:
            self._check_housekeeper(v["assigned_to"])
        v["due_date"] = v["due_date"] or today_iso()
        tid = self.repos.housekeeping.insert(**v, created_by=self.actor_id)
        self.audit("task_create", "housekeeping_task", tid, v["kind"])
        return self.repos.housekeeping.get(tid)

    def _check_housekeeper(self, user_id):
        u = self.repos.users.get(user_id)
        if not u or not u["active"] or u["role"] not in (Role.HOUSEKEEPER, Role.STAFF):
            raise ValidationError("Assignee must be an active housekeeper")

    def assign(self, task_id: int, user_id) -> dict:
        self.require(Perm.HOUSEKEEPING_MANAGE)
        task = self.repos.housekeeping.require(task_id, "Task")
        if user_id:
            self._check_housekeeper(int(user_id))
        self.repos.housekeeping.update(task_id, assigned_to=int(user_id) if user_id else None)
        self.audit("task_assign", "housekeeping_task", task_id, f"room {task['room_number']} -> {user_id}")
        return self.repos.housekeeping.get(task_id)

    def generate_stayovers(self) -> dict:
        """Creates today's stay-over service tasks for every occupied room without one."""
        self.require(Perm.HOUSEKEEPING_MANAGE)
        created = 0
        for res in self.repos.reservations.in_house():
            if res["check_out"] > today_iso() and not self.repos.housekeeping.open_for_room(res["room_id"]):
                self.repos.housekeeping.insert(room_id=res["room_id"], kind="stayover", due_date=today_iso(),
                                               created_by=self.actor_id)
                created += 1
        self.audit("tasks_generate", "housekeeping_task", None, f"{created} stay-over tasks")
        return {"created": created}

    def _own_task(self, task_id: int) -> dict:
        task = self.repos.housekeeping.require(task_id, "Task")
        if not self.actor.can(Perm.HOUSEKEEPING_MANAGE):
            self.require(Perm.HOUSEKEEPING_WORK)
            if task["assigned_to"] not in (None, self.actor_id):
                raise PermissionDenied("This task is assigned to someone else")
        return task

    def start(self, task_id: int) -> dict:
        task = self._own_task(task_id)
        if task["status"] != "open":
            raise Conflict("Only open tasks can be started")
        self.repos.housekeeping.update(task_id, status="in_progress", started_at=now_str(),
                                       assigned_to=task["assigned_to"] or self.actor_id)
        self.audit("task_start", "housekeeping_task", task_id, f"room {task['room_number']}")
        return self.repos.housekeeping.get(task_id)

    def complete(self, task_id: int, notes: str = "") -> dict:
        task = self._own_task(task_id)
        if task["status"] not in ("open", "in_progress"):
            raise Conflict("This task is already finished")
        fields = {"status": "done", "completed_at": now_str(), "assigned_to": task["assigned_to"] or self.actor_id}
        if not task["started_at"]:
            fields["started_at"] = now_str()
        if notes:
            fields["notes"] = (task["notes"] + "\n" if task["notes"] else "") + str(notes)[:500]
        self.repos.housekeeping.update(task_id, **fields)
        room = self.repos.rooms.get(task["room_id"])
        if room["status"] != "maintenance":
            self.repos.rooms.set_status(room["id"], "clean")
        self.audit("task_complete", "housekeeping_task", task_id, f"room {task['room_number']}")
        return self.repos.housekeeping.get(task_id)

    def inspect(self, task_id: int, passed: bool, notes: str = "") -> dict:
        self.require(Perm.HOUSEKEEPING_MANAGE)
        task = self.repos.housekeeping.require(task_id, "Task")
        if task["status"] != "done":
            raise Conflict("Only completed tasks can be inspected")
        if passed:
            self.repos.housekeeping.update(task_id, status="inspected", inspected_by=self.actor_id)
            if self.repos.rooms.get(task["room_id"])["status"] != "maintenance":
                self.repos.rooms.set_status(task["room_id"], "inspected")
        else:
            self.repos.housekeeping.update(task_id, status="open", started_at=None, completed_at=None,
                                           notes=(task["notes"] + "\n" if task["notes"] else "") + f"Re-clean: {notes}"[:500])
            self.repos.rooms.set_status(task["room_id"], "dirty")
        self.audit("task_inspect", "housekeeping_task", task_id, "passed" if passed else "failed")
        return self.repos.housekeeping.get(task_id)

    def cancel(self, task_id: int) -> dict:
        self.require(Perm.HOUSEKEEPING_MANAGE)
        self.repos.housekeeping.require(task_id, "Task")
        self.repos.housekeeping.update(task_id, status="cancelled")
        self.audit("task_cancel", "housekeeping_task", task_id)
        return self.repos.housekeeping.get(task_id)

    def housekeepers(self):
        return [{"id": u["id"], "full_name": u["full_name"]} for u in self.repos.users.active_by_role(Role.HOUSEKEEPER)]


class MaintenanceService(Service):
    def list(self, status="active"):
        if self.actor.can(Perm.MAINTENANCE_VIEW):
            return self.repos.maintenance.search(status)
        self.require(Perm.MAINTENANCE_REPORT)
        return self.repos.maintenance.search(status, reported_by=self.actor_id)

    def report(self, data: dict, *, from_guest_request: bool = False) -> dict:
        if not from_guest_request:
            self.require(Perm.MAINTENANCE_REPORT)
        v = TicketSchema.validate(data)
        if not v["room_id"] and not v["location"]:
            raise ValidationError("Choose a room or describe the location")
        if v["room_id"]:
            self.repos.rooms.require(v["room_id"], "Room")
        ooo = bool(v.pop("out_of_order")) and v["room_id"] and self.actor and self.actor.can(Perm.MAINTENANCE_MANAGE)
        tid = self.repos.maintenance.insert(code=self.new_code("MT", self.repos.maintenance, 5), **v,
                                            out_of_order=int(bool(ooo)), reported_by=self.actor_id)
        if ooo:
            self._take_out_of_order(v["room_id"], v["title"])
        self.audit("ticket_report", "maintenance", tid, v["title"])
        return self.repos.maintenance.get(tid)

    def _take_out_of_order(self, room_id: int, reason: str) -> None:
        occupant = self.repos.reservations.occupant(room_id)
        if occupant:
            raise Conflict(f"The room is occupied ({occupant['code']}). Move the guest before taking it out of order.")
        self.repos.rooms.set_status(room_id, "maintenance", reason[:200])

    def update(self, ticket_id: int, data: dict) -> dict:
        self.require(Perm.MAINTENANCE_MANAGE)
        t = self.repos.maintenance.require(ticket_id, "Ticket")
        v = TicketUpdateSchema.validate(data, partial=True)
        fields = {k: v[k] for k in ("status", "priority", "assigned_to", "resolution") if k in v}
        if "out_of_order" in v and t["room_id"]:
            if v["out_of_order"] and not t["out_of_order"]:
                self._take_out_of_order(t["room_id"], t["title"])
            fields["out_of_order"] = int(v["out_of_order"])
        if fields.get("status") in ("resolved", "closed"):
            fields["resolved_at"] = t["resolved_at"] or now_str()
            fields["out_of_order"] = 0
        released = t["out_of_order"] and fields.get("out_of_order") == 0
        self.repos.maintenance.update(ticket_id, **fields)
        if released and t["room_id"] and not self.repos.maintenance.other_out_of_order(t["room_id"], ticket_id):
            # back in service: needs cleaning before it is sold again
            self.repos.rooms.set_status(t["room_id"], "dirty", "")
            if not self.repos.housekeeping.open_for_room(t["room_id"]):
                self.repos.housekeeping.insert(room_id=t["room_id"], kind="deep_clean", priority="high",
                                               due_date=today_iso(), notes=f"After repair {t['code']}",
                                               created_by=self.actor_id)
        self.audit("ticket_update", "maintenance", ticket_id, f"{t['code']} {fields}")
        return self.repos.maintenance.get(ticket_id)


class GuestRequestService(Service):
    """Requests raised by guests from the client portal (or by staff on their behalf)."""

    def list(self, status="active"):
        self.require(Perm.REQUESTS_MANAGE)
        return self.repos.guest_requests.search(status)

    def create_for_reservation(self, res: dict, kind: str, message: str) -> dict:
        if kind not in ("housekeeping", "maintenance", "amenity", "wake_up", "other"):
            raise ValidationError("Invalid request type")
        message = Str("Message", required=True, max_len=500, multiline=True).clean(message or "")
        if not message:
            raise ValidationError("Message is required")
        rid = self.repos.guest_requests.insert(reservation_id=res["id"], kind=kind, message=message)
        # route operational requests straight to the right department
        if kind == "housekeeping" and not self.repos.housekeeping.open_for_room(res["room_id"], "guest_request"):
            self.repos.housekeeping.insert(room_id=res["room_id"], kind="guest_request", priority="high",
                                           due_date=today_iso(), notes=f"Guest request: {message}"[:500])
        elif kind == "maintenance":
            self.use(MaintenanceService).report(
                {"room_id": res["room_id"], "title": f"Guest request: {message[:80]}", "description": message,
                 "priority": "high"}, from_guest_request=True)
        return self.repos.guest_requests.get(rid)

    def respond(self, request_id: int, status: str, response: str = "") -> dict:
        self.require(Perm.REQUESTS_MANAGE)
        req = self.repos.guest_requests.require(request_id, "Request")
        if status not in ("open", "in_progress", "done", "cancelled"):
            raise ValidationError("Invalid status")
        self.repos.guest_requests.update(request_id, status=status, response=str(response or "")[:500],
                                         handled_by=self.actor_id, updated_at=now_str())
        self.audit("request_" + status, "guest_request", request_id, req["reservation_code"])
        return self.repos.guest_requests.get(request_id)


class LostFoundService(Service):
    def list(self, status=None):
        if self.actor.can(Perm.LOSTFOUND_MANAGE):
            return self.repos.lost_found.search(status)
        self.require(Perm.LOSTFOUND_REPORT)
        return self.repos.lost_found.search(status, found_by=self.actor_id)

    def log(self, data: dict) -> dict:
        self.require(Perm.LOSTFOUND_REPORT)
        v = LostItemSchema.validate(data)
        guest_id = None
        if v["room_id"]:
            self.repos.rooms.require(v["room_id"], "Room")
            last = self.repos.reservations.fetch_one(
                "SELECT guest_id FROM reservations WHERE room_id=? AND status IN ('checked_in','checked_out')"
                " ORDER BY COALESCE(checked_out_at, checked_in_at) DESC LIMIT 1", (v["room_id"],))
            guest_id = last["guest_id"] if last else None
        lid = self.repos.lost_found.insert(**v, guest_id=guest_id, found_by=self.actor_id)
        self.audit("lost_found_log", "lost_found", lid, v["description"])
        return self.repos.lost_found.get(lid)

    def close(self, item_id: int, status: str, notes: str = "") -> dict:
        self.require(Perm.LOSTFOUND_MANAGE)
        if status not in ("returned", "disposed"):
            raise ValidationError("Status must be returned or disposed")
        item = self.repos.lost_found.require(item_id)
        if item["status"] != "stored":
            raise Conflict("This item is already closed")
        self.repos.lost_found.update(item_id, status=status, notes=str(notes or "")[:500], closed_at=now_str())
        self.audit("lost_found_" + status, "lost_found", item_id, item["description"])
        return self.repos.lost_found.get(item_id)


class ReviewService(Service):
    def list(self):
        self.require(Perm.REVIEWS_MANAGE)
        return {"reviews": self.repos.reviews.all(), "summary": self.repos.reviews.average()}

    def moderate(self, review_id: int, published: bool, reply: str = "") -> dict:
        self.require(Perm.REVIEWS_MANAGE)
        self.repos.reviews.require(review_id)
        self.repos.reviews.update(review_id, published=int(bool(published)), reply=str(reply or "")[:1000])
        self.audit("review_moderate", "review", review_id, "published" if published else "hidden")
        return self.repos.reviews.get(review_id)

    def public(self):
        return {"reviews": [{"rating": r["rating"], "comment": r["comment"], "reply": r["reply"],
                             "guest": r["guest_first_name"], "room_type": r["room_type"], "date": r["created_at"][:10]}
                            for r in self.repos.reviews.published()],
                "summary": self.repos.reviews.average()}
