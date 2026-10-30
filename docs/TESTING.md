# Testing the project

There are three parts, and each one starts with a double-click in the project folder (`V:\Programming\ChatGPT_Classifier`). You don't type any commands.

| Part | Double-click | What it does |
|---|---|---|
| 1. Automatic checks | `TEST_EVERYTHING.bat` | Runs everything CI runs, then opens a green/red report in your browser |
| 2. Try it by hand on made-up chats | `OPEN_DEMO_DASHBOARD.bat` | Opens the dashboard on five synthetic chats |
| 3. Try it by hand on your chats | `OPEN_DASHBOARD.bat` | Opens the dashboard on your real workspace |

No step uses a paid AI. See [Which steps could cost money?](#which-steps-could-cost-money) at the end.

## 1. Automatic checks: `TEST_EVERYTHING.bat`

The first time, it sets up Python for the project (a `.venv` folder), which takes a few minutes. After that it runs the checks: about 10 to 20 minutes in all. A black window shows progress. When it's done, `workspace\test-report\report.html` opens in your browser.

**What you should see:** a green banner saying **Everything passed**, and one line per area, each marked PASS:

| Area | What it proves |
|---|---|
| Code tidiness, Code layout, Type checks | The code is clean and consistent |
| Privacy guard | Nothing private is in Git |
| All automated tests | Importing, branches, images, repeat imports, links, notes, search and the web pages all behave |
| Release scorecard | Each quality check against its threshold, with a fake model |
| Same answer every time | A shuffled or repeated run gives identical results |
| Whole journey | A synthetic export goes all the way to Obsidian notes with working links |

**If a line is red:** it says what to do, and the last lines of its log are just under it. Usually the answer is to give that log to Claude (each line links to its full log).

If Python isn't installed, the window says so. Install Python 3.12 or newer from python.org, tick **Add python.exe to PATH**, and double-click the file again.

For a quicker run that skips the three nightly areas, open PowerShell in the folder and run `.\TEST_EVERYTHING.bat --quick`.

## 2. Click-through on made-up chats: `OPEN_DEMO_DASHBOARD.bat`

This imports five synthetic chats into a separate demo workspace (`workspace\demo`), so nothing mixes with your real chats. The dashboard then opens at `http://127.0.0.1:8770`. Tick each line as you go. Close the black window when you're done.

1. **Overview.** You should see the tiles **5 chats stored**, **5 in the latest export**, **0 not seen lately** and **1 imports** (or more if you've opened the demo before).
2. **Chats** (left menu). Five chats whose titles start with "Synthetic", newest first.
3. Open **Synthetic branched chat**. The conversation shows, and below it is a section called **Other branches**: the alternative reply is kept separately, not mixed in.
4. Go back and open **Synthetic image chat**. A message shows its picture, with an **Every message using this file** link under it. Click the link: the image page lists each message that uses the picture.
5. **Search** (left menu). Search for `shed`. You should get **3 messages**, each linking straight to its message in its chat.
6. **Links** (left menu). Three web addresses, each once, with how many times they were mentioned. Two are marked **video**.
7. **Videos**. One video with **2 mentions** in **2 chats**: two differently written links to the same video count as one. Its transcript status says **not requested** (nothing is downloaded).
8. **Accounts**. One GitHub account, marked **probable**. Nobody is looked up or contacted.
9. **Notes**. Five chats, all **unclassified** with **no digest yet**. That's right for the demo: classifying and digests need a Claude session (see the runbooks).
10. **Suggestions**, **Reviews**, **Timeline** and **Evaluation**. Each one opens and explains that it's empty for now. Evaluation says **No answer key loaded**.
11. **Import** (left menu). Paste `V:\Programming\ChatGPT_Classifier\tests\fixtures\e2e\export.zip` and click **Import**. When it's done, the report should say **0 new chats, 0 changed chats, 5 unchanged. Nothing new: this export was already in the archive.** Back on **Overview**, the Imports table has a new row with 0 new and 5 unchanged. This is the duplicate-proof check.

If every line matched, the dashboard works.

## 3. Click-through on your chats: `OPEN_DASHBOARD.bat`

This opens the dashboard at `http://127.0.0.1:8765` on your real workspace (and uses `ke.toml` if you have one). Your export is only read, never changed.

1. **Import** (left menu). Paste the full path to your ChatGPT export ZIP or its unzipped folder, for example `V:\Programming\ChatGPT_Classifier\raw\<your export>`. Click **Import**. A progress page refreshes by itself until the report appears.
2. The **import report** lists new, changed and unchanged chats, branches, images found and images missing, and any failures. There should be no failures.
3. **Import the same export again.** The new report should say **Nothing new: this export was already in the archive.**
4. **Chats**. Open a few, including one where you edited a message or regenerated an answer: it should show **Other branches**. Images should show, or say plainly why they're missing.
5. **Search** for a word you know you used. Each hit should open the right message.
6. **Links**, **Videos** and **Accounts** list what your chats mention, once each.

## Which steps could cost money?

None of the above. In detail:

- The checks remove every API key before they run, and the AI steps use a fake model. A check that needed a real model would fail instead of spending money.
- The dashboard and the import never call an AI.
- Classifying and digests (`ke classify run`, `ke digest run`) write request files that a Claude Code session answers on your subscription ([LABELLING_SESSION.md](runbooks/LABELLING_SESSION.md)). They don't call a paid API.
- The only paid path is `ke eval semantic --provider anthropic`. It refuses to run unless all four of these are true: `--synthetic`, `--max-cost-usd` above zero, `[egress] text_llm = true` in `ke.toml`, and `[limits] max_cost_usd_per_run` above zero. It also needs the optional `api` extra and an `ANTHROPIC_API_KEY`. Don't set that key until you decide to allow paid calls.

## For developers

The double-clicks run these, which also work from a terminal:

```powershell
python -m knowledge_engine.devtools.test_report           # all checks + HTML report
python -m knowledge_engine.devtools.test_report --quick   # without the nightly checks
python -m knowledge_engine.devtools.ci                    # what CI runs on every PR
python -m knowledge_engine.devtools.ci --nightly          # what CI runs nightly
```
