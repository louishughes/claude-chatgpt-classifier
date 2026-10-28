# Changelog

Every release of the Knowledge Engine, newest first. Each entry says what changed for a person using it and whether the database schema moved. A schema change means `ke db upgrade`, which backs up first. To go back, follow `docs/runbooks/UPGRADE_AND_ROLLBACK.md`.

The release check (`python -m knowledge_engine.devtools.release_check`, run nightly) refuses a release whose newest entry here doesn't match the version in `pyproject.toml`.

## [0.1.0] - 2026-10-28

The first numbered release: everything from the audit to M5 hardening. Built ticket by ticket; `docs/diary/BUILD_DIARY.md` has the full story.

- **Import:** ChatGPT exports (official ZIP or folder, split exports, older layouts) with every branch, image and attachment. Repeated exports are idempotent, and nothing is lost or overwritten.
- **Browse:** an Obsidian vault of transcripts and knowledge notes, a local web interface (`ke ui`), and search, `ke ask` and `ke find` that cite their sources.
- **Understand:** topic segments, classification against a versioned taxonomy, extraction of decisions and tasks with evidence, links, YouTube videos, social accounts, and related or continued chats.
- **Operations:** limits and cost caps, logs without private text, backups that prove they restore, purge with an audit trail, CI on Linux and Windows, and protection against hostile chat text (OPS-006).
- **Upgrade safety (OPS-007):** `ke db upgrade` backs up before migrating. An import no longer migrates an existing database, and a database from a newer version is refused.
- **Schema:** migrations `0001` to `0028_purge_log`. A workspace created by any earlier build is upgraded with `ke db upgrade`.
