## What changes?

<!-- Describe the change and the problem it solves. -->

## Risk and invariants

- [ ] Does not allow uploads without a valid `baseVersion`.
- [ ] Does not weaken locking, identity validation, authentication or atomic publication.
- [ ] Preserves Palworld compatibility unless the PR explicitly documents and justifies a contract change.
- [ ] Preserves managed-host user/token/host revalidation when that capability is involved.
- [ ] Does not include secrets, saves or real deployment configuration.
- [ ] Includes migration and rollback notes if persistence or deployment changes.

## Verification

- [ ] `ruff check save_sync tests wsgi.py scripts/check-docs.py`
- [ ] `python -m pytest -q`
- [ ] `pip-audit -r requirements.txt --progress-spinner=off`
- [ ] `bash scripts/local-e2e.sh`
- [ ] Pester when `client/` changes

## Documentation

<!-- List updated docs or explain why no documentation change is needed. -->
