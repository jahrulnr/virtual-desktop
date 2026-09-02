#!/bin/sh
set -eu

/opt/relay/scripts/validate-config.sh

install -d -m 0710 -o desktop -g relayapi /run/user/1000
install -d -m 0710 -o desktop -g relayapi /run/user/1000/at-spi
install -d -m 0750 -o relayapi -g relayapi /run/user/1000/relay-tmux
install -d -m 0750 -o root -g relayapi /run/ai-desktop
install -d -m 0770 -o root -g relayaccess /run/relay-access
install -d -m 0700 -o desktop -g desktop /run/relay-vnc
install -d -m 1777 -o root -g root /tmp/.X11-unix
install -d -m 0700 -o root -g root /var/lib/relay
install -d -m 0700 -o coddy -g coddy /var/lib/coddy
install -d -m 0755 -o desktop -g desktop /home/desktop/Downloads /home/desktop/Desktop /home/desktop/workspace

if [ ! -e /home/desktop/.relay-xfce-v1 ]; then
  cp -a /opt/relay/home-template/.config /home/desktop/
  cp -a /opt/relay/home-template/.local /home/desktop/
  touch /home/desktop/.relay-xfce-v1
fi
# Keep the launcher panel behavior in sync for already-initialized named
# volumes without resetting unrelated user-owned XFCE preferences.
if [ ! -e /home/desktop/.relay-xfce-v2 ]; then
  install -D -m 0644 \
    /opt/relay/home-template/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-panel.xml \
    /home/desktop/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-panel.xml
  touch /home/desktop/.relay-xfce-v2
fi
install -d -m 0755 /home/desktop/.agents/skills
cp -a /opt/relay/home-template/.agents/skills/os-operator \
  /home/desktop/.agents/skills/

if [ ! -e /home/desktop/.relay-initialized ]; then
  touch /home/desktop/.relay-initialized
fi
chown -R desktop:desktop /home/desktop
chown -R coddy:coddy /var/lib/coddy
chmod 2775 /home/desktop/workspace

# control-api runs as relayapi (relayaccess) and writes screen recordings
# here. Must run after the recursive home chown above, which would
# otherwise reset the group ownership on every container start.
install -d /home/desktop/Downloads/recordings
chown desktop:relayaccess /home/desktop/Downloads/recordings
chmod 2770 /home/desktop/Downloads/recordings
chgrp relayaccess /home/desktop/Downloads
chmod 0751 /home/desktop/Downloads
if [ ! -L /workspace ]; then
  rm -rf /workspace
  ln -sfn /home/desktop/workspace /workspace
fi

# Chromium's singleton links include the previous container hostname and are not
# valid after a named home volume is attached to a recreated container. No desktop
# processes are running yet, so these exact profile locks are necessarily stale.
for relay_lock in \
  /home/desktop/.config/chromium/SingletonLock \
  /home/desktop/.config/chromium/SingletonCookie \
  /home/desktop/.config/chromium/SingletonSocket; do
  if [ -e "$relay_lock" ] || [ -L "$relay_lock" ]; then
    unlink "$relay_lock"
  fi
done

python3 /opt/relay/scripts/configure-chromium-profile.py

if [ "${RESTORE_INSTALLS:-true}" = true ] && [ -s /var/lib/relay/install-manifest.json ]; then
  if ! python3 /opt/relay/broker/restore_installs.py; then
    echo "Warning: one or more approved install plans could not be restored" >&2
  fi
fi

if [ -n "${VNC_PASSWORD:-}" ]; then
  relay_vnc_password=$VNC_PASSWORD
  relay_vnc_source=provided
else
  relay_vnc_password=$(python3 -c 'import secrets,string; print("".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(8)))')
  relay_vnc_source=generated
fi

if [ -n "${CONTROL_TOKEN:-}" ]; then
  relay_operator_token=$CONTROL_TOKEN
  relay_token_source=provided
else
  relay_operator_token=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
  relay_token_source=generated
fi

x11vnc -storepasswd "$relay_vnc_password" /run/relay-vnc/vnc.pass >/dev/null
printf '%s\n' "$relay_operator_token" > /run/ai-desktop/operator-token
printf '%s\n' "$relay_vnc_password" > /run/ai-desktop/human-token
chown desktop:desktop /run/relay-vnc/vnc.pass
chown relayapi:relayapi /run/ai-desktop/operator-token /run/ai-desktop/human-token
chmod 0600 /run/relay-vnc/vnc.pass /run/ai-desktop/operator-token /run/ai-desktop/human-token

if [ "$relay_vnc_source" = generated ]; then
  printf 'Relay one-time VNC password: %s\n' "$relay_vnc_password"
else
  printf 'Relay VNC password: supplied through environment (not logged)\n'
fi
if [ "$relay_token_source" = generated ]; then
  printf 'Relay operator bearer token: %s\n' "$relay_operator_token"
else
  printf 'Relay operator bearer token: supplied through environment (not logged)\n'
fi

unset VNC_PASSWORD CONTROL_TOKEN relay_vnc_password relay_operator_token
exec /usr/bin/supervisord -c /etc/supervisor/supervisord.conf
