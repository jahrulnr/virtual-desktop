# Security policy

## Supported versions

Relay is currently an early reference implementation. Security fixes are applied
to the latest commit on the default branch; there are no supported release lines
yet.

## Reporting a vulnerability

Please do not open a public issue for a suspected vulnerability. Use GitHub's
**Report a vulnerability** flow in the repository Security tab when it is
available. If private reporting is not enabled, contact the repository owner
privately through their GitHub profile and include only enough detail to establish
a secure follow-up channel.

Useful reports explain the affected boundary, the minimum reproduction, expected
impact, and whether the issue can escape the container or expose another user's
data. Never include real credentials or unrelated personal data.

The current threat model, known limitations, and production hardening work are
documented in [docs/SECURITY.md](../docs/SECURITY.md).
