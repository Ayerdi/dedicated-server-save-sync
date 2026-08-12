# Troubleshooting

## The client cannot acquire the lock

Check `/status` and make sure no other live session exists. Do not force-unlock unless you understand whether another PalServer may still be running.

## A different world is detected

Do not force the upload. Check the configured directory and `worldGuid`. This rejection is a safety feature that prevents one world from overwriting another.

## A pending ZIP remains

Do not delete it. The client preserves unconfirmed publications so they can be reconciled safely.

## Backup state is `unknown` or `stalePending`

The supervisor may have crashed or a queue row may be older than expected. These states are neither confirmed success nor permission to delete the protected version. Inspect `backup-supervisor` logs and the external backup destination.

## What can I paste in an issue?

Redact tokens, passwords, private paths, GUIDs, IP addresses, domains and personal names. Never attach a real save, ZIP or SQLite database to a public issue.

[[Resolucion-de-problemas|Leer en español]]
