# Imported text is data, never instructions (OPS-006)

Everything in an export is written by someone else: the person in the chat, a model, a web page that was pasted in. It can contain prompt injection, Markdown that acts on its own, HTML, odd URLs and hostile file names. This page lists every place that text goes, and the rule that applies there. The end-to-end check is `tests/integration/test_adversarial.py`: one hostile chat goes through import, the vault, the web pages, model requests and every file the engine writes.

| Where the text goes | The rule | Where it's enforced |
|---|---|---|
| The source folder or ZIP | Read only. Never written, renamed or extracted. ZIP member names with `..`, absolute paths, drive letters or backslashes are refused. Declared and actual sizes are both capped (`max_source_file_bytes`, `max_media_file_bytes`, `max_archive_entries`). | `ingestion/source.py` `safe_member_name`, `ingestion/chatgpt_export.py` |
| Vault notes (Obsidian) | `escape_text` shows chat text and never obeys it. No wikilinks or embeds, no Markdown links or images (a remote image would tell its server the note was opened; an `obsidian://` link would act in another vault), no code fences or inline code (where plugins such as Dataview run queries and JavaScript), no HTML, comments, tags, block references or line-start syntax. File names come from `safe_filename`. Front matter is written by a YAML library. | `rendering/markdown.py` |
| Web pages (`ke ui`) | Every template escapes by default. Every page sends `Content-Security-Policy: default-src 'none'`, so no script runs and nothing is fetched from elsewhere. It only listens on loopback. | `ui/app.py` |
| Links | Only `http` and `https` URLs become link records. They are never fetched while importing. | `links/extract.py` |
| Model requests | `instructions` never contain imported text; it goes only in `input_text`. Each message is framed by a `[m:ID] role:` line, and `quote_untrusted` escapes any line-start `[` inside the text, so a message can't pose as another message or as the user. The real-model adapter also puts the text in `<source_data>` tags it can't close, says in the system prompt that it is data, and offers the model no tools. | `providers/base.py`, `classification/schema.py`, `extraction/runner.py`, `retrieval/answers.py`, `providers/anthropic_api.py` |
| Model answers | Only JSON that fits the stage's schema is stored. Anything else gets one repair, then becomes a review item. An assistant's suggestion is never stored as the user's decision. | `providers/base.py` `result_from_response`, `extraction/` |
| Logs, reports, job checkpoints, command output | Counts and IDs only, never chat text. | `infrastructure/logs.py`; the leak check in `test_adversarial.py` |
| Sending data off the machine | Off unless a capability is switched on in `[egress]`. Paid calls also need a cost cap. | `settings.py` `EgressPolicy`, `providers/ledger.py` |

## Not covered here

- **OCR, image understanding and face recognition** never run without explicit consent. Nothing in the engine does them today.
- **Plugins in your own vault.** Escaping stops chat text from becoming plugin syntax. A plugin that runs on every note's plain text would still see the words.
