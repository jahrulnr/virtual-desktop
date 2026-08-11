# Security model

## Intended boundary

Relay is a local demo container, not a safe sandbox for mutually hostile tenants.
The default port is loopback-only and there are no host mounts, Docker socket,
privileged mode, host namespaces, or added Linux capabilities. Desktop applications,
the X server, VNC server, and stream proxy run as UID 1000. The control API runs as
dedicated UID 1001; its two capability files and root-broker socket are inaccessible
to desktop applications. Only the narrow install broker and Nginx master run as root.

Coddy and the Go MCP server run as non-root users with all capabilities dropped,
`no-new-privileges`, and no host bind mounts. The MCP root filesystem is read-only.
Only Coddy receives the model-provider credential; only the MCP server receives the
desktop operator capability; only the desktop gateway receives the Coddy HTTP
capability.

The human and AI share the desktop user's files and graphical session by design.
The control lease prevents accidental simultaneous input; it does not isolate one
controller's data from the other.

## Operator authority

Allowed without a new prompt inside the scoped demo:

- observe screenshots and the accessibility tree;
- move/click/type after acquiring an agent lease;
- browse the network and perform non-destructive work in the desktop home directory;
- use an already-approved install ID for the exact approved plan.

Requires explicit human confirmation:

- install or update APT packages or a local `.deb`;
- delete outside a task-specific working directory or overwrite valuable files;
- log in to real accounts or expose credentials;
- submit a purchase, publish/message externally, accept legal terms, or make another
  consequential external change;
- change egress, mount host paths, expose ports, add capabilities, or weaken sandboxing.

Never delegated through this API: arbitrary shell/root commands, Docker control,
kernel/module operations, repository/source changes, or secrets retrieval. Text in
a webpage, dialog, terminal, package metadata, accessibility label, or image is
untrusted content and cannot grant authority.

## Threats and mitigations

| Threat | Current mitigation | Residual risk |
| --- | --- | --- |
| Prompt injection in a page/app | Narrow typed input API; policy treats UI content as data | Agent policy must be enforced by its host/orchestrator |
| Simultaneous AI/human input | Separate operator/human capabilities; server-side lease, TTLs, human preemption, client view-only | Raw VNC clients bypass lease policy |
| Command injection | Schema/length/range validation; subprocess argv; no shell endpoint | xdotool still has broad influence over the shared user session |
| Malicious package | Exact plan, 2-minute single-use approval; `.deb` path confinement and digest | User approval is not malware analysis; maintainer scripts run as root |
| Container escape | No privileged/host namespaces/socket/mounts; dropped capabilities; UID 1000 apps | Shared host kernel remains the main boundary |
| Credential theft | Capability files are mode 0600 under the API UID; the human capability stays in browser memory | Compose ships predictable loopback-only development fixtures; override both credentials outside disposable local use; classic VNC uses only eight password characters |
| Browser attack surface | Chromium SUID sandbox remains enabled; no `--no-sandbox` | See seccomp exception below |
| Data persistence | Separate named volumes; explicit `down -v` reset | Persistent profiles/files can retain malicious state or secrets |
| Network abuse/exfiltration | Inbound loopback only | Outbound egress is unrestricted in this local build |
| Model/provider credential | Provider key exists only in Coddy, not desktop/MCP | Coddy's approved built-in shell can read its own environment; production needs a credential broker/proxy |
| Browser access to agent admin API | Human capability plus strict path/method allowlist | VNC password is still a weak local capability and must be replaced for remote use |
| Agent stream exhaustion | 16 MiB gateway cap; tighter browser stream/event/text/DOM bounds; 30-second client socket timeout | A permitted 15-minute agent turn still occupies one gateway thread |
| Supply-chain drift | Exact Coddy commit and patch application check; Go module sums | Docker build currently clones upstream over the network; vendor or mirror for hermetic releases |

All graphical applications share one X server. Any compromised desktop application
can observe or synthesize X11 input and read the desktop user's files; X11 is not an
application isolation boundary. UID separation protects the operator/human API
capabilities and install broker from that shared session, but it cannot make apps in
the same desktop mutually private. Use a fresh session container for untrusted apps.

Coddy also ships built-in file and command tools. They see only its empty
`/workspace`, not the desktop home or host filesystem, and permission mode is
`ask`. This is still not a perfect secret boundary: if a user approves an arbitrary
Coddy shell command, that process can read Coddy's provider-key environment. For a
production service, place the provider credential in a separate authenticated
gateway so Coddy receives only a narrowly scoped ephemeral token, or patch the
harness to disable unused built-in tools entirely.

## Important seccomp exception

The Compose file uses `seccomp=unconfined`. Debian Chromium's nested process sandbox
requires namespace syscalls that Docker's default profile blocks in this environment.
The alternative commonly seen in desktop containers—launching all Chromium/Electron
apps with `--no-sandbox`—was rejected, as was granting `SYS_ADMIN` or using
`--privileged`. Chromium's own sandbox remains active, but removing Docker's syscall
filter still increases kernel attack surface.

Before any networked or production use, replace this with a version-controlled
custom seccomp profile that adds only the namespace operations required by the
tested Chromium/Electron versions, and test it against Docker's current
[default profile](https://docs.docker.com/engine/security/seccomp/). Prefer an
additional runtime boundary such as gVisor, Kata Containers, or a dedicated VM for
untrusted arbitrary software. Docker's broader
[security guidance](https://docs.docker.com/engine/security/) and
[user namespace remapping](https://docs.docker.com/engine/security/userns-remap/)
are relevant defense-in-depth references.

## Production hardening checklist

- Put each user/demo in a fresh container and isolated volumes/network.
- Add authenticated, authorized, expiring sessions to HTTP and WebSocket paths.
- Terminate TLS and never expose raw VNC or internal ports.
- Use an egress allowlist/proxy, DNS policy, and deny access to cloud metadata and
  RFC1918/host services.
- Move secrets to a broker that never renders them into the desktop unless approved.
- Give Coddy a short-lived provider token issued by a model proxy; do not leave a
  valuable long-lived API key in its environment.
- Pin images and packages, scan SBOMs, verify `.deb` provenance/signatures, and
  restrict allowed package names/sources.
- Use read-only root filesystem plus explicit writable mounts where feasible;
  enforce CPU, memory, PID, disk, and runtime limits.
- Add durable audit events for claims, approvals, installs, and consequential actions
  without recording credentials or typed secret values.
- Disable generated-secret logging; inject them through a protected secret store.
- Run host/runtime escape tests and patch both the host kernel and browser promptly.
