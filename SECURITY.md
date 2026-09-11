# Security policy

## Supported versions

| Version | Security support |
|---|---|
| latest `2.x` release | Yes |
| older `2.x` releases | Best effort; upgrade first |
| `< 2.0` | No |

## Reporting a vulnerability

Do **not** open a public issue. Use GitHub's private **Report a vulnerability** flow:

<https://github.com/Ayerdi/dedicated-server-save-sync/security/advisories/new>

Private Vulnerability Reporting is enabled for this public repository.

Include the affected version, impact, minimal reproduction steps and known mitigations. Do not attach real saves, tokens or production configuration.

## Data that must never be committed

- real `.env` files;
- `pws_...` tokens;
- REST passwords or DPAPI exports;
- machine-specific `config.json`;
- saves, ZIP archives, SQLite databases and WAL/SHM sidecars;
- rendered Traefik runtime configuration;
- logs or screenshots that contain credentials;
- private domains, users, GUIDs or filesystem paths from a real deployment.

`.gitignore` is only a guardrail. Always review the diff and run the secret scanner.

## Threat model notes

- A stolen Bearer token has that user's privileges until it is revoked.
- In a `managedHosts` deployment, a computer-bound token is additionally restricted to its registered active host and matching `ClientId`; it is not an administrative credential even when owned by an administrator.
- The backend validates identity metadata and ZIP structure; it does not semantically parse `Level.sav`.
- DPAPI protects local secrets at rest, not against malware running as the same Windows user.
- DPAPI `CurrentUser` is user-profile scoped protection. Do not rely on it as the machine-authorization boundary; provision a distinct token/secrets file per authorized PC.
- The reverse proxy must strip client-supplied Authentik identity headers.
- SQLite and ZIP confidentiality still depend on correct host filesystem permissions.
- The Gitleaks and repository checks reduce accidental exposure; they do not replace secret rotation after a leak.

## Before a release

```bash
bash scripts/check-repository.sh
bash scripts/run-gitleaks.sh
git diff --cached
```

CI also runs dependency auditing, coverage, Docker E2E, crash/restart recovery tests and Pester. Automated tests do not replace an external backup or a controlled real-game acceptance test.
