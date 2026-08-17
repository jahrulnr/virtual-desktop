# syntax=docker/dockerfile:1

FROM golang:1.25-bookworm AS computer-mcp-build

WORKDIR /src/computer-mcp
COPY computer-mcp/go.mod computer-mcp/go.sum ./
RUN go mod download
COPY computer-mcp/ ./
RUN CGO_ENABLED=0 go test ./... \
    && CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/relay-computer-mcp ./cmd/server

FROM golang:1.25-bookworm AS coddy-build

ARG CODDY_REF=2ba0ec9cc531e31954c2565b2984d92d4bc890d3
RUN git clone --filter=blob:none https://github.com/coddy-project/coddy-agent.git /src/coddy \
    && git -C /src/coddy checkout --detach "$CODDY_REF"
COPY agent/patches/0001-preserve-mcp-image-results.patch /tmp/coddy.patch
RUN git -C /src/coddy apply --check /tmp/coddy.patch \
    && git -C /src/coddy apply /tmp/coddy.patch
WORKDIR /src/coddy
RUN CGO_ENABLED=0 go test ./internal/mcp ./internal/agent ./internal/llm \
    && CGO_ENABLED=0 go build -trimpath -tags=http -ldflags="-s -w" -o /out/coddy ./cmd/coddy

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
        ffmpeg \
        tmux \
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

ARG INSTALL_SELKIES=false
RUN if [ "$INSTALL_SELKIES" = "true" ]; then \
      apt-get update \
      && apt-get install -y --no-install-recommends \
        gstreamer1.0-plugins-base \
        gstreamer1.0-plugins-good \
        gstreamer1.0-tools \
        python3-pip \
      && PIP_BREAK_SYSTEM_PACKAGES=1 pip3 install --no-cache-dir selkies \
      && rm -rf /var/lib/apt/lists/*; \
    fi

RUN groupadd --gid 1000 desktop \
    && groupadd --gid 1001 relayapi \
    && groupadd --gid 1002 relayaccess \
    && groupadd --gid 1003 coddy \
    && useradd --uid 1000 --gid desktop --groups relayaccess --create-home --shell /bin/bash desktop \
    && useradd --uid 1001 --gid relayapi --groups relayaccess --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin relayapi \
    && useradd --uid 1002 --gid coddy --groups desktop --no-create-home --home-dir /var/lib/coddy --shell /usr/sbin/nologin coddy \
    && install -d -o desktop -g desktop /home/desktop/Downloads /home/desktop/Desktop /home/desktop/workspace \
    && install -d -o coddy -g coddy -m 0700 /var/lib/coddy \
    && install -d -o coddy -g coddy -m 0750 /opt/relay-agent/skills/os-operator \
    && install -d /opt/relay/control /opt/relay/broker /opt/relay/web /usr/share/licenses/coddy

COPY --from=computer-mcp-build /out/relay-computer-mcp /usr/local/bin/relay-computer-mcp
COPY --from=coddy-build /out/coddy /usr/local/bin/coddy
COPY --from=coddy-build /src/coddy/LICENSE /usr/share/licenses/coddy/LICENSE
COPY desktop/control/ /opt/relay/control/
COPY desktop/broker/ /opt/relay/broker/
COPY desktop/config/supervisord.conf /etc/supervisor/supervisord.conf
COPY desktop/config/nginx.conf /etc/nginx/nginx.conf
COPY desktop/scripts/ /opt/relay/scripts/
COPY desktop/home/ /opt/relay/home-template/
COPY web/ /opt/relay/web/
COPY --chown=coddy:coddy agent/config.yaml /etc/coddy/config.yaml
COPY --chown=coddy:coddy agent/skills/os-operator/SKILL.md /opt/relay-agent/skills/os-operator/SKILL.md

RUN chmod 0755 /opt/relay/scripts/*.sh /opt/relay/control/*.py /opt/relay/broker/*.py \
    /opt/relay/home-template/.agents/skills/os-operator/scripts/*.py \
    && chown -R desktop:desktop /opt/relay/web \
    && rm -rf /etc/supervisor/conf.d \
    && rm -f /etc/nginx/sites-enabled/default

EXPOSE 8080
VOLUME ["/home/desktop", "/var/lib/relay", "/var/lib/coddy"]
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=6 \
  CMD /opt/relay/scripts/healthcheck.sh

ENTRYPOINT ["/opt/relay/scripts/entrypoint.sh"]
