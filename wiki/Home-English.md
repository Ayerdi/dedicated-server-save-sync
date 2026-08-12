# Dedicated Server Save Sync

**Stable release: v2.2.0 · Palworld**

Save Sync lets multiple PCs alternate as the Palworld dedicated-server host
without manually passing save archives around or keeping one gaming PC online
permanently.

## Start here

- [[Installation]]
- [[Windows-Client]]
- [[Backups-and-Recovery]]
- [[Troubleshooting]]
- [[FAQ]]
- [[Home|Español]]

## Safety model

Save Sync uses an authoritative version, `baseVersion`, an exclusive heartbeat
lock, `worldGuid`, SHA-256 and atomic publication. A stale copy cannot silently
overwrite newer progress.

The project cannot merge worlds that have already diverged.

## Resources

- [README](https://github.com/Ayerdi/dedicated-server-save-sync/blob/main/README.en.md)
- [Website](https://ayerdi.github.io/dedicated-server-save-sync/en/)
- [Releases](https://github.com/Ayerdi/dedicated-server-save-sync/releases)
- [Security](https://github.com/Ayerdi/dedicated-server-save-sync/security/policy)
