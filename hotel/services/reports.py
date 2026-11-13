"""Dashboards, management reports and the night audit (end-of-day close)."""
import datetime as dt

from ..core.clock import add_days, date_range, money, today_iso
from ..core.errors import Conflict, ValidationError
from ..core.permissions import Perm
from .base import Service
from .billing import BillingService
from .reservations import ReservationService


class DashboardService(Service):
    def front_desk(self) -> dict:
        self.require(Perm.DASHBOARD_VIEW)
        t = today_iso()
        rooms = self.repos.rooms.search()
        total = len(rooms)
        occupied = sum(1 for r in rooms if r["occupied"])
        ooo = sum(1 for r in rooms if r["status"] == "maintenance")
        billing = self.use(BillingService)
        departures = self.repos.reservations.departures(t)
        for r in departures:
            r["balance"] = billing.folio(r)["balance"]
        month_start = t[:8] + "01"
        return {
            "date": t,
            "business_date": NightAuditService(self.ctx).business_date(),
            "rooms": {"total": total, "occupied": occupied, "out_of_order": ooo,
                      "vacant_ready": sum(1 for r in rooms if not r["occupied"] and r["status"] in ("clean", "inspected")),
                      "dirty": sum(1 for r in rooms if r["status"] == "dirty"),
                      "occupancy": round(occupied * 100 / (total - ooo), 1) if total - ooo else 0},
            "in_house_guests": self.repos.reservations.in_house_guests_count(),
            "arrivals": self.repos.reservations.arrivals(t),
            "departures": departures,
            "upcoming": self.repos.reservations.upcoming(t),
            "payments_today": money(self.repos.payments.total_between(t, t)),
            "payments_month": money(self.repos.payments.total_between(month_start, t)),
            "open_requests": len(self.repos.guest_requests.search("active")),
            "open_tickets": len(self.repos.maintenance.search("active")),
            "open_tasks": len(self.repos.housekeeping.search(statuses=("open", "in_progress"))),
            "kitchen_open": len(self.repos.orders.search(statuses=("pending", "preparing", "ready"))),
            "low_stock": self.repos.items.low_stock() if self.actor.can(Perm.INVENTORY_VIEW) else [],
        }


