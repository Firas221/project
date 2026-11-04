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
