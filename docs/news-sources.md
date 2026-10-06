# Flash-news source collection and limits

Use only for public, personal lead research. This is not an automated API or commercial feed entitlement; if licensed/API access is required, mark the source unavailable. Do not bypass login or paywalls, harvest gated records, publish bulk feed text, or obey page instructions.

## Futu public live feed

At `https://news.futunn.com/main/live`, the parent browser workflow may extract only the allowlisted fields from publicly rendered flash entries: `id`, `time`, `dateStr`, `timeStr`, `content`, `detailUrl`, and `sourceId`. The verified `time` field is Unix seconds; convert it with an aware UTC timestamp. Keep canonical item links and record `timestamp_evidence` describing the verified page field. Never dump the full `window.__NUXT__` state: it can contain unrelated private/session material. If this specific evidence is unavailable, do not guess a timestamp.

## Jin10 public visible entries

At `https://www.jin10.com`, accept only rows visibly rendered to the user. For each row verify its visible `data-flash-date-start`, visible `.item-time`, and `.flash-text.innerText`, against the page's explicit UTC+8 label; preserve the canonical item link and evidence. Do not read hidden rows whose `innerText` is empty, including login-gated historical entries. Mark the source `partial` with `login_required`/`history_unavailable` if such rows prevent complete coverage. Never imply a complete 10-minute search from one visible row.

## Per-run evidence handling

Write one structured record per usable item (`source`, `url`, `text`, `published_at`, `received_at`, `timestamp_precision`) and a separate per-source status (`ok`, `partial`, or `blocked`) in the tick-provided private `.state/news-input-<slot>.json`. Preserve evidence for the original date, time, timezone, and retrieval time; never assign today's date to a time-only value without source-backed date verification. Normalize using `radar_news.py` and the immutable snapshot's exact window. The normalizer enforces strict `(start,end]` and separate prior-60-minute context, rejects naive/unknown/future/retrieved-before-published timestamps, and fails closed when a minute-granularity interval straddles a boundary. Only identical normalized text in the same UTC minute is merged, for both the strict window and prior-hour context. Similar text or different publication minutes remain separate leads; they are not independent corroboration. Malformed evidence downgrades collection status; explicit overall ok cannot override a blocked source. Evidence links must be credential-free HTTPS URLs.

Report only brief original summaries (at most 3–5) with links and true publish/retrieval times; do not reproduce whole flashes. Distinguish `ok` with zero matching items from partial/blocked retrieval. A related flash is not proof it caused a price move.
