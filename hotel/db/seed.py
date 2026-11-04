"""Bootstrap data: roles, permissions, settings, the first admin and optional demo data."""
import datetime as dt
import logging

from ..core.permissions import DEFAULT_ROLE_PERMISSIONS, Role
from ..core.security import PasswordHasher, Tokens
from ..repositories import Repositories

log = logging.getLogger("hotel.seed")

DEFAULT_SETTINGS = {
    "hotel_name": "Harborview Hotel",
    "tagline": "Seaside comfort in the heart of the bay",
    "address": "1 Harbor Road, Bayside",
    "phone": "+1 555 0100",
    "email": "frontdesk@harborview.example",
    "currency": "$",
    "tax_rate": "10",
    "check_in_time": "14:00",
    "check_out_time": "11:00",
    "free_cancellation_days": "1",
    "online_booking_enabled": "1",
    "max_online_nights": "30",
}

DEMO_PASSWORDS = {
    "admin": "AdminPass123",
    "frontdesk": "FrontDesk123",
    "chef": "ChefPass123",
    "maid": "MaidPass123",
    "maid2": "MaidPass123",
    "guest": "GuestPass123",
}


class Bootstrapper:
    """Runs inside one write transaction. Idempotent for roles/settings."""

    def __init__(self, conn, hasher: PasswordHasher):
        self.repos = Repositories(conn)
        self.hasher = hasher

    def run(self, seed_demo: bool) -> dict:
        r = self.repos
        for role in Role.ALL:
            r.roles.ensure(role, Role.LABELS[role])
            if role in DEFAULT_ROLE_PERMISSIONS and not r.roles.permissions_of(role):
                r.roles.set_permissions(role, DEFAULT_ROLE_PERMISSIONS[role])
        for k, v in DEFAULT_SETTINGS.items():
            r.settings.put_default(k, v)
        if r.users.count() > 0:
            return {}
        if seed_demo:
            DemoData(r, self.hasher).load()
            return {"admin_password": DEMO_PASSWORDS["admin"], "demo": True}
        password = Tokens.temporary_password()
        r.users.insert(username="admin", full_name="Administrator", role=Role.ADMIN,
                       password_hash=self.hasher.hash(password), must_change_password=1)
        return {"admin_password": password, "demo": False}


