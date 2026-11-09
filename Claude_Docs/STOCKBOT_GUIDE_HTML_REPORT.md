# Interactive codebase guide: report

Documentation task. No change to the engine, config, schema, data or any shared package. No strategy file added, no dependency added. Nothing started beyond the brief (the data-guide HTML was not started).

## What was built

| item | path | size |
|---|---|---|
| The page (one file, everything inline) | `docs/guides/codebase_guide.html` (copy: `Claude_Docs/codebase_guide.html`) | 107,864 bytes |
| Content (packages, modules, flows, glossary; 128 `source` fields) | `docs/guides/codebase_guide_data.json` | 61,383 bytes |
| Template (CSS and vanilla JavaScript) | `docs/guides/codebase_guide_template.html` | 48,803 bytes |
| Builder, logic | `stockbot/data_checks/guide_html.py` (standard library only) | 3,388 bytes |
| Builder, thin wrapper | `scripts/build_guide_html.py` | 412 bytes |
| Tests | `tests/unit/test_guide_html.py` (14 tests) | 7,867 bytes |
| Screenshots | `docs/guides/screenshots/` (35 PNG files, 3.0 MB) | |

Use: open `docs/guides/codebase_guide.html` from the folder (double-click). To change content: edit the JSON (or the template), then `py scripts/build_guide_html.py` (add `--stamp` to record today's date and the git commit in the footer). The page is a pure function of the JSON and the template; a test fails if they disagree.

`docs/guides/CODEBASE_GUIDE.md` now names the new module, the new script and the new files (the existing guide test requires that), and points to the picture version in one sentence. Its copy in `Claude_Docs/` was refreshed.

## The ten views

| # | tab | what is on screen |
|---|---|---|
| 1 | Big picture | The rule banner "Strategies only propose. Everything else is shared." and six blocks (Data, Strategy, Engine and shared rules, Validation, Backtest/Live runners, Outputs/Tickets) joined by labelled arrows. Click a block: the panel of its main package, with the other packages of the block named. |
| 2 | Package map | All ten packages plus `scripts/`, `tests/`, `docs/`, `data/` as nodes with the allowed-import arrows. Hover: one line. Click: panel with meaning (2 sentences), key modules (name and one line), reads and writes, who calls it, may import / may not import. Filter: "Show everything" or "Show what I touch daily" (non-daily nodes fade; the choice is remembered in the browser if it allows). |
| 3 | Who can import whom | The same layout. Click a package: allowed imports turn green, the temporary `live` to `validation` edge amber, forbidden imports red dashed, with one reason line per forbidden package underneath. A fixed card shows "strategy A (cross) strategy B" and the rule that no strategy imports another, plus the other enforced rules. |
| 4 | A day in the engine | Step-through of `decide()` with Back, Next, Play, Reset, clickable step chips and arrow keys. Each step: what goes in, what comes out, a plain sentence, an example labelled "EXAMPLE, NOT REAL DATA", and "More detail". One made-up stock, EXAMPLECO, is followed across all ten steps in a strip at the bottom. |
| 5 | Backtest vs Live | Two lanes side by side with a single `decide()` box across both. Click any box (backtest: 5, live: 7) for detail and its source. |
| 6 | Life of a trade | Eight states as linked cards (Proposed, Sized and capped, Ticket, Filled, same-bar step, stop moves up, Exit, Closed trade) plus the two side states (Blocked, Not filled), with Back/Next/Play/Reset. Tags show where caps, slippage and costs apply. |
| 7 | Add a strategy | Left: six things the owner adds, each tickable, each opening a comment-only skeleton. Right: six things never to touch, each with a one-line reason. |
| 8 | Validation | Nine boxes (pre-register, hash lock, trial ledger, backtest, matched-random baseline, paired weekly advantage, Max-T bootstrap, gates, status), each with the question it answers. |
| 9 | Where do I look? | Search box and 14 symptoms (section K of the markdown guide, shortened) with the files to open. |
| 10 | Glossary | 35 terms with search. Terms used in other views are underlined once per block and show the definition on hover, keyboard focus or tap. |

Always visible: the colour key (one colour per package, the same everywhere: map, import graph, flow steps, chips), a "You are here" breadcrumb and a Back button, light/dark/auto theme switch. Footer: build date, git commit, and the note that example numbers are made up. Each panel ends with "Read more: `docs/guides/CODEBASE_GUIDE.md`, section X" as plain text (not a link) and a "Source:" line.

Items that are not built are labelled **planned**: the gates step in the validation flow (no code applies `validation_gates` yet), and the location of an exit-policy file (not fixed by the repository yet). Overlays are described as "none exist yet".

## Differences against `engine/decide.py` (check 5)

I read `decide.py` line by line. **The order of the ten steps equals the order of the code**: input checks, overlays, fills of yesterday's tickets, corporate actions, stepping through today's bar, eligibility, strategies propose, sizing, arbitration, decisions and new State. A test ties the step ids to the order of the section comments in `decide.py`. Differences in granularity, all stated in the page's "More detail":

1. The code does steps 4 and 5 together, one position at a time (corporate actions for that position, then its bar), and includes positions filled today.
2. The code does steps 6, 7 and 8 per strategy (eligibility is cached per distinct set of universe overrides, then propose, then size each proposal). Arbitration (step 9) runs once after all strategies.
3. Step 1 also checks duplicate strategy ids and unknown exit policies before anything else; step 3 sizes from the fill price on equity marked at the previous close, step 8 on equity after today's moves.
4. Tickets are built after arbitration, in admission order; they are part of step 10's packaging.

No step in the page is missing from the code, and no step of the code is missing from the page.

## Quality checks

**Browser.** Real engine: headless Google Chrome 156.0.8078.80 (Windows), driven through its debugging protocol by a throw-away script kept outside the repository (it needed Python's `websockets`, which was already installed; nothing was added to the project). Edge is installed but I did not run it; Firefox is not installed here. **So Chrome is the only engine tested.** The "phone" screenshots are a 390 px wide emulated viewport in Chrome, not a real phone.

- **Screenshots:** each of the ten views at 1280 px and at 390 px, plus panel-open states (map/engine, imports/strategies, big/engine block, add/skeleton, lanes/shared box, engine step 9) at both widths, and three dark-mode screenshots (big picture, imports, engine step 5). List: `big`, `map`, `imports`, `engine`, `lanes`, `trade`, `add`, `validation`, `where`, `glossary` each as `<view>_desktop.png` and `<view>_phone.png`; `map_engine_*`, `imports_strategies_*`, `engine_9_*`, `big_b-engine_*`, `add_a1_*`, `lanes_shared_*`; `big_x_dark.png`, `imports_engine_dark.png`, `engine_5_dark.png`. I looked at a sample of them by eye (big picture, map with panel, imports with strategies selected, engine step 3 and 5, lanes, trade, the add skeleton on the phone, map on the phone, imports on the phone) and fixed three things I saw: step colours in the trade and validation views did not follow "one colour per package"; the colour key took half the phone screen (now one scrolling line); a missing space in a label. I did not inspect every one of the 35 images.
- **Console errors:** across all 35 page states and 17 scripted interactions: **0 uncaught exceptions, 0 console errors or warnings, 0 browser log errors.**
- **Horizontal overflow:** none at 390 px or 1280 px (document width equals window width in every state). Three views switch to stacked cards on the phone (big picture, map, import graph) because their drawings would be unreadable at that size.
- **Interactions checked in the browser (17 of 17 passed):** a block click opens the engine panel; Esc closes it; the map has 14 nodes; the daily filter fades the 10 non-daily nodes; selecting `strategies` draws 1 green and 8 red edges; selecting `live` draws 6 green, 1 amber (temporary) and 2 red; Next ten times reaches step 10 and disables Next; Back, Reset and Play work; a glossary term shows its tooltip; the glossary lists 35 terms and its search narrows; the symptom search narrows; the add view has 6 plus 6 items; arrow keys move between tabs.
- **Offline / no external requests:** the page text contains no `http://` or `https://` at all (a test enforces it, together with no external script, style, image, font, frame, `fetch`, XMLHttpRequest, WebSocket, `@import` and no `url()` except references to markers inside the page). The browser's network log for the whole run contains **one request: the page itself** (`file:///...codebase_guide.html`). The page uses `localStorage` for the theme, the daily filter and the tick boxes, always inside try/catch, and works if it is blocked.

**Tests.**

| check | before | after | note |
|---|---|---|---|
| G1 (`tests/unit` + `tests/integration`) | 505 passed, 2 skipped | **520 passed, 2 skipped** (3 min 07 s) | +15 = the 14 new tests and the new wrapper's `--help` test |
| G3 | 2 passed | 2 passed | |
| G2 (`STOCKBOT_DATA_TESTS=1 STOCKBOT_FINAL_CHECK=1 py -m pytest tests`) | 628 passed | **643 passed**, 0 skipped, 0 failed (4 min 25 s) | +15 as in G1; the env-gated guide tests ran against the real lake (read-only) | |
| G4 `finsight.db` | sha256 `dcade46506518a25d35f220e7e3b5b35d53c349362308ee42888cd9615ceb752`, modified 2026-11-08 12:38:02 +0530, 3,432,767,488 bytes | **identical** (re-hashed after the commit) | none of this work opens the database |

A fresh clone of the committed tree (autocrlf on Windows) also passed the three test files touching the guides: 52 passed, 1 skipped (the env-gated one).

**New tests shown failing before their fix.** Before any of the new code existed, the test file failed at collection (`cannot import name 'guide_html'`). After the guide was built, twelve defects were seeded one at a time, each caught by the intended test, with a clean control run passing and the files restored after each: a module path that does not exist; a `path::function` whose function does not exist; a package removed from the JSON; an import table that differs from `tests/fixtures/boundaries.py`; a glossary entry without a source; a required term removed; the engine steps out of the order of `decide.py`; a panel text over 40 words; an external `<script src>` in the template; a `fetch()` in the template; the HTML edited by hand; the JSON changed without rebuilding the HTML. Run once, one of my own test patterns was wrong (it forbade `url(#marker)`, which is an in-page reference); I narrowed it before anything was committed and noted why in the test.

## Limitations and deviations (plainly)

- **Browsers:** only Chrome was run. Firefox and Edge are untested; the page uses features that current versions of both support (`color-mix`, look-behind regular expressions, `matchMedia`), but I did not verify that.
- **Accessibility:** tabs, buttons, drawing nodes and terms are keyboard-operable and have visible focus; Esc closes the panel. I did not run a screen reader and did not measure colour contrast numerically; the colours were chosen to be readable and the screenshots look readable in light and dark.
- **Phone layout:** three drawings become lists of cards at phone width instead of scaling down; the "life of a trade" state diagram is drawn as cards with arrows rather than as an SVG, so it stays readable at 390 px. The ten tabs scroll sideways inside their own bar on a phone.
- **Running example:** the brief asked for one stock. EXAMPLECO is followed through all ten steps, but because a stock that is held cannot be bought again, its second half ends with the made-up strategy proposing it again and arbitration blocking it (`ALREADY_HELD`). That keeps one stock throughout and shows that a strategy cannot see the portfolio. The lifecycle view uses different made-up numbers (it is a separate example).
- **"What I touch daily":** the markers are my reading of the guide: `scripts/` (run_eod, daily_health_check, snapshot_asm_gsm), `stockbot.live`, `stockbot.data` (the snapshot ingestion and the lake) and `stockbot.config` (settings). No scheduled task exists on this machine, so "daily" means "meant to be run each trading day", which the panel says.
- **Panel length:** panels were kept short; each step view is about 50 words including the input, output and example (the brief said about 40). A test caps the plain-English sentences at 40 words.
- **Strategy content:** none. The skeletons are comments only; the only numbers are the labelled made-up examples. No parameter, rule, signal count or result of the momentum work appears.
- **Footer commit:** the footer says "built from commit 22b5372", the commit before the one that adds the page (a page cannot contain its own commit id). It is recorded in the JSON by `--stamp`, which keeps the HTML a pure function of its inputs.
- **Sources:** every item has a `source`; the test checks every path exists and that a named function or class occurs in its file. It does not check that the *sentence* is true; I wrote each from the code and `docs/guides/CODEBASE_GUIDE.md`.
- **Screenshots in git:** 3.0 MB of PNG files are committed under `docs/guides/screenshots/`, as the brief asked.

## Commits

| SHA | what |
|---|---|
| `9ddbf4a` | the guide, JSON, template, builder, wrapper, tests, screenshots, `CODEBASE_GUIDE.md` update, copies in `Claude_Docs/` |
| the commit carrying this report | `Claude_Docs/STOCKBOT_GUIDE_HTML_REPORT.md` (SHA given in the chat message) |

STOP. The data-guide HTML was not started.
