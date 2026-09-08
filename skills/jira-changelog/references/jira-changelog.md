# Jira changelog — what ad-jira does and why

## Where the token comes from
`ad-jira` never runs the pncli binary. It reads pncli's own config (`~/.pncli/config.json`) at call time using the
key names chosen in `ad-setup --only pncli`, and sends the token itself. Env `JIRA_URL` / `JIRA_EMAIL` /
`JIRA_TOKEN` override. Nothing is ever printed or stored; `ad-jira whoami` shows only `token_source`.

## Flavor (detected once, cached in config; `ad-jira whoami --redetect` to redo)
| | Cloud (`*.atlassian.net`) | Data Center / Server |
|---|---|---|
| REST base | `/rest/api/3` | `/rest/api/2` |
| Auth | `Basic base64(email:api_token)` — the account **email**, not the username | `Bearer <PAT>` (Basic as fallback) |
| Search | `GET /search/jql` with `nextPageToken` (`/search` was retired) — returns only ids unless `fields` is passed | `GET /search` with `startAt`/`total` |
| Changelog | `GET /issue/{key}/changelog` paged (`values[]`, `isLast`) and `POST /changelog/bulkfetch` (≤1000 issues, ≤10 field ids, `nextPageToken`) | `GET /issue/{key}/changelog` if it exists, else `GET /issue/{key}?expand=changelog` (newest first; capped, and reported `partial`) |
| Bulkfetch fallback | 404/405 → one `GET /issue/{key}/changelog` **per issue**, announced with the request count it implies; 400 naming bad keys → those keys are dropped and the chunk retried once | no bulkfetch at all: the per-issue path is the only path, so the cache saves the most here |
| Agile | `/rest/agile/1.0/sprint/{id}`, `/board/{id}/sprint`, `/sprint/{id}/issue` | same |

## Response facts encoded in the client (verified from Atlassian's OpenAPI)
- Changelog item: `field, fieldId, fieldtype, from, fromString, to, toString`. `toString` is missing from the published
  schema but present in every response — always read it. `author` may be null (automation, deleted users).
- `created` is ISO-8601 with milliseconds and a **colon-less offset** (`+0000`); Agile dates use `+10:00`; bulkfetch
  examples show **epoch seconds**. `parse_ts` accepts all of them and normalises to UTC.
- Pagination: use the `maxResults` the server **echoes** (it may cap the request), stop on `isLast`/`total`.
- bulkfetch envelope is `issueChangeLogs[].changeHistories[]` keyed by `issueId`, no `total`; duplicates across pages
  are documented (JRACLOUD-94906) → rows are de-duplicated on `(issueId, changelog id, field id, position)`, which also
  lets an 11th field id be a second call over the same issues instead of a silent `[:10]` truncation.
- 429 → `Retry-After` (seconds or HTTP date) honoured up to 120 s; missing → `min(120, 2^n)` seconds plus up to 1 s of
  jitter, 6 attempts per request. By the time a 429 is raised the client has already waited, so its hint no longer says
  "wait a minute and rerun": it says to narrow the JQL or raise `--max-requests` / `--max-seconds`. Cloud's
  `X-RateLimit-*` headers are read on every response, so the last requests before a limit are a pause, not a refusal.

## Limits and budgets
A pull spends the **human's** token: pncli's. So every run has a ceiling it stops at rather than a rate limit it
discovers.

| Flag | Default | Also from | What it does |
|---|---|---|---|
| `--max-requests` | 2000 | `jira.budget.max_requests` | stop after this many HTTP requests |
| `--max-seconds` | 900 | `jira.budget.max_seconds` | stop after this much wall clock |
| `--bulk-issues` | 200 (max 1000) | — | issues per bulkfetch call |
| `--bulk-page` | 500 (max 10000) | — | changes per bulkfetch page; halves itself down to 50 when a page proves too heavy |
| `--stats` | off | — | five numbers in the meta and one line on stderr |
| `--quiet` | off | — | no progress lines on stderr (the result is unchanged) |

