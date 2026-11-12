"""Migration 9: payments taken in a second currency."""

MIGRATION_9 = """
-- A payment is always booked in the hotel's own currency (amount). When the guest paid in the second
-- currency, these columns remember what was actually handed over and the rate used on that day.
ALTER TABLE payments ADD COLUMN currency TEXT NOT NULL DEFAULT '';
ALTER TABLE payments ADD COLUMN fx_rate REAL NOT NULL DEFAULT 0;
ALTER TABLE payments ADD COLUMN foreign_amount REAL NOT NULL DEFAULT 0;
"""
