# Installing, upgrading and rolling back (OPS-007)

## Install on a new computer

You need Python 3.12 or newer. From a release wheel (or the repository folder):

```
python -m venv .venv
.venv\Scripts\activate            # Windows; on macOS/Linux: source .venv/bin/activate
pip install knowledge_engine-0.1.0-py3-none-any.whl     # or: pip install -e .
ke --version
ke status
```

`ke status` says where the workspace is and whether the database needs upgrading. Nothing is created until the first import.

## Upgrade to a new version

1. Read the new entry in `CHANGELOG.md`. It says whether the database schema changes.
2. Install the new version in the same environment (`pip install <new wheel>`, or `git pull` and `pip install -e .`).
3. Run `ke db upgrade`.
   - If the schema is behind, it first makes a full backup (OPS-003) into `<workspace>-backups/` next to the workspace, then migrates. The message names the backup folder. Keep it until you are happy with the new version.
   - If nothing needs migrating, it says "Database is up to date" and makes no backup.
   - `--backup-to DIR` puts the backup somewhere else. `--no-backup` skips it; only use that if you have just made a backup yourself.
4. Until you run it, `ke import` (and an import from `ke ui`) stops with `schema_mismatch`. It never migrates an existing database by itself.

## Roll back

Use this if a new version misbehaves, or a migration failed. A failed migration's message names the backup to restore.

1. Reinstall the previous version (`pip install <old wheel>`, or `git checkout <old tag>` and `pip install -e .`).
2. Restore the pre-upgrade backup into a new, empty folder:
   `ke backup restore <workspace>-backups/<backup folder> --to <new folder>`.
   The restore checks every file's hash and every table's row count, and refuses a non-empty folder.
3. Point the engine at it: set `workspace_root` in `ke.toml`, or `KE_WORKSPACE_ROOT`, to `<new folder>`. Run `ke status`: the revision should be the old one, with no upgrade needed.
4. Keep the upgraded workspace until you're sure, then delete it yourself. Nothing is deleted automatically.

The old version refuses a database a newer version has already upgraded: it says to install the newer version again or restore the backup. That is the protection against opening a database the code can't read.

Your source exports in `raw/` are never touched by any of this. A backup also holds its own copy of the archived export files.

## What is checked automatically

- Every change: `tests/integration/test_upgrade.py` (old database → `ke db upgrade` backs up, migrates, and the backup restores at the old revision; import refuses an old or newer database) and `tests/unit/test_release.py` (version, changelog and package agree).
- Nightly, on demand, and for `v*` tags (`.github/workflows/release.yml`, Linux and Windows): `python -m knowledge_engine.devtools.release_check`. It builds the wheel, installs it into a fresh virtual environment, imports a synthetic export, upgrades from the previous schema and restores the pre-upgrade backup.
