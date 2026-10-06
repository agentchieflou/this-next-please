# `chat/chat.js`

The reasoning for this script, kept out of the source (decisions 18 and 19 on #429). The source keeps
its code and the JSDoc types `tsc` reads (docs/desk-types.md); the server strips every comment from
what it serves (`agentdata/fleet/strip.py`).

A `###` heading is the declaration or statement the notes sit in or above, in source order.

### The file

/chat, the chat view (operator request, 2026-10: "a view where agents are tracked in a left sidebar,
and all of their active sessions sit beneath each agent, where one session's chat is readable at a
time ... we want to make sure we're offering a traditional offering as well"). A modular addition
beside the desk, never a replacement for it: the desk keeps its panes, its widths and its skins, and
this page is one more address, opened from the desk's toolbar (*chat*, or the `c` key on the pane the
keys are on), or pasted as `/open?page=chat`.

It adds no route and no rule. It reads what the desk reads -- `GET /api/fleet` for the agents,
`GET /api/sessions?repo=` for each one's sessions, `GET /api/transcript` for the one conversation on
screen, and the event stream for what happens next -- and it posts the desk's own verbs (`send`,
`say`, `answer`, `approve`, `deny`, `start`, `fresh`), so every refusal it shows is the server's,
in the server's words.

A classic script after `common.js`, whose `q`, `post`, `pageUrl`, `patchList`, setters and
`applyThemeState` it uses. No `innerHTML`: every row is a template filled through `textContent`.
Not in `tsconfig.json`'s program, like `m/m.js`: its globals (`W_NAME`) are `app.js`'s names too,
and the two are never loaded together.

### `var C_SESSIONS_SHOWN`

Five sessions under each agent before *N more*: the current one first, then the newest. An agent
that has run for a month has dozens, and a sidebar that listed them all would push every other agent
off the screen -- the opposite of tracking agents in a sidebar.

### `var C_WIDE`

On a phone-width window the sidebar and the conversation are one column, one at a time
(`body.is-open`), so the page does not pick a conversation for the operator at boot: it opens on
the list.

### `var cState`

`repo` and `session` are what the operator chose. `session` is `""` for *the agent's current
session*: choosing the agent, or its current session, follows the agent, so a fresh start moves the
view to the new session the way a chat app moves to a new conversation. An explicit id is that one
session, read-only unless it is the current one. `shown` is what the log holds: `key` is the
`repo|session` it was loaded for, `seq` the last event in it (so a replayed frame is never appended
twice), `cursor` the `before` for the page above.

### `function cCurrent`

The session `send` would continue: the latest run's (`row.run.session`), which is what
`supervisor.session_id` resumes.

### `function cSessionsOf`

The sidebar's rows for one agent. `/api/sessions` is the list (hand-set titles, Copilot's own store,
`left` marks from a fresh start); the current session is added from the row when the index has not
caught up with it yet, and a live run that Copilot has not named yet is shown as *a new session*.
The chip says which is which: *live* while its turn runs, *current* when it is idle, *left* for a
session a fresh start left, and where a session came from when it was not the fleet's.

### `function drawSession`

Choosing the current session follows the agent (`session = ""`); choosing any other is that session.

### `function chatLine`

What each event kind says in a conversation, and on which side. The operator's words are the
`prompt` of a resumed `started` (that is what `send` and `answer` write), a `said` line typed into a
console, and an answered question; the agent's are `assistant_text` and its questions. Tool calls are
one monospaced line each, and a successful result is not a line at all: in a conversation the call
is the news, and *ok* under every one of them buried it. The *tool calls* box hides them all.
`turn_started`, `turn_ended`, `session_id`, `cost` and `raw` are bookkeeping, never a message.

### `function chatLoad`

One session's conversation, from `/api/transcript`, newest page first; *earlier messages* asks for
the page above with `before` and keeps the scroll where it was. A live run Copilot has not named yet
has no id to ask for, so its events come from the row's `recent` until the `session_id` arrives, the
key changes, and the transcript takes over.

### `function cForeign`

A `started` frame for a session other than the one on screen (a fresh start, a resume of another)
belongs to a conversation this log is not. It is not appended; the refresh it triggers moves the
view, and the reload clears the flag.

### `function drawAsks`

The agent's open questions, answered together in one turn (`answer`, as the desk's card does). A
question with no id cannot be answered by id -- the server needs one -- so it says to reply in the
box below, and its choices fill that box instead.

### `function drawApproval`

The oldest waiting approval of this agent, decided here with the desk's verbs. Only on its current
session: an earlier one is read, never acted on.

### `function cVerb`

`start` for an agent with no session yet (a ticket key, or empty for a clean session), `say` for a
console the fleet opened (typed into that window, #190), `send` otherwise.

### `function drawCompose`

The composer on the current session; on an earlier one, a line saying so and *Resume here*, which is
the desk's second deliberate press (`start` with `resume`). A refusal that a press can override
(`live_agent`, `mid_ticket`) arms it, and the label says what the next press does.

### `function cSubmit`

Enter sends, Shift+Enter is a new line. Over budget, the server refuses `budget_exceeded` and the
button becomes *Send anyway*: the next press spends one more turn, as on the desk.

### `function cFresh`

*+ new session* is the desk's *start fresh*. A session that is still open is refused with
`second_press`; the next press on the same agent sends `closed: true`.

### `function cPick`

What the page opens on: `#<repo>` or `#<repo>/<session>` from the address (the desk's `c` key and a
bookmark), else the agent that needs a person, else the most recently active one.

### `function cRefresh`

An agent's sessions are re-read only when its current session or its count of sessions moves, not on
every frame: `/api/sessions` rebuilds the index from the stream.

An agent's stream cursor starts at the row's `last_seq`, as the desk's starts at its pane's: the
conversation on screen came from `/api/transcript`, so the stream has only what happens next to
send, never every agent's whole history again.

### `function cConnect`

The phone page's stream (`notify=0`, so a desk's notification sweep is never taken from it), with one
addition: a frame for the agent on screen is appended to the log when it belongs to the session on
screen and is newer than the last line in it. Only a newer frame can say the conversation moved
(`cForeign`): a reconnect that replays an older `started` is history the log already holds.

### `prerender("#toworld");`

The world loads while the pointer rests on its link (`common.js`'s `prerender`, 2026-10-06), as it
does from the desk.