Flag beats config beats default. Retries are capped at 200 per run and have no flag. Per request: 6 attempts,
`min(120, 2^n)` seconds of backoff plus up to 1 s of jitter (the jitter is why several agents sharing one token do
not retry in lockstep). Retried: 429, 502, 503, 504, socket timeout, connection reset, remote disconnect —
and 500 **once**, because Jira answers 500 for transient changelog hiccups and a second 500 on the same page is
real. Never retried: 400, 401, 403, 404, 405, 409, 413. Idempotency is a property of the call, not the method:
every GET and the `bulkfetch` POST may be replayed, `ad-jira transition` never is.

Rate-limit headers (`X-RateLimit-Limit`, `-Remaining`, `-Reset`, `-NearLimit`) are read on every response. Under 10 %
remaining, or `NearLimit: true`, the client sleeps until the reset (capped at 300 s) **before** the next request and
says so: `rate limit: 43 of 500 left, waiting 12s`. Data Center below 8.6 sends no such headers; those runs stay
reactive and learn only from `Retry-After`.

A budget stop is not an error from Jira — it is this client refusing to keep going, and it renders as a partial
result (below), exit code 1. `--stats` on a run that fell back to per-issue fetching:

```
changelog: 0 issues from cache, 12 to fetch
bulkfetch fell back to one request per issue (HTTP 404 on /rest/api/3/changelog/bulkfetch): about 12 more requests
changelog: 15 requests, 0 retries, 0 rate-limit waits, 0.0s waiting, 0.1s elapsed
```

That announcement is the bulkfetch fallback's price list. One bulkfetch call becoming one request per issue is the
cheapest way there is to get a shared token throttled, so it is said out loud, recorded as `bulk_fallback` in the
meta, and **refused before it starts** when the remaining budget cannot pay for it — the error then names
`--max-requests <n>`, a narrower JQL, `--no-bulk` or `--bulk-issues`. A 400 that names bad keys is not a fallback:
those keys go to `skipped_keys` and the chunk is retried once without them. `_invalid_keys` only ever drops keys
*this run asked for*, so that is a whole history missing from the answer — it ends the run as a partial result
(`reason: keys rejected by bulkfetch`, exit 1), never as a footnote under `ok: true`.

## Partial results
Any result that is not the whole history the operator asked for says so. Real output, budget exhausted mid-pull
(`ad-jira changelog --jql "project = RDSD" --bulk-issues 5 --max-requests 8` against the test fake):

```
meta:
  ok: false
  rule: 6
  source: ad-jira changelog RDSD-1 RDSD-2 RDSD-3 …
  rows: 600
  cols: 11
  truncated: false
  elapsed_s: 0.0
  path: /tmp/tmp_c_p7_pb/out/20260908T065823-9ff7_changelog.tsv
  shown: 10
  action: script over path; do not read file
  stats: omitted (streamed)
  partial: true
  reason: budget
  rows_written: 600
  issues_complete: 30
  issues_incomplete[10]: RDSD-37,RDSD-38,RDSD-39,RDSD-4,RDSD-40,RDSD-5,RDSD-6,RDSD-7,RDSD-8,RDSD-9
  issues_incomplete_count: 10
  resume: "ad-jira changelog --jql ""project = RDSD"" --bulk-issues 5"
  hint: "rerun with a larger --max-requests, or narrow the JQL to fewer issues"
  cached: 0
  fetched: 40
  resumed: false
```

(the rule-6 sample rows follow it, unchanged; `issues_incomplete` is capped at 20 keys and `issues_incomplete_count`
carries the rest.)

`hint` is what to DO about it; `reason` is one of:

