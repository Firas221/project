"""Food & beverage: menu, recipes and orders."""
from .base import BaseRepository, QueryBuilder


class MenuRepository(BaseRepository):
    table = "menu_items"
    columns = ("name", "description", "category", "price", "prep_minutes", "available")
    default_order = "t.category, t.name"
    entity_label = "Menu item"

    def search(self, available_only=False) -> list:
        qb = QueryBuilder("SELECT t.* FROM menu_items t")
        qb.add_if(available_only, "t.available = 1")
        return self.fetch_all(qb.sql(self.default_order), qb.args)

    def ingredients(self, menu_item_id: int) -> list:
        return self.fetch_all(
            "SELECT mi.item_id, mi.quantity, i.sku, i.name, i.unit, i.quantity AS on_hand FROM menu_ingredients mi"
            " JOIN items i ON i.id = mi.item_id WHERE mi.menu_item_id = ? ORDER BY i.name", (menu_item_id,))

    def set_ingredients(self, menu_item_id: int, ingredients) -> None:
        self.execute("DELETE FROM menu_ingredients WHERE menu_item_id=?", (menu_item_id,))
        for ing in ingredients:
            self.execute("INSERT INTO menu_ingredients(menu_item_id, item_id, quantity) VALUES (?,?,?)",
                         (menu_item_id, ing["item_id"], ing["quantity"]))

    def used_in_orders(self, menu_item_id: int) -> bool:
        return self.scalar("SELECT 1 FROM order_lines WHERE menu_item_id=? LIMIT 1", (menu_item_id,)) is not None


class RestaurantTableRepository(BaseRepository):
    table = "restaurant_tables"
    columns = ("name", "seats", "area", "active")
    default_order = "t.area, t.name"
    entity_label = "Table"


class CheckRepository(BaseRepository):
    table = "restaurant_checks"
    columns = ("code", "table_id", "table_name", "covers", "customer_name", "status", "reservation_id", "subtotal",
               "service_charge", "vat", "city_tax", "total", "paid_method", "receipt_number", "shift_id", "notes", "opened_by",
               "closed_by", "closed_at")
    select_sql = ("SELECT t.*, o.full_name AS opened_by_name, c.full_name AS closed_by_name, r.code AS reservation_code,"
                  " rm.number AS room_number FROM restaurant_checks t LEFT JOIN users o ON o.id = t.opened_by"
                  " LEFT JOIN users c ON c.id = t.closed_by LEFT JOIN reservations r ON r.id = t.reservation_id"
                  " LEFT JOIN rooms rm ON rm.id = r.room_id")
    default_order = "t.id DESC"
    entity_label = "Check"

    def open_checks(self) -> list:
        return self.fetch_all(self.select_sql + " WHERE t.status = 'open' ORDER BY t.id")

    def closed_between(self, start: str, end: str, limit: int = 2000) -> list:
        return self.fetch_all(self.select_sql + " WHERE t.status IN ('paid', 'charged') AND date(t.closed_at) BETWEEN ? AND ?"
                              " ORDER BY t.id DESC LIMIT ?", (start, end, limit))

    def next_receipt(self, year: int) -> str:
        prefix = f"RCP-{year}-"
        last = self.scalar("SELECT receipt_number FROM restaurant_checks WHERE receipt_number LIKE ? ORDER BY receipt_number DESC LIMIT 1",
                           (prefix + "%",))
        return f"{prefix}{(int(last.rsplit('-', 1)[1]) + 1 if last else 1):06d}"

    def lines(self, check_id: int) -> list:
        return self.fetch_all("SELECT * FROM restaurant_check_lines WHERE check_id = ? ORDER BY id", (check_id,))

    def add_line(self, check_id, menu_item_id, name, quantity, unit_price, notes, created_by) -> int:
        return self.execute("INSERT INTO restaurant_check_lines(check_id, menu_item_id, name, quantity, unit_price, notes, created_by)"
                            " VALUES (?,?,?,?,?,?,?)", (check_id, menu_item_id, name, quantity, unit_price, notes, created_by)).lastrowid

    def line(self, line_id: int):
        return self.fetch_one("SELECT * FROM restaurant_check_lines WHERE id = ?", (line_id,))

    def set_line_status(self, line_id: int, status: str) -> None:
        self.execute("UPDATE restaurant_check_lines SET status = ? WHERE id = ?", (status, line_id))

    def kitchen_tickets(self) -> list:
        """Dishes sent to the kitchen and not yet ready, oldest first."""
        return self.fetch_all(
            "SELECT l.id, l.name, l.quantity, l.notes, l.created_at, c.id AS check_id, c.code, c.table_name FROM restaurant_check_lines l"
            " JOIN restaurant_checks c ON c.id = l.check_id WHERE l.status = 'sent' AND c.status = 'open' ORDER BY l.id")


class OrderRepository(BaseRepository):
    table = "orders"
    columns = ("code", "reservation_id", "status", "notes", "total", "placed_via", "created_by", "updated_at",
               "delivered_at")
    select_sql = (
        "SELECT t.*, r.code AS reservation_code, r.guest_id, rm.number AS room_number,"
        " g.first_name || ' ' || g.last_name AS guest_name, u.full_name AS created_by_name"
        " FROM orders t JOIN reservations r ON r.id = t.reservation_id JOIN rooms rm ON rm.id = r.room_id"
        " JOIN guests g ON g.id = r.guest_id LEFT JOIN users u ON u.id = t.created_by"
    )
    default_order = "t.id DESC"
    entity_label = "Order"

    def search(self, statuses=None, reservation_id=None, guest_id=None, date_from=None, limit=300) -> list:
        qb = QueryBuilder(self.select_sql)
        if statuses:
            qb.add(f"t.status IN ({','.join('?' for _ in statuses)})", *statuses)
        qb.add_if(reservation_id, "t.reservation_id = ?", reservation_id)
        qb.add_if(guest_id, "r.guest_id = ?", guest_id)
        qb.add_if(date_from, "date(t.created_at) >= ?", date_from)
        return self.fetch_all(qb.sql("t.id DESC", limit), qb.args)

    def lines(self, order_id: int) -> list:
        return self.fetch_all("SELECT * FROM order_lines WHERE order_id=? ORDER BY id", (order_id,))

    def add_line(self, order_id, menu_item_id, name, quantity, unit_price, notes="") -> None:
        self.execute("INSERT INTO order_lines(order_id, menu_item_id, name, quantity, unit_price, notes) VALUES (?,?,?,?,?,?)",
                     (order_id, menu_item_id, name, quantity, unit_price, notes))

    def open_for_reservation(self, reservation_id: int) -> int:
        return self.scalar("SELECT COUNT(*) FROM orders WHERE reservation_id=? AND status IN ('pending','preparing','ready')",
                           (reservation_id,), 0)

    def top_items(self, date_from, date_to, limit=10) -> list:
        return self.fetch_all(
            "SELECT l.name, SUM(l.quantity) AS qty, ROUND(SUM(l.quantity*l.unit_price),2) AS revenue FROM order_lines l"
            " JOIN orders o ON o.id = l.order_id WHERE o.status='delivered' AND date(o.created_at) BETWEEN ? AND ?"
            " GROUP BY l.name ORDER BY revenue DESC LIMIT ?", (date_from, date_to, limit))
