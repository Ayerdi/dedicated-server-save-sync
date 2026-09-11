# Managed computers

Some game deployments can opt into `managedHosts`. The experimental Valheim descriptor enables it; stable Palworld v2.2.2 does not.

Managed access separates the **person** from the **physical PC**:

- Authentik authenticates the username;
- Save Sync stores whether that user is active and its role;
- each approved PC is registered with a stable `ClientId`;
- each PC receives its own API token bound to that registered host;
- lock/publication history records computer provenance.

Creating a user in the Save Sync panel does **not** create the corresponding Authentik account. Authentik remains responsible for authentication; Save Sync only authorizes the already-authenticated username.

## Administrator workflow

1. Open `/games/<gameKey>` as an administrator.
2. Create/enable the Save Sync user if needed.
3. Register the physical computer and its stable `ClientId`.
4. Create a token for that computer.
5. Copy the plaintext token once to that PC and configure the same `ClientId` locally.

Computer-bound tokens are synchronization credentials only. They cannot call administrative endpoints even if the owning user is an admin.

Legacy unbound tokens may remain visible for migration/administration, but they cannot acquire or continue a managed-host sync session.

## Disable/revoke behavior

- disabling a user or host blocks trusted session activity;
- revoking the exact token also blocks it;
- a token cannot impersonate a second registered `ClientId`;
- an active lock is deliberately preserved instead of being deleted immediately, so another host cannot start while the previous machine may still be shutting down;
- after a safety incident, force-unlock only when you have confirmed that the previous game server can no longer write the authoritative world.

Provision a separate token and DPAPI secrets file on every authorized PC. Do not use one copied secrets file as the machine-authorization mechanism.

[[Equipos-Gestionados|Leer en español]]