| `reason` | What happened | Does a rerun fix it |
|---|---|---|
| `budget` | `--max-requests` / `--max-seconds` ran out | yes — the cache holds the finished issues, so the rerun is shorter |
| `interrupted` | Ctrl-C; the pages that arrived are on disk | yes |
| `http 502 on RDSD-1234 page 7` | an HTTP failure the retries could not recover | usually — if it repeats, it is the server, not the pull |
| `network on RDSD-1234 page 7` | a timeout or reset that survived six retries | usually |
| `keys rejected by bulkfetch` | a 400 named keys this JQL asked for; `skipped_keys` lists them and none of their rows are in the file | only if the keys are real — check they still exist, or rerun with `--no-bulk` |
| `cache read failed` | the changelog cache answered and then stopped mid-run | yes, after `ad-jira cache --clear` |
| `expand=changelog truncated: 100 of 150` | Data Center answered knowingly short for the keys in `truncated_keys` | **not for those keys** — the endpoint cannot page, so use the Teradata history for their older events. Every OTHER issue in the JQL is complete, on disk and cached, so the rerun still costs nothing for them |

**`resume` is the literal command to run, and rerunning IS the resume**: an issue is written to the cache only after
its last row, so the second run's freshness check asks Jira for the incomplete ones and nothing else. Four flags are
deliberately dropped from the printed command: `--no-cache` and `--refresh` would start the whole pull again, and on
a `budget` stop `--max-requests` / `--max-seconds` would replay the ceiling that stopped it — a resume that cannot
resume. The rerun gets the default budget (or `jira.budget.*`), which is what the `hint` is telling you.

Exit codes: `changelog` returns 1 with the file kept and named on stderr. `sprint-replay` returns 2 and computes
nothing: `error: "changelog partial (budget): replay refuses a short history"` with the same `resume` in the hint. A
`committed_points` over 30 of 40 histories looks exactly like a real number, which is why the refusal is not a
warning. `--allow-partial` makes it compute anyway and marks `summary.partial: true` plus `issues_incomplete` — the
findings must repeat that. A failure before the first row is a plain error, not a partial: there is nothing kept and
nothing to resume.

## Cache
`.agent/out/.jira-changelog-cache/changelog.sqlite3` — one SQLite file per project, holding the eleven changelog
columns and an `issue(key, id, updated, fetched_at, complete, row_count)` table. Nothing else: no summaries, no
descriptions, no credential. The rows are the same ones already written to `.agent/out/*.tsv`.

The key is each issue's `updated` stamp, and it is safe because it is not a heuristic: **a changelog cannot change
without `updated` moving, since every history entry is an edit.** The `search(jql, ["key","updated"])` that finds the
issues also decides which of them changed, so the freshness check costs nothing extra. Twelve issues on the fake:
first run 3 requests (search, fields, bulkfetch), second run 2 (search, fields) and `cached: 12, fetched: 0`.

- On for every `--jql` run. Explicitly named `KEY` arguments have no search and therefore no stamp, so they are
  always fetched and never stored.
- Off for a `--fields` run, and it says so: a field-filtered pull is part of a history, and storing it under the
  issue's stamp would serve a fragment as the whole history later.
- `--since` / `--until` never narrow the cache. They are client-side filters applied on the way to the file; the
  cache is given the unfiltered history. That is the difference between a filter and a lie.
- `--refresh` refetches everything, ignoring `updated` equality — for the day Jira's stamp lies (a re-index).
  `--no-cache` neither reads nor writes.
- It is also the checkpoint: an issue is `complete=1` only after its last row, so a crash mid-issue refetches that
  issue and nothing else.
- `ad-jira cache --stats` reports path, issues, rows, bytes and the oldest `fetched_at`; `ad-jira cache --clear`
  deletes the file and the next pull recreates it.
- A cache that cannot be opened disables itself with a message and a hint, and the run fetches everything exactly as
  it did before the cache existed. It never fails a pull.

## Ordering
Rows are emitted **grouped by key, ascending by `(created_utc, changelog_id)`**, whatever the source — bulkfetch,
per-issue Cloud, per-issue Data Center, `?expand=changelog`, or the cache. This is guaranteed at fetch time, not by
sorting at the end, because rows go to disk as pages arrive and cannot be re-read. Bulkfetch states no order within
an issue across pages, so one chunk's pages are collected per issue, sorted, then yielded — which is also the memory
bound: one chunk (`--bulk-issues`), never the run. A numeric `changelog_id` is compared as a number, so 9 sorts
before 10.

