#!/bin/sh
# Example cron job (daily 03:15): copies the newest backups to another disk / cloud bucket.
#   15 3 * * * /opt/hotel/deploy/backup-offsite.sh
set -eu
SRC=/var/lib/hotel/backups
DEST=/mnt/offsite/hotel-backups      # e.g. a mounted NAS, or replace with: rclone copy "$SRC" remote:bucket
mkdir -p "$DEST"
cp -n "$SRC"/hotel-*.db "$DEST"/
find "$DEST" -name 'hotel-*.db' -mtime +90 -delete