class DemoData:
    def __init__(self, repos: Repositories, hasher: PasswordHasher):
        self.r = repos
        self.hasher = hasher
        self.today = dt.date.today()

    def d(self, offset: int) -> str:
        return (self.today + dt.timedelta(days=offset)).isoformat()

    def load(self):
        self.users = self._users()
        self._rooms()
        self.guest_ids = self._guests()
        self._inventory()
        self._menu()
        self._reservations()
        self._operations()
        log.info("Demo data loaded")

    # ------------------------------------------------------------------
    def _users(self) -> dict:
        people = [
            ("admin", "Alex Morgan", Role.ADMIN, "alex.morgan@harborview.example"),
            ("frontdesk", "Sam Rivera", Role.STAFF, "sam.rivera@harborview.example"),
            ("chef", "Marco Bellini", Role.CHEF, "marco.bellini@harborview.example"),
            ("maid", "Rosa Delgado", Role.HOUSEKEEPER, "rosa.delgado@harborview.example"),
            ("maid2", "Lina Haddad", Role.HOUSEKEEPER, "lina.haddad@harborview.example"),
        ]
        ids = {}
        for username, name, role, email in people:
            ids[username] = self.r.users.insert(
                username=username, full_name=name, role=role, email=email,
                password_hash=self.hasher.hash(DEMO_PASSWORDS[username]))
        return ids

    def _rooms(self):
        types = [
            ("Standard Single", "Cozy room with a single bed, ideal for solo travellers", 89, 1, "Single", 16,
             "Wi-Fi, TV, Work desk, Rain shower"),
            ("Standard Double", "Comfortable room with a queen bed", 119, 2, "Queen", 22, "Wi-Fi, TV, Mini-bar, Safe"),
            ("Deluxe King", "Spacious king room with harbour view", 159, 2, "King", 30,
             "Wi-Fi, Smart TV, Mini-bar, Bathtub, Harbour view"),
            ("Family Suite", "Two bedrooms and a living area", 229, 4, "King + 2 Twin", 48,
             "Wi-Fi, 2 TVs, Kitchenette, Mini-bar, Sofa bed"),
            ("Presidential Suite", "Top-floor suite with a private terrace", 450, 4, "King", 85,
             "Wi-Fi, Terrace, Jacuzzi, Butler service, Lounge access"),
        ]
        for name, desc, rate, cap, bed, size, amen in types:
            self.r.room_types.insert(name=name, description=desc, base_rate=rate, capacity=cap, bed_type=bed,
                                     size_sqm=size, amenities=amen)
        layout = [(f"1{n:02d}", 1, 1 if n <= 4 else 2) for n in range(1, 9)]
        layout += [(f"2{n:02d}", 2, 2 if n <= 3 else 3) for n in range(1, 9)]
        layout += [(f"3{n:02d}", 3, 3 if n <= 2 else 4) for n in range(1, 7)]
        layout += [("401", 4, 5), ("402", 4, 5)]
        self.room_ids = {}
        for number, floor, type_id in layout:
            self.room_ids[number] = self.r.rooms.insert(number=number, floor=floor, type_id=type_id)

    def _guests(self) -> list:
        guests = [
            ("Amelia", "Hart", "amelia.hart@example.com", "+1 555 0111", "12 Oak St", "British", "P1234567", 1),
            ("Benjamin", "Okafor", "ben.okafor@example.com", "+1 555 0112", "44 Pine Ave", "Nigerian", "P2345678", 0),
            ("Chloe", "Nguyen", "chloe.n@example.com", "+1 555 0113", "9 Elm Rd", "Vietnamese", "D3456789", 0),
            ("Daniel", "Rossi", "d.rossi@example.com", "+39 555 0114", "Via Roma 3", "Italian", "P4567890", 0),
            ("Elena", "Petrova", "elena.p@example.com", "+7 555 0115", "Lenina 21", "Bulgarian", "P5678901", 1),
            ("Farid", "Haddad", "farid.h@example.com", "+961 555 0116", "Hamra St 5", "Lebanese", "P6789012", 0),
            ("Grace", "Kim", "grace.kim@example.com", "+82 555 0117", "Gangnam 77", "Korean", "P7890123", 0),
            ("Hugo", "Martin", "hugo.martin@example.com", "+33 555 0118", "Rue Lepic 8", "French", "P8901234", 0),
            ("Isla", "Brown", "isla.b@example.com", "+44 555 0119", "Baker St 221", "British", "D9012345", 0),
            ("Jonas", "Weber", "jonas.w@example.com", "+49 555 0120", "Hauptstr 10", "German", "P0123456", 0),
        ]
        ids = []
        for first, last, email, phone, addr, nat, idn, vip in guests:
            ids.append(self.r.guests.insert(first_name=first, last_name=last, email=email, phone=phone, address=addr,
                                            nationality=nat, id_number=idn, vip=vip))
        # Amelia has an online account (client portal).
        self.r.users.insert(username="amelia.hart@example.com", email="amelia.hart@example.com",
                            full_name="Amelia Hart", role=Role.GUEST, guest_id=ids[0],
                            password_hash=self.hasher.hash(DEMO_PASSWORDS["guest"]))
        return ids

    def _inventory(self):
        for name, contact, phone, email in [
            ("FreshServe Foods", "Maria Lopez", "+1 555 0201", "orders@freshserve.example"),
            ("CleanCo Supplies", "Tom Becker", "+1 555 0202", "sales@cleanco.example"),
            ("LinenWorks", "Sara Ali", "+1 555 0203", "hello@linenworks.example"),
        ]:
            self.r.suppliers.insert(name=name, contact=contact, phone=phone, email=email)
        items = [
            # sku, name, category, department, unit, qty, reorder, cost, price, chargeable, supplier
            ("MB-WATER", "Mineral Water 500ml", "Minibar", "minibar", "bottle", 120, 40, 0.40, 3.00, 1, 1),
            ("MB-COLA", "Cola 330ml", "Minibar", "minibar", "can", 80, 30, 0.55, 4.00, 1, 1),
            ("MB-BEER", "Craft Beer 330ml", "Minibar", "minibar", "bottle", 18, 24, 1.50, 7.00, 1, 1),
            ("MB-CHIPS", "Potato Chips", "Minibar", "minibar", "bag", 45, 20, 0.70, 4.50, 1, 1),
            ("MB-CHOC", "Dark Chocolate Bar", "Minibar", "minibar", "bar", 9, 15, 0.90, 5.00, 1, 1),
            ("KT-EGGS", "Eggs", "Dairy & Eggs", "kitchen", "pcs", 240, 60, 0.25, 0, 0, 1),
            ("KT-BREAD", "Sourdough Bread", "Bakery", "kitchen", "loaf", 14, 6, 2.40, 0, 0, 1),
            ("KT-BEEF", "Beef Patty 180g", "Meat", "kitchen", "pcs", 30, 12, 2.10, 0, 0, 1),
            ("KT-PASTA", "Spaghetti", "Dry goods", "kitchen", "kg", 12, 4, 1.80, 0, 0, 1),
            ("KT-TOMSC", "Tomato Sauce", "Dry goods", "kitchen", "kg", 8, 3, 3.20, 0, 0, 1),
            ("KT-SALMN", "Salmon Fillet", "Fish", "kitchen", "pcs", 10, 8, 5.50, 0, 0, 1),
            ("KT-LETTC", "Lettuce", "Produce", "kitchen", "head", 16, 6, 0.90, 0, 0, 1),
            ("KT-COFFE", "Coffee Beans", "Beverages", "kitchen", "kg", 5, 2, 14.00, 0, 0, 1),
            ("AM-SHAMP", "Shampoo 30ml", "Amenities", "housekeeping", "bottle", 300, 100, 0.25, 0, 0, 2),
            ("AM-SOAP", "Soap Bar", "Amenities", "housekeeping", "bar", 260, 100, 0.20, 0, 0, 2),
            ("AM-TOOTH", "Dental Kit", "Amenities", "housekeeping", "kit", 60, 50, 0.45, 2.00, 1, 2),
            ("CL-DETER", "Multi-surface Cleaner 5L", "Cleaning", "housekeeping", "can", 6, 4, 12.00, 0, 0, 2),
            ("CL-BAGS", "Trash Bags (roll)", "Cleaning", "housekeeping", "roll", 3, 10, 3.50, 0, 0, 2),
            ("LN-TOWEL", "Bath Towel", "Linen", "housekeeping", "pcs", 180, 80, 6.50, 0, 0, 3),
            ("LN-SHEET", "Bed Sheet Set (King)", "Linen", "housekeeping", "set", 70, 40, 18.00, 0, 0, 3),
            ("LN-ROBE", "Bathrobe", "Linen", "housekeeping", "pcs", 25, 10, 22.00, 45.00, 1, 3),
            ("MT-BULB", "LED Bulb E27", "Electrical", "maintenance", "pcs", 40, 15, 2.50, 0, 0, 2),
        ]
        self.item_ids = {}
        admin = self.users["admin"]
        for sku, name, cat, dept, unit, qty, reorder, cost, price, charge, sup in items:
            iid = self.r.items.insert(sku=sku, name=name, category=cat, department=dept, unit=unit, quantity=qty,
                                      reorder_level=reorder, cost=cost, price=price, chargeable=charge, supplier_id=sup)
            self.r.movements.insert(item_id=iid, kind="receive", change=qty, balance_after=qty, unit_cost=cost,
                                    reason="Opening stock", created_by=admin)
            self.item_ids[sku] = iid

    def _menu(self):
        menu = [
            ("Full English Breakfast", "Eggs, toast, beef sausage, tomato", "Breakfast", 18.0, 15,
             [("KT-EGGS", 2), ("KT-BREAD", 0.2)]),
            ("Classic Burger & Fries", "180g beef patty, lettuce, house sauce", "Mains", 21.0, 20,
             [("KT-BEEF", 1), ("KT-BREAD", 0.15), ("KT-LETTC", 0.1)]),
            ("Spaghetti Pomodoro", "Fresh tomato sauce, basil, parmesan", "Mains", 17.0, 15,
             [("KT-PASTA", 0.15), ("KT-TOMSC", 0.12)]),
            ("Grilled Salmon", "With seasonal greens", "Mains", 29.0, 25, [("KT-SALMN", 1), ("KT-LETTC", 0.2)]),
            ("Caesar Salad", "Romaine, croutons, parmesan", "Starters", 13.0, 10, [("KT-LETTC", 0.5), ("KT-BREAD", 0.05)]),
            ("Espresso", "Double shot", "Drinks", 4.0, 3, [("KT-COFFE", 0.018)]),
            ("Fresh Orange Juice", "Freshly squeezed", "Drinks", 6.0, 5, []),
        ]
        for name, desc, cat, price, prep, ingredients in menu:
            mid = self.r.menu.insert(name=name, description=desc, category=cat, price=price, prep_minutes=prep)
            self.r.menu.set_ingredients(mid, [{"item_id": self.item_ids[s], "quantity": q} for s, q in ingredients])

    def _reservations(self):
        g = self.guest_ids
        admin = self.users["admin"]
        rate = {n: self.r.rooms.get(rid)["base_rate"] for n, rid in self.room_ids.items()}
        plan = [
            # code, guest, room, ci, co, adults, children, status, source
            ("RHV1001", g[0], "301", -2, 2, 2, 0, "checked_in", "online"),
            ("RHV1002", g[1], "105", -1, 1, 2, 0, "checked_in", "booking.com"),
            ("RHV1003", g[2], "202", -3, 0, 2, 0, "checked_in", "phone"),
            ("RHV1004", g[3], "401", 0, 4, 2, 1, "booked", "direct"),
            ("RHV1005", g[4], "203", 0, 3, 2, 0, "booked", "expedia"),
            ("RHV1006", g[5], "101", 1, 3, 1, 0, "booked", "walk-in"),
            ("RHV1007", g[6], "304", 2, 6, 3, 1, "booked", "direct"),
            ("RHV1008", g[7], "106", -6, -2, 2, 0, "checked_out", "booking.com"),
            ("RHV1009", g[8], "205", -9, -5, 1, 0, "checked_out", "phone"),
            ("RHV1010", g[9], "102", 5, 8, 1, 0, "booked", "direct"),
            ("RHV1011", g[0], "206", -12, -10, 2, 0, "checked_out", "online"),
            ("RHV1012", g[3], "107", -4, -1, 2, 0, "cancelled", "expedia"),
            ("RHV1013", g[0], "204", 20, 23, 2, 0, "booked", "online"),
        ]
        self.res_ids = {}
        for code, gid, room, ci, co, ad, ch, status, source in plan:
            rid = self.r.reservations.insert(
                code=code, guest_id=gid, room_id=self.room_ids[room], check_in=self.d(ci), check_out=self.d(co),
                adults=ad, children=ch, rate=rate[room], status=status, source=source, created_by=admin,
                checked_in_at=self.d(ci) + " 14:20:00" if status in ("checked_in", "checked_out") else None,
                checked_out_at=self.d(co) + " 10:45:00" if status == "checked_out" else None,
                cancelled_at=self.d(ci - 3) + " 09:00:00" if status == "cancelled" else None)
            self.res_ids[code] = rid
            if status == "checked_out":
                self.r.charges.insert(reservation_id=rid, description="Breakfast Buffet", category="Food & Beverage",
                                      quantity=2, unit_price=18, amount=36, created_by=admin)
                total = round(((co - ci) * rate[room] + 36) * 1.10, 2)
                self.r.payments.insert(reservation_id=rid, amount=total, method="card", reference="POS-" + code[-4:],
                                       created_by=admin)
        self.r.payments.insert(reservation_id=self.res_ids["RHV1001"], amount=200, method="card", reference="Deposit",
                               created_by=admin)
        self.r.reviews.insert(reservation_id=self.res_ids["RHV1011"], rating=5, published=1,
                              comment="Wonderful stay, the harbour view was stunning and the staff were lovely.",
                              reply="Thank you Amelia, we can't wait to welcome you back!")
        self.r.reviews.insert(reservation_id=self.res_ids["RHV1008"], rating=4, published=1,
                              comment="Great breakfast and very clean rooms. Parking was a little tight.")
        for room in ("103", "301", "105", "202", "204"):
            self.r.rooms.set_status(self.room_ids[room], "dirty")

    def _operations(self):
        maid, maid2, staff, chef = (self.users[k] for k in ("maid", "maid2", "frontdesk", "chef"))
        today = self.d(0)
        for room, kind, who, prio in [("103", "checkout_clean", maid, "high"), ("204", "checkout_clean", maid, "normal"),
                                      ("301", "stayover", maid2, "normal"), ("105", "stayover", None, "normal"),
                                      ("202", "stayover", maid2, "low")]:
            self.r.housekeeping.insert(room_id=self.room_ids[room], kind=kind, priority=prio, assigned_to=who,
                                       due_date=today, created_by=staff)
        self.r.rooms.set_status(self.room_ids["208"], "maintenance", "AC unit repair")
        self.r.maintenance.insert(code="MT1001", room_id=self.room_ids["208"], title="Air conditioning not cooling",
                                  description="Unit makes noise and blows warm air", priority="high", status="in_progress",
                                  out_of_order=1, reported_by=maid)
        self.r.maintenance.insert(code="MT1002", location="Lobby", title="Flickering light near elevator",
                                  priority="low", reported_by=staff)
        self.r.guest_requests.insert(reservation_id=self.res_ids["RHV1001"], kind="amenity",
                                     message="Could we have two extra pillows please?")
        oid = self.r.orders.insert(code="OR1001", reservation_id=self.res_ids["RHV1002"], status="pending", total=25.0,
                                   placed_via="guest", notes="No onions please")
        self.r.orders.add_line(oid, 2, "Classic Burger & Fries", 1, 21.0)
        self.r.orders.add_line(oid, 6, "Espresso", 1, 4.0)
        self.r.lost_found.insert(room_id=self.room_ids["106"], description="Black phone charger", found_by=maid)
        req = self.r.stock_requests.insert(code="SR1001", department="kitchen", requested_by=chef,
                                           notes="For tomorrow's breakfast service")
        self.r.stock_requests.add_line(req, self.item_ids["KT-EGGS"], 60)