With `--jql` the key list is sorted before fetching, so the file comes out globally sorted with no second pass.
`sprint-replay`'s per-issue output rows keep the order the search returned, as they always have.

## Field ids are per instance
`GET /field` once; `ad-jira fields --pin` stores: **Sprint** = the field whose `schema.custom` ends with `:gh-sprint`;
**Story Points** = ids of `Story Points` (company-managed projects) and `Story point estimate` (team-managed) — an
issue populates one or the other, so the replay coalesces them in that order. Hard-coding `customfield_10020` is a bug.

## Sprint field semantics
The Sprint change item carries the **whole membership before and after**, not a delta: `from`/`to` are
comma-separated sprint **ids** (stable), `fromString`/`toString` the names (mutable, non-unique). Data Center may
serialize sprints as `...Sprint@1a[id=12,rapidViewId=3,...]` strings — ids are extracted with `id=(\d+)`.
Closed sprints stay in the field, so "carried over" = the issue also lists another sprint at the start instant.

## Replay rules (uat/sprint.py)
- `value_at(current, changes, t)`: start from the **current** value, undo every change with `created > t`, newest
  first. Correct when a field was set at creation with no changelog entry. Half-open boundary: an event at exactly the
  sprint start counts as *before* the start (a bulk "add to sprint" at the same millisecond as the start is committed).
- `T_start = startDate`; `T_close = completeDate` (when it exists) else `endDate`; active sprint → now, `provisional`.
- **committed** = in the sprint at `T_start`; points = estimate at `T_start`.
- **completed** = in the sprint at `T_close`, status category `done` at `T_close`, the last transition into done
  happened inside `[T_start, T_close]` while the issue was in this sprint. Done means `statusCategory.key == "done"`,
  never a name match on "Done".
- Flags: `added_after_start`, `punted` (in at start, out at close — still counts as committed), `re_estimated`,
  `estimated_mid_sprint` (null at start → counts 0 committed), `carried_over`, `reopened` (done → not done inside the
  window; evaluated as state at `T_close`, not by counting transitions), `completed_in_another_sprint`.
- Sub-tasks are excluded from sums unless `--include-subtasks`. `--points-at commit|close` picks the estimate credited
  for completed work (default `close`; the summary states it).

## Known limits
- JQL `sprint = <id>` matches current/closed membership; issues **removed** from the sprint are found only through the
  `--jql` widening (recommend `project = X AND updated >= '<start - 1d>'`). Without it `punted` is under-counted.
- Deleted issues vanish from both JQL and changelog.
- `--compare-sprintreport` calls `/rest/greenhopper/1.0/rapid/charts/sprintreport` — undocumented, unsupported,
  rate-limited on Cloud. Informational only; never the truth.
- `?expand=changelog` on Data Center returns the most recent histories only; that answer comes back `partial: true`
  with `reason: expand=changelog truncated: <have> of <total>` rather than being silently miscounted. The affected
  keys are in `truncated_keys` and no rerun fixes those; they contribute **no rows at all** rather than a short
  history, and the rest of the JQL is fetched and cached normally (§Partial results).
- Neither changelog endpoint filters by date server-side. `--since` / `--until` are client-side filters over a full
  pull; the only real narrowing is the JQL that chooses the issues.
- A run stops at its own budget before Jira's limit, and reports what it fetched (§Limits and budgets). A partial
  pull is a distinct outcome from a failure: rerun it, never fix it from `hint`.
- The cache trusts `updated`. A Jira re-index that rewrites histories without moving the stamp is the one case it
  gets wrong, and `--refresh` is the answer to exactly that.
- `changelog_id` is unique per history, not per row: one history that changed three fields is three rows sharing an
  id. Group on `(key, changelog_id)` before counting "changes".
