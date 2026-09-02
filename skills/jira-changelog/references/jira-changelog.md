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
| Changelog | `GET /issue/{key}/changelog` paged (`values[]`, `isLast`) and `POST /changelog/bulkfetch` (≤1000 issues, ≤10 field ids, `nextPageToken`) | `GET /issue/{key}/changelog` if it exists, else `GET /issue/{key}?expand=changelog` (newest first; refused when `total > len(histories)`) |
| Agile | `/rest/agile/1.0/sprint/{id}`, `/board/{id}/sprint`, `/sprint/{id}/issue` | same |

## Response facts encoded in the client (verified from Atlassian's OpenAPI)
- Changelog item: `field, fieldId, fieldtype, from, fromString, to, toString`. `toString` is missing from the published
  schema but present in every response — always read it. `author` may be null (automation, deleted users).
- `created` is ISO-8601 with milliseconds and a **colon-less offset** (`+0000`); Agile dates use `+10:00`; bulkfetch
  examples show **epoch seconds**. `parse_ts` accepts all of them and normalises to UTC.
- Pagination: use the `maxResults` the server **echoes** (it may cap the request), stop on `isLast`/`total`.
- bulkfetch envelope is `issueChangeLogs[].changeHistories[]` keyed by `issueId`, no `total`; duplicates across pages
  are documented (JRACLOUD-94906) → rows are de-duplicated on `(issueId, changelog id)`; 404/405 → per-issue fallback.
- 429 → honour `Retry-After` (seconds or HTTP date); missing → 1, 2, 4, 8 s backoff, then fail with a hint.

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
- `?expand=changelog` on Data Center returns the most recent histories only; the client refuses to return a truncated
  history rather than silently miscounting.
