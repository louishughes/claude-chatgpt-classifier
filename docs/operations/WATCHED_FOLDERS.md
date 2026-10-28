# Watched folders (INT-003)

`ke watch FOLDER` imports each ChatGPT export that lands in a folder, once it has finished arriving, and again only if its contents change.

```
ke watch ~/Downloads/chatgpt --partial --vault ~/Notes/ke      # keeps running; Ctrl-C stops
ke watch ~/Downloads/chatgpt --once --settle 5                 # look twice, act, stop
```

| Option | Meaning |
|---|---|
| `--account LABEL` | account label for these exports (default: the matching raw root's, or `default`) |
| `--partial` | the exports hold only some chats, so nothing is marked "not seen" |
| `--vault DIR` | after an import that changed something, sync this vault (DOC-006) |
| `--interval S` | seconds between looks (default 5) |
| `--settle S` | seconds an export must stay unchanged before it is imported (default 3) |
| `--once` | look, wait `--settle`, look again, act, stop |

## What counts as an export

Top-level folders and `.zip` files in the watched folder. Hidden entries, links, loose files and partial downloads (`.crdownload`, `.part`) are ignored. The folder can't be the workspace, inside it, or contain it.

## When it imports

1. **Settled.** The export's metadata (paths, sizes, modified times) is the same on two looks at least `--settle` seconds apart. A download or copy still in progress waits.
2. **Not seen before.** The watch state (`<workspace>/watch/<key>.json`, one file per watched folder) holds each export's metadata and content fingerprints:
   - same metadata as last time: skipped without reading the files;
   - new metadata but contents already imported (touched, re-downloaded, or a second copy under another name): recorded, not imported;
   - new contents: imported through the normal importer.
3. **Failures are not loops.** A refused or broken export is recorded with its error code (for example `unsupported_format`) and isn't tried again until it changes.

The importer's own rules still apply: the source is only read, identical material adds nothing, and an export missing from the folder is never treated as a deletion.

## Affected stages

When an import changed at least one message revision and `--vault` is set, the vault is synced once for that look. Only notes whose content changed are rewritten; notes about other chats keep their bytes and modified times. Classification and other model steps are never started by the watcher.

## Output

Counts, error codes and import IDs only: `imported`, `import_ids`, `unchanged`, `same_contents`, `waiting`, `failed`, `changed_revisions`, and each stage's counts. Export names never appear, because they can be private. The exit code is non-zero if any export failed.

**Tested by** `tests/integration/test_watch_folder.py`, with a fake clock, so the tests never sleep.
