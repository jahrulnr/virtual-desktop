#!/bin/sh
set -eu

/opt/relay/scripts/wait-for-x.sh /usr/bin/xdotool mousemove 720 450
xset s off -dpms

(
  relay_wallpaper=/home/desktop/.local/share/backgrounds/relay-fields.png
  relay_attempt=0
  while [ "$relay_attempt" -lt 20 ]; do
    relay_properties=$(xfconf-query -c xfce4-desktop -l 2>/dev/null \
      | sed -n '/last-image$/p')
    if [ -n "$relay_properties" ]; then
      printf '%s\n' "$relay_properties" | while IFS= read -r relay_property; do
        xfconf-query -c xfce4-desktop -p "$relay_property" -s "$relay_wallpaper"
        relay_style=${relay_property%/last-image}/image-style
        xfconf-query -c xfce4-desktop -p "$relay_style" -s 5 2>/dev/null || true
      done
      break
    fi
    relay_attempt=$((relay_attempt + 1))
    sleep 1
  done
) &

(
  sleep 2
  chromium \
    --force-renderer-accessibility \
    --no-first-run \
    --hide-crash-restore-bubble \
    --disable-sync \
    --disable-features=TranslateUI \
    --window-size=1100,680 \
    --window-position=170,95 \
    about:blank >/tmp/chromium.log 2>&1
) &

exec /usr/bin/xfce4-session
