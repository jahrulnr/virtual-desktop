# syntax=docker/dockerfile:1

FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    DISPLAY=:0 \
    WIDTH=1440 \
    HEIGHT=900 \
    XDG_RUNTIME_DIR=/run/user/1000 \
    DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus \
    NO_AT_BRIDGE=0 \
    QT_ACCESSIBILITY=1 \
    GTK_MODULES=gail:atk-bridge

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        at-spi2-core \
        ca-certificates \
        chromium \
        chromium-sandbox \
        curl \
        dbus-x11 \
        fonts-dejavu-core \
        fonts-inter \
        greybird-gtk-theme \
        nginx \
        novnc \
        papirus-icon-theme \
        python3 \
        python3-pyatspi \
        scrot \
        supervisor \
        thunar \
        websockify \
        x11-utils \
        x11vnc \
        xdg-utils \
        xdotool \
        xfce4-appfinder \
        xfce4-panel \
        xfce4-session \
        xfce4-settings \
        xfce4-terminal \
        xfdesktop4 \
        xfwm4 \
        xvfb \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 1000 desktop \
    && groupadd --gid 1001 relayapi \
    && groupadd --gid 1002 relayaccess \
    && useradd --uid 1000 --gid desktop --groups relayaccess --create-home --shell /bin/bash desktop \
    && useradd --uid 1001 --gid relayapi --groups relayaccess --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin relayapi \
    && install -d -o desktop -g desktop /home/desktop/Downloads /home/desktop/Desktop \
    && install -d /opt/relay/control /opt/relay/broker /opt/relay/web

COPY desktop/control/ /opt/relay/control/
COPY desktop/broker/ /opt/relay/broker/
COPY desktop/config/supervisord.conf /etc/supervisor/supervisord.conf
COPY desktop/config/nginx.conf /etc/nginx/nginx.conf
COPY desktop/scripts/ /opt/relay/scripts/
COPY desktop/home/ /opt/relay/home-template/
COPY web/ /opt/relay/web/

RUN chmod 0755 /opt/relay/scripts/*.sh /opt/relay/control/*.py /opt/relay/broker/*.py \
    /opt/relay/home-template/.agents/skills/os-operator/scripts/*.py \
    && chown -R desktop:desktop /opt/relay/web \
    && rm -rf /etc/supervisor/conf.d \
    && rm -f /etc/nginx/sites-enabled/default

EXPOSE 8080
VOLUME ["/home/desktop", "/var/lib/relay"]
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=6 \
  CMD curl --fail --silent http://127.0.0.1:8080/api/v1/health >/dev/null || exit 1

ENTRYPOINT ["/opt/relay/scripts/entrypoint.sh"]