class ReportService(Service):
    def _range(self, date_from, date_to, default_days=30):
        end = date_to or today_iso()
        start = date_from or add_days(end, -(default_days - 1))
        try:
            dt.date.fromisoformat(start), dt.date.fromisoformat(end)
        except ValueError:
            raise ValidationError("Invalid date range")
        if start > end:
            raise ValidationError("'From' must be before 'To'")
        if (dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days > 366:
            raise ValidationError("Range cannot exceed one year")
        return start, end

    def summary(self, date_from=None, date_to=None) -> dict:
        self.require(Perm.REPORTS_VIEW)
        start, end = self._range(date_from, date_to)
        r = self.repos
        room_count = r.rooms.count()
        stays = r.reservations.overlapping(start, add_days(end, 1))
        daily = []
        for day in date_range(start, end):
            occ = [x for x in stays if x["check_in"] <= day < x["check_out"]]
            rev = money(sum(x["rate"] for x in occ))
            daily.append({"date": day, "occupied": len(occ),
                          "occupancy": round(len(occ) * 100 / room_count, 1) if room_count else 0,
                          "room_revenue": rev, "adr": money(rev / len(occ)) if occ else 0,
                          "revpar": money(rev / room_count) if room_count else 0})
        days = len(daily)
        sold = sum(d["occupied"] for d in daily)
        room_rev = money(sum(d["room_revenue"] for d in daily))
        extras = r.charges.by_category(start, end)
        payments = r.payments.by_method(start, end)
        inventory = r.items.valuation()
        invoices = r.invoices.search(start, end)
        return {
            "from": start, "to": end, "room_count": room_count,
            "totals": {
                "room_nights": sold, "occupancy": round(sold * 100 / (room_count * days), 1) if room_count else 0,
                "room_revenue": room_rev, "adr": money(room_rev / sold) if sold else 0,
                "revpar": money(room_rev / (room_count * days)) if room_count else 0,
                "extras_revenue": money(sum(e["amount"] for e in extras)),
                "payments": money(sum(p["amount"] for p in payments)),
                "inventory_value": money(sum(i["value"] or 0 for i in inventory)),
                "invoiced_total": money(sum(i["total"] for i in invoices)),
                "service_charge": money(sum(i["service_charge"] for i in invoices)),
                "vat": money(sum(i["vat"] for i in invoices)),
            },
            "daily": daily, "extras": extras, "payments": payments, "inventory": inventory,
            "sources": r.reservations.fetch_all(
                "SELECT source, COUNT(*) AS count FROM reservations WHERE status<>'cancelled' AND check_in BETWEEN ? AND ?"
                " GROUP BY source ORDER BY count DESC", (start, end)),
            "nationalities": r.reservations.fetch_all(
                "SELECT COALESCE(NULLIF(g.nationality,''),'Unknown') AS nationality, COUNT(*) AS count FROM reservations x"
                " JOIN guests g ON g.id=x.guest_id WHERE x.status IN ('checked_in','checked_out')"
                " AND x.check_in BETWEEN ? AND ? GROUP BY 1 ORDER BY count DESC LIMIT 10", (start, end)),
            "top_menu": r.orders.top_items(start, end),
            "top_items": r.movements.consumption(("sale", "return"), start, end),
            "usage": r.movements.consumption(("issue", "consume"), start, end),
            "housekeeping": r.housekeeping.productivity(start, end),
            "restaurant": {k: v for k, v in self._restaurant(start, end).items() if k != "receipts"},
            "events": {k: v for k, v in self._events(start, end).items() if k != "invoices"},
            "reviews": r.reviews.average(),
        }

    def tax_report(self, date_from=None, date_to=None) -> dict:
        """Invoices issued in the period with service charge and VAT — for the monthly VAT return."""
        self.require(Perm.REPORTS_VIEW)
        start, end = self._range(date_from, date_to)
        invoices = self.repos.invoices.search(start, end, limit=5000)
        restaurant, events = self._restaurant(start, end), self._events(start, end)
        keys = ("subtotal", "service_charge", "vat", "city_tax", "total")
        totals = {k: money(sum(i[k] for i in invoices)) for k in keys}
        return {"from": start, "to": end, "invoices": invoices, "totals": totals,
                # restaurant receipts and event invoices are tax documents too: the VAT return needs all three
                "restaurant": restaurant, "events": events,
                "grand_totals": {k: money(totals[k] + restaurant[k] + events[k]) for k in keys}}

    def _events(self, start: str, end: str) -> dict:
        from .events import EventService
        return self.use(EventService).sales(start, end)

    def _restaurant(self, start: str, end: str) -> dict:
        from .restaurant import RestaurantService
        return self.use(RestaurantService).sales(start, end)


class NightAuditService(Service):
    """Closes a business day: marks no-shows, checks departures, snapshots the day's figures, rolls the date."""

    def business_date(self) -> str:
        bd = self.settings().get("business_date") or ""
        if not bd:
            last = self.repos.audit_days.scalar("SELECT MAX(business_date) FROM audit_days")
            bd = add_days(last, 1) if last else today_iso()
        return bd

    def preview(self) -> dict:
        self.require(Perm.REPORTS_VIEW)
        bd = self.business_date()
        return {"business_date": bd, "can_close": bd <= today_iso(),
                "pending_arrivals": self.repos.reservations.fetch_all(
                    self.repos.reservations.select_sql + " WHERE t.status='booked' AND t.check_in <= ?", (bd,)),
                "overdue_departures": self.repos.reservations.fetch_all(
                    self.repos.reservations.select_sql + " WHERE t.status='checked_in' AND t.check_out <= ?", (bd,)),
                "open_shifts": self.repos.shifts.fetch_all(self.repos.shifts.select_sql + " WHERE t.closed_at IS NULL"),
                "history": self.repos.audit_days.recent()}

    def close_day(self, mark_no_shows: bool = True, notes: str = "") -> dict:
        self.require(Perm.REPORTS_VIEW)
        self.require(Perm.NIGHT_AUDIT_CLOSE)
        bd = self.business_date()
        if bd > today_iso():
            raise Conflict(f"Business date {bd} is in the future; nothing to close yet")
        if self.repos.audit_days.get_day(bd):
            raise Conflict(f"{bd} is already closed")
        no_shows = 0
        if mark_no_shows:
            res_service = self.use(ReservationService)
            for res in self.repos.reservations.fetch_all(
                    "SELECT id FROM reservations WHERE status='booked' AND check_in <= ?", (bd,)):
                res_service.no_show(res["id"], system=True)
                no_shows += 1
        stays = [x for x in self.repos.reservations.overlapping(bd, add_days(bd, 1), ("checked_in", "checked_out"))
                 if x["check_in"] <= bd < x["check_out"]]
        r = self.repos
        self.repos.audit_days.insert_day(
            business_date=bd, rooms_total=r.rooms.count(), rooms_sold=len(stays),
            room_revenue=money(sum(x["rate"] for x in stays)),
            other_revenue=money(r.charges.scalar("SELECT COALESCE(SUM(amount),0) FROM charges WHERE date(created_at)=?", (bd,), 0)),
            payments=money(r.payments.total_between(bd, bd)),
            arrivals=r.reservations.scalar("SELECT COUNT(*) FROM reservations WHERE date(checked_in_at)=?", (bd,), 0),
            departures=r.reservations.scalar("SELECT COUNT(*) FROM reservations WHERE date(checked_out_at)=?", (bd,), 0),
            no_shows=no_shows, notes=str(notes or "")[:500], closed_by=self.actor_id)
        self.repos.settings.put("business_date", add_days(bd, 1))
        self.audit("night_audit", "audit_day", None, f"closed {bd}: {no_shows} no-shows")
        return self.preview()
