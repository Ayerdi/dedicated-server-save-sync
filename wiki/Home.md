# Dedicated Server Save Sync

**Stable release: v2.2.2 · Palworld**

**Development preview on `main`: experimental Valheim 1.0 + managed computers**

Save Sync lets multiple PCs alternate as the Palworld dedicated-server host without manually passing save archives around or keeping one gaming PC online permanently.

## Start here

- [[Installation]]
- [[Windows-Client]]
- [[Backups-and-Recovery]]
- [[Architecture]]
- [[Troubleshooting]]
- [[FAQ]]
- [[Valheim-Experimental]]
- [[Managed-Computers]]
- [[Inicio|Español]]

## What it protects

Save Sync combines one authoritative version with `baseVersion`, an exclusive heartbeat lock, adapter-defined `saveIdentity`, SHA-256 verification and atomic publication. Palworld exposes that identity as `worldGuid`; experimental Valheim uses `worldUid`. A stale copy cannot silently overwrite newer progress.

External backups are durably queued in SQLite and executed by a supervisor independent from the web process. Restarting the web service does not lose pending backup work.

Save Sync intentionally **cannot merge worlds that already diverged**. When two independent copies contain different progress, a human must decide which one is authoritative.

The stable release remains Palworld-only. The development tree also contains an isolated Valheim adapter; use [[Valheim-Experimental]] for its status and safety requirements rather than following the stable release instructions blindly.

## Resources

- [Repository](https://github.com/Ayerdi/dedicated-server-save-sync)
- [Website](https://ayerdi.github.io/dedicated-server-save-sync/)
- [Releases](https://github.com/Ayerdi/dedicated-server-save-sync/releases)
- [Security](https://github.com/Ayerdi/dedicated-server-save-sync/security/policy)
