# Troubleshooting

## Lock cannot be acquired

Check `/status`, make sure no other live session exists, and avoid force-unlock
unless you understand the current game-server state.

## A different world is detected

Do not force the upload. Check the configured directory and `worldGuid`. This is
a safety feature against overwriting another world.

## A pending ZIP remains

Do not delete it. The client preserves an unconfirmed publication for later
reconciliation.

## Backup state is `unknown`

A supervisor may have disappeared or a marker may be stale. `unknown` is
neither confirmed success nor confirmed failure. Verify external storage.

Never paste complete logs into a public issue. Redact tokens, paths, GUIDs, IPs
and domains.
