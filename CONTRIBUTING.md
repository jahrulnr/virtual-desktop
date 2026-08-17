# Contributing to Relay AI Desktop

Relay sits at an awkward and interesting boundary: browser UI, Linux desktop
plumbing, input arbitration, and a deliberately narrow privilege broker all meet
in one container. Small changes can cross several trust boundaries, so a useful
contribution is one that explains its effect and proves the handoff still works.

## Before you start

You need Docker Engine with Compose, Python 3, and enough disk for the desktop
image. Fork or clone the repository, then build the reference environment:

```bash
docker compose up -d --build
make static
make smoke
```

The defaults are intentionally local and predictable. Keep port 3000 bound to
`127.0.0.1`; do not publish a test instance with the fixture credentials.

## Shape of a change

Keep the existing boundaries visible:

- Human takeover must remain immediate and must never create a second desktop.
- AI input must pass through the typed API and an active lease. Do not add raw
  shell, xdotool, VNC, Docker socket, or host-mount escape hatches.
- Package installation needs an exact, expiring, human-created approval.
- Desktop applications must not gain access to the API capability files or broker
  socket.
- Persistent data belongs in `/home/desktop` or `/var/lib/relay`; image defaults
  belong in the home template.

When a change alters one of those promises, update the relevant document under
`docs/` in the same pull request. Architecture changes deserve rationale, not
only a new configuration value.

## Tests

Run the smallest useful test while developing, then the full static suite before
opening a pull request:

```bash
make test
make static
```

Changes to Docker startup, the display stack, input, accessibility, noVNC, Nginx,
or control ownership also require a live run:

```bash
docker compose up -d --build
make smoke
```

For handoff or cursor changes, complete the manual two-controller test in
[docs/TESTING.md](docs/TESTING.md). Include the browser, host OS, and result in the
pull request.

## Pull requests

Prefer a focused change over a broad cleanup. In the description, state the user
problem, the trust boundary affected, and the evidence that the result works.
Screenshots are useful for visual changes; logs are useful only after secrets and
tokens have been removed.

Before submitting, check that:

- tests pass and documentation links resolve;
- no generated browser artifacts, credentials, tokens, profiles, or downloaded
  packages are committed;
- Compose remains loopback-only and contains no privileged mode, host namespace,
  host filesystem, or Docker socket access;
- new operator actions have validation, authorization, and conflict tests;
- UI changes preserve keyboard access, focus visibility, and observer-mode input
  blocking.

Security findings should follow [the private reporting guidance](.github/SECURITY.md)
instead of a public issue.

## License

The project is released under the [MIT License](LICENSE). By submitting a
contribution, you confirm that you have the right to submit it under that license.
