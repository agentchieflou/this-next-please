# `chat.css`

The reasoning for this stylesheet, kept out of the source (decisions 18 and 19 on #429). The source
keeps its rules, and the server strips any comment from what it serves (`agentdata/fleet/strip.py`).

A `###` heading is the rule or at-rule the notes sit in or above, by its selector or prelude, in
source order. A builder who changes a rule changes its note here.

### The file

/chat, the chat view (operator request, 2026-10): the traditional layout, over `app.css` (its
tokens, its toolbar, `.linkbtn`, `.chip` and `.ask-choice`). Tokens only, no colour literals, so the
palette and the skin reach it through the page dressing (`serve._page`) as they reach the map and the
phone page. No word is in `--muted`: secondary words are `--text` at a smaller size, so every
sentence reads at 4.5:1 on every palette.

### `#chat`

Two columns: the sidebar at 220–300 px, the conversation the rest. `minmax(0, 1fr)` so a long line
in the log wraps instead of widening the page.

### `.ca-glyph`

The state is the glyph's shape first (the desk's glyphs, `C_GLYPHS`), its colour second, through the
`--*-text` tokens the desk uses for words in a state's colour.

### `.ca.needs-human .ca-head`

An agent that needs a person is marked by an edge and the *needs you* badge, as `/m` marks its row.

### `.cs.is-open .cs-open`

The session on screen: the selection colour and an accent edge, never a state colour, because which
session is open is not a state.

### `.cl`

One line of the conversation: who and when on top, the words below. The operator's lines sit on
the right in the selection colour, the agent's on the left in the panel colour, a question in the
human colour's edge; tool calls and notes are full-width and quiet, so the conversation reads as one.

### `.cl-tool .cl-text`

One monospaced line, cut with an ellipsis: the arguments are there to recognise the call, and the
desk's pane is where every byte of one is read.

### `#chatlog.no-tools .cl-tool`

The *tool calls* box: hidden lines are only hidden, so turning them back on needs no reload.

### `#chatmessage`

The composer is a `textarea` (Shift+Enter is a new line), and `app.css` dresses `input`, `button` and
`select` but not a `textarea`: given the same panel, line, radius and focus ring here, so it reads as
the desk's reply box on every palette rather than as the browser's own grey field.

### `@media (max-width: 720px)`

One column on a phone-width window: the list, or the open conversation with *← agents* to go back,
as `/m` does.

### `@media (pointer: coarse)`

44 px targets and a 16 px field on a touch screen, as on /m and /tidy.
