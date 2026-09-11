# Troubleshooting

## The client cannot acquire the lock

Check `/status` and make sure no other live session exists. Do not force-unlock unless you understand whether another PalServer may still be running.

## A different world is detected

Do not force the upload. Check the configured directory and `worldGuid`. This rejection is a safety feature that prevents one world from overwriting another.

## A pending ZIP remains

Do not delete it. The client preserves unconfirmed publications so they can be reconciled safely.

## Valheim says the host/token is disabled or mismatched

Check the Valheim panel: the user, registered computer and token must all be active, and `config.json` must use the exact stable `ClientId` assigned to that token. Do not reuse one computer's token on another PC.

## Valheim stops after heartbeat/lease degradation

This is intentional fail-closed behavior. The client reserves enough remaining TTL for a controlled shutdown rather than allowing the lock to expire while `valheim_server.exe` may still be writing. Do not force-unlock until the old server process is confirmed stopped.

If a lock later expires naturally, that still does **not** prove a failed/stranded old server process is gone. Confirm the old writer process and pending-session state before starting another host.

## Backup state is `unknown` or `stalePending`

The supervisor may have crashed or a queue row may be older than expected. These states are neither confirmed success nor permission to delete the protected version. Inspect `backup-supervisor` logs and the external backup destination.

## What can I paste in an issue?

Redact tokens, passwords, private paths, GUIDs, IP addresses, domains and personal names. Never attach a real save, ZIP or SQLite database to a public issue.

[[Resolucion-de-problemas|Leer en español]]
