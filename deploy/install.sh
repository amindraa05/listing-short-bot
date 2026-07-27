#!/usr/bin/env bash
# Install the listing-short paper trader.
#
# THIS HOST RUNS OTHER PEOPLE'S WORK, INCLUDING LIVE TRADING. The design guarantees no
# collision rather than merely avoiding it:
#
#   * binds NO port. The bot only makes outbound HTTPS calls, so there is nothing for
#     nginx (80/443), IB Gateway (4002) or the TGMM uvicorn (8100) to contend with.
#   * touches no nginx config, no certificate, no domain, no shared file.
#   * installs no packages. Python 3.12 stdlib only — no pip, no venv, no apt.
#   * runs as its own unprivileged user with its own home, never root.
#   * every systemd unit is prefixed listingbot- so it cannot clash with the existing
#     climate-*, tgmm-* or idx-* units.
#   * capped at 256M memory and 15% CPU with Nice=10, because 2 vCPU are shared with
#     the operator's live trading and that must always win.
#
# Idempotent: safe to re-run. Removes nothing it did not create.
set -euo pipefail

APP_USER="listingbot"
APP_DIR="/opt/listing-bot"
UNIT_PREFIX="listingbot"
PY="/usr/bin/python3"

say() { printf '\n\033[1m== %s\033[0m\n' "$1"; }
ok()  { printf '   ok  %s\n' "$1"; }

[ "$(id -u)" -eq 0 ] || { echo "run as root"; exit 1; }

say "pre-flight — refusing to proceed if anything looks contested"
for p in 80 443 4002 8100; do
  ss -tlnp 2>/dev/null | grep -q ":$p " && ok "port $p in use by something else (we bind none)"
done
for unit in "${UNIT_PREFIX}.service" "${UNIT_PREFIX}.timer"; do
  if systemctl list-unit-files --no-legend 2>/dev/null | grep -q "^${unit}"; then
    ok "$unit already present — will be replaced"
  fi
done
if [ -e "$APP_DIR" ] && [ ! -f "$APP_DIR/.listingbot" ]; then
  echo "   REFUSING: $APP_DIR exists but was not created by this installer." >&2
  exit 1
fi
"$PY" -c 'import sys,sqlite3,urllib.request,json; assert sys.version_info>=(3,10)' \
  || { echo "python3 too old or missing stdlib modules"; exit 1; }
ok "python $($PY -V 2>&1 | cut -d" " -f2) with sqlite3, urllib, json"

say "user"
if id "$APP_USER" >/dev/null 2>&1; then
  ok "$APP_USER exists"
else
  useradd --system --create-home --home-dir "/home/$APP_USER" \
          --shell /usr/sbin/nologin "$APP_USER"
  ok "created system user $APP_USER (no login shell)"
fi

say "directory"
mkdir -p "$APP_DIR" "$APP_DIR/data"
touch "$APP_DIR/.listingbot"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"
chmod 750 "$APP_DIR"
ok "$APP_DIR owned by $APP_USER, mode 750"

say "code"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
install -o "$APP_USER" -g "$APP_USER" -m 640 "$SRC"/listingbot/*.py -D -t "$APP_DIR/listingbot/"
chown "$APP_USER:$APP_USER" "$APP_DIR/listingbot"
chmod 750 "$APP_DIR/listingbot"
ok "installed $(ls -1 "$APP_DIR/listingbot"/*.py | wc -l) modules from $SRC"

say "systemd units"
cat > "/etc/systemd/system/${UNIT_PREFIX}.service" <<UNIT
[Unit]
Description=Listing-short paper trader (records only, places no orders)
Documentation=https://amindraa05.github.io/listing-short-bot/
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
Environment=LISTINGBOT_HOME=${APP_DIR}
Environment=PYTHONUNBUFFERED=1
ExecStart=${PY} -m listingbot.cli tick

# This box also runs the operator's live trading. It always wins.
Nice=10
IOSchedulingClass=idle
CPUQuota=15%
MemoryMax=256M
TasksMax=32
TimeoutStartSec=600

# Nothing outside its own directory is reachable or writable.
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=${APP_DIR}/data
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
RestrictRealtime=yes
LockPersonality=yes
UNIT

cat > "/etc/systemd/system/${UNIT_PREFIX}.timer" <<UNIT
[Unit]
Description=Run the listing-short paper trader every 5 minutes

[Timer]
OnBootSec=3min
OnUnitActiveSec=5min
AccuracySec=30s
RandomizedDelaySec=20s
Persistent=true
Unit=${UNIT_PREFIX}.service

[Install]
WantedBy=timers.target
UNIT
ok "wrote ${UNIT_PREFIX}.service and ${UNIT_PREFIX}.timer"

say "enable"
systemctl daemon-reload
systemctl enable --now "${UNIT_PREFIX}.timer" >/dev/null
ok "timer enabled and started"

say "first run"
# cd first: the unit file sets WorkingDirectory, but this manual invocation needs the
# package's parent directory on sys.path or python cannot find listingbot at all.
if (cd "$APP_DIR" && sudo -u "$APP_USER" env LISTINGBOT_HOME="$APP_DIR" \
      "$PY" -m listingbot.cli tick) 2>&1 | sed 's/^/   /' ; then
  ok "tick completed"
else
  echo "   tick returned non-zero — check: journalctl -u ${UNIT_PREFIX}.service -n 50"
fi

say "verification — proof nothing else was disturbed"
echo "   ports we listen on: $(ss -tlnp 2>/dev/null | grep -c listingbot || true) (expected 0)"
echo "   nginx still active: $(systemctl is-active nginx 2>/dev/null || echo n/a)"
echo "   other units untouched:"
for u in tgmm-monitor.service climate-paper.service; do
  systemctl list-unit-files --no-legend 2>/dev/null | grep -q "^$u" && \
    printf '     %-26s %s\n' "$u" "$(systemctl is-active "$u" 2>/dev/null)"
done
echo
echo "   status   : cd $APP_DIR && sudo -u $APP_USER env LISTINGBOT_HOME=$APP_DIR $PY -m listingbot.cli status"
echo "   logs     : journalctl -u ${UNIT_PREFIX}.service -f"
echo "   next run : $(systemctl list-timers "${UNIT_PREFIX}.timer" --no-legend 2>/dev/null | awk '{print $1, $2}')"
echo "   uninstall: bash $SRC/deploy/uninstall.sh"
