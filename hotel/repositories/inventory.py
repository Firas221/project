"""Inventory: suppliers, items, stock ledger, purchase orders, supply requests."""
from .base import BaseRepository, QueryBuilder, page_of


class SupplierRepository(BaseRepository):
    table = "suppliers"
    columns = ("name", "contact", "phone", "email", "active")
    select_sql = ("SELECT t.*, (SELECT COUNT(*) FROM items i WHERE i.supplier_id = t.id AND i.active = 1) AS item_count"
                  " FROM suppliers t")
    default_order = "t.name"
    entity_label = "Supplier"


class ItemRepository(BaseRepository):
    table = "items"
    columns = ("sku", "name", "category", "department", "unit", "quantity", "reorder_level", "cost", "price", "chargeable",
               "supplier_id", "active")
    select_sql = ("SELECT t.*, s.name AS supplier_name, (t.quantity <= t.reorder_level) AS low_stock,"
                  " ROUND(t.quantity * t.cost, 2) AS stock_value FROM items t LEFT JOIN suppliers s ON s.id = t.supplier_id")
    default_order = "t.category, t.name"
    entity_label = "Item"

    def search(self, q=None, category=None, department=None, low=False, chargeable=False, include_inactive=False) -> list:
        qb = QueryBuilder(self.select_sql)
        if not include_inactive:
            qb.add("t.active = 1")
        qb.add_if(category, "t.category = ?", category)
        qb.add_if(department, "t.department = ?", department)
        qb.add_if(low, "t.quantity <= t.reorder_level")
        qb.add_if(chargeable, "t.chargeable = 1")
        qb.add_if(q, "(t.name LIKE ? OR t.sku LIKE ?)", f"%{q}%", f"%{q}%")
        return self.fetch_all(qb.sql(self.default_order), qb.args)

    def low_stock(self, supplier_id: int = None) -> list:
        qb = QueryBuilder(self.select_sql).add("t.active = 1 AND t.quantity <= t.reorder_level")
        qb.add_if(supplier_id, "t.supplier_id = ?", supplier_id)
        return self.fetch_all(qb.sql("t.quantity / NULLIF(t.reorder_level, 0)"), qb.args)

    def valuation(self) -> list:
        return self.fetch_all(
            "SELECT category, COUNT(*) AS items, ROUND(SUM(quantity*cost),2) AS value, SUM(quantity <= reorder_level) AS low"
            " FROM items WHERE active=1 GROUP BY category ORDER BY value DESC")


class MovementRepository(BaseRepository):
    table = "stock_movements"
    columns = ("item_id", "kind", "change", "balance_after", "unit_cost", "reason", "reference", "reservation_id",
               "created_by")
    select_sql = ("SELECT t.*, i.sku, i.name AS item_name, i.unit, u.full_name AS user_name, r.code AS reservation_code"
                  " FROM stock_movements t JOIN items i ON i.id = t.item_id LEFT JOIN users u ON u.id = t.created_by"
                  " LEFT JOIN reservations r ON r.id = t.reservation_id")
    default_order = "t.id DESC"

    def search(self, item_id=None, kind=None, date_from=None, date_to=None, limit=500, page=None, per_page=None):
        qb = QueryBuilder(self.select_sql)
        qb.add_if(item_id, "t.item_id = ?", item_id)
        qb.add_if(kind, "t.kind = ?", kind)
        qb.add_if(date_from, "date(t.created_at) >= ?", date_from)
        qb.add_if(date_to, "date(t.created_at) <= ?", date_to)
        if page is not None:
            return page_of(self, qb, self.default_order, page, per_page)
        return self.fetch_all(qb.sql(self.default_order, limit), qb.args)

    def consumption(self, kinds, date_from, date_to, limit=10) -> list:
        marks = ",".join("?" for _ in kinds)
        return self.fetch_all(
            f"SELECT i.sku, i.name, i.unit, SUM(-m.change) AS qty, ROUND(SUM(-m.change * i.cost), 2) AS cost,"
            f" ROUND(SUM(-m.change * i.price), 2) AS revenue"
            f" FROM stock_movements m JOIN items i ON i.id = m.item_id WHERE m.kind IN ({marks})"
            f" AND date(m.created_at) BETWEEN ? AND ? GROUP BY i.id HAVING qty > 0 ORDER BY cost DESC LIMIT ?",
            (*kinds, date_from, date_to, limit))


class PurchaseOrderRepository(BaseRepository):
    table = "purchase_orders"
    columns = ("code", "supplier_id", "status", "expected_date", "notes", "created_by", "ordered_at", "received_at")
    select_sql = (
        "SELECT t.*, s.name AS supplier_name, u.full_name AS created_by_name,"
        " (SELECT ROUND(COALESCE(SUM(l.quantity * l.unit_cost),0),2) FROM purchase_order_lines l WHERE l.po_id = t.id) AS total,"
        " (SELECT COUNT(*) FROM purchase_order_lines l WHERE l.po_id = t.id) AS line_count"
        " FROM purchase_orders t JOIN suppliers s ON s.id = t.supplier_id LEFT JOIN users u ON u.id = t.created_by"
    )
    default_order = "t.id DESC"
    entity_label = "Purchase order"

    def search(self, status=None) -> list:
        qb = QueryBuilder(self.select_sql)
        qb.add_if(status, "t.status = ?", status)
        return self.fetch_all(qb.sql(self.default_order), qb.args)

    def lines(self, po_id: int) -> list:
        return self.fetch_all(
            "SELECT l.*, i.sku, i.name AS item_name, i.unit, ROUND(l.quantity * l.unit_cost, 2) AS amount"
            " FROM purchase_order_lines l JOIN items i ON i.id = l.item_id WHERE l.po_id = ? ORDER BY l.id", (po_id,))

    def add_line(self, po_id: int, item_id: int, quantity: float, unit_cost: float) -> None:
        self.execute("INSERT INTO purchase_order_lines(po_id, item_id, quantity, unit_cost) VALUES (?,?,?,?)",
                     (po_id, item_id, quantity, unit_cost))

    def clear_lines(self, po_id: int) -> None:
        self.execute("DELETE FROM purchase_order_lines WHERE po_id=?", (po_id,))


class StockRequestRepository(BaseRepository):
    table = "stock_requests"
    columns = ("code", "department", "status", "notes", "response", "requested_by", "handled_by", "handled_at")
    select_sql = (
        "SELECT t.*, u.full_name AS requested_by_name, u.role AS requested_by_role, h.full_name AS handled_by_name"
        " FROM stock_requests t JOIN users u ON u.id = t.requested_by LEFT JOIN users h ON h.id = t.handled_by"
    )
    default_order = "t.id DESC"
    entity_label = "Supply request"

    def search(self, status=None, requested_by=None, limit=300) -> list:
        qb = QueryBuilder(self.select_sql)
        qb.add_if(status, "t.status = ?", status)
        qb.add_if(requested_by, "t.requested_by = ?", requested_by)
        return self.fetch_all(qb.sql(self.default_order, limit), qb.args)

    def lines(self, request_id: int) -> list:
        return self.fetch_all(
            "SELECT l.*, i.sku, i.name AS item_name, i.unit, i.quantity AS on_hand FROM stock_request_lines l"
            " JOIN items i ON i.id = l.item_id WHERE l.request_id = ? ORDER BY l.id", (request_id,))

    def add_line(self, request_id: int, item_id: int, quantity: float) -> None:
        self.execute("INSERT INTO stock_request_lines(request_id, item_id, quantity) VALUES (?,?,?)",
                     (request_id, item_id, quantity))
