# FAQ

## Is this an alternative to Steam Cloud?

Not exactly. Save Sync coordinates a dedicated server: it versions the save, locks sessions and transports one authoritative world between authorized hosts.

The future broader project may explore device/cloud synchronization as a separate product mode, but that is intentionally outside this Palworld reference repository.

## Do I need to keep a Palworld server online 24/7?

No. The Save Sync web service must be reachable when hosts exchange the save, but PalServer only needs to run on the PC hosting the current session.

## Can it merge two different versions of a world?

No. It rejects conflicting publication attempts to prevent silent data loss, but it cannot semantically merge divergent Palworld progress.

## Should I deploy from `main`?

Not for production. Use the current stable tag, `v2.2.2`, and the client from that same release. `main` can contain changes that are not yet released.

## Why does the product say v2.2.2 while the client reports 1.2.0?

`v2.2.2` is the full product release. `clientVersion=1.2.0` is the internal Palworld adapter/client component version recorded in manifests and diagnostics. The backend does not use it as the product release number.

## Can I use this repository with other games?

The backend retains generic primitives, but this repository is maintained as the stable Palworld reference. Broad multi-game support belongs in the separate successor project.

## Is Spanish documentation available?

Yes. Start at [[Inicio]].
