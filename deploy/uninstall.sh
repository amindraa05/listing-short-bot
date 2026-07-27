#!/usr/bin/env bash
# Remove the listing-short paper trader and nothing else.
#
# Only touches what install.sh created: two systemd units named listingbot-*, the
# listingbot user, and /opt/listing-bot. It refuses to remove a directory that lacks
# the marker file the installer wrote, so it can never delete somebody else's work.
#
# Collected data is preserved by default — the whole point of the exercise is the
# record. Pass --purge-data to delete it too.
set -euo pipefail

APP_USER="listingbot"
APP_DIR="/opt/listing-bot"
UNIT_PREFIX="listingbot"
PURGE=0
[ "${1:-}" = "--purge-data" ] && PURGE=1

say() { printf '\n\033[1m== %s\033[0m\n' "$1"; }
[ "$(id -u)" -eq 0 ] || { echo "run as root"; exit 1; }

say "stopping our units only"
for unit in "${UNIT_PREFIX}.timer" "${UNIT_PREFIX}.service"; do
  if systemctl list-unit-files --no-legend 2>/dev/null | grep -q "^${unit}"; then
    systemctl disable --now "$unit" >/dev/null 2>&1 || true
    rm -f "/etc/systemd/system/${unit}"
    echo "   removed $unit"
  fi
done
systemctl daemon-reload
systemctl reset-failed 2>/dev/null || true

say "data"
if [ -d "$APP_DIR/data" ]; then
  if [ "$PURGE" -eq 1 ]; then
    rm -rf "$APP_DIR/data"
    echo "   data deleted (--purge-data was given)"
  else
    KEEP="/root/listingbot-data-$(date -u +%Y%m%d-%H%M%S)"
    cp -a "$APP_DIR/data" "$KEEP"
    echo "   data preserved at $KEEP"
  fi
fi

say "directory"
if [ -d "$APP_DIR" ]; then
  if [ -f "$APP_DIR/.listingbot" ]; then
    rm -rf "$APP_DIR"
    echo "   removed $APP_DIR"
  else
    echo "   REFUSING to remove $APP_DIR — no installer marker, not ours" >&2
  fi
fi

say "user"
if id "$APP_USER" >/dev/null 2>&1; then
  userdel -r "$APP_USER" 2>/dev/null || userdel "$APP_USER" 2>/dev/null || true
  echo "   removed user $APP_USER"
fi

say "verification"
echo "   nginx      : $(systemctl is-active nginx 2>/dev/null || echo n/a)"
for u in tgmm-monitor.service climate-paper.service; do
  systemctl list-unit-files --no-legend 2>/dev/null | grep -q "^$u" && \
    printf '   %-11s: %s\n' "${u%%.service}" "$(systemctl is-active "$u" 2>/dev/null)"
done
echo "   listingbot units remaining: $(systemctl list-unit-files --no-legend 2>/dev/null | grep -c "^${UNIT_PREFIX}" || echo 0)"
echo
echo "   done — nothing outside this project was modified"
