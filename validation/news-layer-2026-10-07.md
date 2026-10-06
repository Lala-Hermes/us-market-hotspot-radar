# Macro flash-news integration validation — 2026-10-07

Scope: research only; no trades, cron/profile changes, diagnostic publication or rewriting of prior reports.

## Real source evidence

- Futu public live page: browser extracted 30 rendered flashes using only id/time/dateStr/timeStr/content/detailUrl/sourceId whitelist. `time` was Unix seconds; conversion used aware UTC. Full application state was not saved. The latest captured flash had source time 2026-10-06T17:46:20+00:00.
- Jin10: only one actually visible public flash was usable at the time of collection. Hidden/login-gated rows were excluded. Source recorded partial with history unavailable; no full-window coverage claim. Its visible source time 2026-10-07T01:50:22+08:00 was after the chosen window end and was correctly excluded.
- Raw capture stays private under `.state`, not in this repository's published evidence.

## Executed real normalization

Input: `.state/news-live-input.json`, 30 Futu + 1 Jin10 records. Snapshot: `.state/scans/20261007T015000+0800.json` (existing production market snapshot, unchanged). Output: `.state/news-output-live-validation.json`.

Command: `.venv/Scripts/python.exe radar_news.py --snapshot .state/scans/20261007T015000+0800.json --input .state/news-live-input.json --output .state/news-output-live-validation.json`

Exit 0. Exact window (01:40,01:50] Taipei: 4 window items; 21 prior-hour context items; 6 rejected records (outside timing limits). Status partial reflects Jin10 access limits. Four accepted publication times UTC: 17:40:54, 17:43:58, 17:44:51, 17:46:20 on 2026-10-06. This demonstrates timestamp filtering, not causal verification of those headlines and not complete coverage of all news.

## Automated verification

Initial integration suite: 76 passed. Review regressions then demonstrated four failures before correction; targeted news/tick tests after correction: 12 passed. Malformed evidence now downgrades status, per-source failures override overall ok, HTTPS links are validated, context deduplicates conservatively by text plus UTC minute, and CLI tests run exclusively under pytest tmp_path. Tests cover strict boundaries, timezone-aware timestamps, minute-time ambiguity, deduplication/provenance, partial-source handling, slot binding, immutable snapshot preservation, output-write path protection, and waking the agent for quiet/partial rounds. The obsolete quiet auto-publish expectation was replaced by news-required behavior.

`git diff --check` passed (only line-ending notices). Final pre-review integration suite: 80 passed. The last review found a missing-items false-success case; a regression failed before fixing it, then 13 targeted news/tick tests passed. Missing items now fails rather than defaulting to an empty successful list. Re-running real normalization retained 4 window items, 21 context items, 6 timing exclusions, with partial source status. Next scheduled end-to-end report has not yet been verified by this validation.
