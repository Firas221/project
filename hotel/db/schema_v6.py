"""Migration 6: extra beds and infants."""

MIGRATION_6 = """
-- a room type can take a number of extra beds, each at a nightly price
ALTER TABLE room_types ADD COLUMN max_extra_beds INTEGER NOT NULL DEFAULT 0;
ALTER TABLE room_types ADD COLUMN extra_bed_rate REAL NOT NULL DEFAULT 0;

-- infants: children below the hotel's free age. They pay nothing and do not count towards the room's capacity.
ALTER TABLE reservations ADD COLUMN infants INTEGER NOT NULL DEFAULT 0;
ALTER TABLE reservations ADD COLUMN extra_beds INTEGER NOT NULL DEFAULT 0;
"""
