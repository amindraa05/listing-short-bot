#!/usr/bin/env bash
# Set up publishing of the monitor page to GitHub Pages, and nothing else.
#
# Separate from install.sh on purpose: the trading loop must keep working if publishing
# breaks, and publishing is the only part that needs an outbound SSH key and write access
# to a repository. Keeping them apart means a revoked key cannot stop the measurement.
#
# The private key is generated HERE and never leaves this host. Its public half is
# printed for registration as a repository deploy key.
#
#   sudo bash deploy/install_publish.sh                 # first run: prints the key
#   sudo bash deploy/install_publish.sh --enable        # after the key is registered
set -euo pipefail

APP_USER="listingbot"
APP_DIR="/opt/listing-bot"
REPO_DIR="$APP_DIR/repo"
KEY="$APP_DIR/.ssh/id_publish"
REMOTE="git@github.com:amindraa05/listing-short-bot.git"
UNIT="listingbot-publish"
PY="/usr/bin/python3"
ENABLE=0
[ "${1:-}" = "--enable" ] && ENABLE=1

say() { printf '\n\033[1m== %s\033[0m\n' "$1"; }
ok()  { printf '   ok  %s\n' "$1"; }
[ "$(id -u)" -eq 0 ] || { echo "run as root"; exit 1; }
[ -f "$APP_DIR/.listingbot" ] || { echo "$APP_DIR is not an install of this bot"; exit 1; }

say "deploy key"
install -d -o "$APP_USER" -g "$APP_USER" -m 700 "$APP_DIR/.ssh"
if [ -f "$KEY" ]; then
  ok "key already present"
else
  sudo -u "$APP_USER" ssh-keygen -q -t ed25519 -N "" -f "$KEY" \
    -C "listingbot-publish@$(hostname)"
  ok "generated $KEY"
fi
chmod 600 "$KEY"; chown "$APP_USER:$APP_USER" "$KEY" "$KEY.pub"

# Pinned host key, so the first connection cannot be answered by anything else.
sudo -u "$APP_USER" bash -c "ssh-keyscan -t ed25519 github.com 2>/dev/null \
  > $APP_DIR/.ssh/known_hosts"
chmod 600 "$APP_DIR/.ssh/known_hosts"
GIT_SSH="ssh -i $KEY -o IdentitiesOnly=yes -o UserKnownHostsFile=$APP_DIR/.ssh/known_hosts"

if [ "$ENABLE" -eq 0 ]; then
  say "register this as a deploy key WITH WRITE ACCESS, then re-run with --enable"
  echo
  cat "$KEY.pub"
  echo
  echo "   https://github.com/amindraa05/listing-short-bot/settings/keys/new"
  exit 0
fi

say "repository"
if [ -d "$REPO_DIR/.git" ]; then
  sudo -u "$APP_USER" env GIT_SSH_COMMAND="$GIT_SSH" git -C "$REPO_DIR" remote set-url origin "$REMOTE"
  sudo -u "$APP_USER" env GIT_SSH_COMMAND="$GIT_SSH" git -C "$REPO_DIR" fetch -q origin
  sudo -u "$APP_USER" git -C "$REPO_DIR" reset -q --hard origin/main
  ok "existing clone updated"
else
  sudo -u "$APP_USER" env GIT_SSH_COMMAND="$GIT_SSH" \
    git clone -q --depth 50 "$REMOTE" "$REPO_DIR"
  ok "cloned into $REPO_DIR"
fi
sudo -u "$APP_USER" git -C "$REPO_DIR" config core.sshCommand "$GIT_SSH"
sudo -u "$APP_USER" git -C "$REPO_DIR" config user.name listingbot
sudo -u "$APP_USER" git -C "$REPO_DIR" config user.email listingbot@localhost
sudo -u "$APP_USER" git -C "$REPO_DIR" config commit.gpgsign false

say "systemd units"
cat > "/etc/systemd/system/${UNIT}.service" <<UNIT
[Unit]
Description=Publish the listing-short monitor page to GitHub Pages
Documentation=https://amindraa05.github.io/listing-short-bot/monitor.html
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
Environment=LISTINGBOT_HOME=${APP_DIR}
Environment=LISTINGBOT_REPO=${REPO_DIR}
Environment=HOME=${APP_DIR}
Environment=PYTHONUNBUFFERED=1
ExecStart=${PY} -m listingbot.cli publish

# Same discipline as the trading unit: this box runs the operator's live trading.
Nice=15
IOSchedulingClass=idle
CPUQuota=10%
MemoryMax=192M
TasksMax=32
TimeoutStartSec=300

NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=${APP_DIR}/data ${REPO_DIR} ${APP_DIR}/.ssh
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
RestrictRealtime=yes
LockPersonality=yes
UNIT

cat > "/etc/systemd/system/${UNIT}.timer" <<UNIT
[Unit]
Description=Publish the listing-short monitor page every 30 minutes

[Timer]
OnBootSec=8min
OnUnitActiveSec=30min
AccuracySec=2min
RandomizedDelaySec=3min
Persistent=true
Unit=${UNIT}.service

[Install]
WantedBy=timers.target
UNIT
ok "wrote ${UNIT}.service and ${UNIT}.timer"

systemctl daemon-reload
systemctl enable --now "${UNIT}.timer" >/dev/null
ok "timer enabled"

say "first publish"
systemctl start "${UNIT}.service" || true
journalctl -u "${UNIT}.service" -n 12 --no-pager | sed 's/^/   /'

say "verification"
echo "   ports we listen on : $(ss -tlnp 2>/dev/null | grep -c listingbot || true) (expected 0)"
echo "   nginx              : $(systemctl is-active nginx 2>/dev/null || echo n/a)"
echo "   trading timer      : $(systemctl is-active listingbot.timer 2>/dev/null)"
echo "   publish timer      : $(systemctl is-active ${UNIT}.timer 2>/dev/null)"
echo "   page               : https://amindraa05.github.io/listing-short-bot/monitor.html"
