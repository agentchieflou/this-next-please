# `chat.css`

The reasoning for this stylesheet, kept out of the source (decisions 18 and 19 on #429). The source
keeps its rules, and the server strips any comment from what it serves (`agentdata/fleet/strip.py`).

A `###` heading is the rule or at-rule the notes sit in or above, by its selector or prelude, in
source order. A builder who changes a rule changes its note here.

### The file

/chat, the chat view (operator request, 2026-10): the traditional layout, over `app.css`. Since
2026-10-06 (*"adopting all of the themes in a cohesive manner (sticking 1:1 with the desk view)"*) the
conversation is a desk pane: `#chatmain` is a `.tile` holding the desk's classes, so `app.css` draws
it, and a skin's rules and marks select it, exactly as they do a pane. This file adds only what a
pane does not have (the sidebar, the log, the reply box's `textarea`) and keeps every selector it
adds at a class's weight, so a skin's `.tile .head .repo` or `.asks` still wins here as it does on
the desk. Tokens only, no colour literals. Secondary words are `--muted`, as on the desk: it holds
4.5:1 on every palette and every skin's composited panel (`tests/test_fleet_skins.py`).

### `#chat`

Two columns: the sidebar at 220–300 px, the conversation the rest. `minmax(0, 1fr)` so a long line
in the log wraps instead of widening the page.

### `.ca-glyph`

The state is the glyph's shape first (the desk's glyphs, `C_GLYPHS`), its colour second: the rail's
filled circle (`.pr-glyph`), in the state's colour with its `--on-*` text, so an agent reads the same
in the chat's sidebar as on the desk's rail.

### `.ca.needs-human .ca-head`

An agent that needs a person is marked by an edge and the *needs you* badge, as `/m` marks its row;
the open agent is in the selection colour.

### `.cs.is-open .cs-open`

The session on screen: the selection colour and an accent edge, never a state colour, because which
session is open is not a state.

### `.ca:not(.is-open) .ca-new`

*start fresh* under the open agent only: on every agent it was a column of the same button. Every
agent's is a press away (open it), and the pane's bottom row has it too.

### `#chatmain`

The pane sits in its column with the desk grid's 8 px around it, the desk's edge, radius and panel
(`.tile` in `app.css`).

### `.head h2`

The agent's name is a heading for the page's outline, sized as the desk's `strong.repo`; at a
class's weight, so a skin that letters the name (the notebook's hand) does so here too.

### `.why:empty, .runline:empty`

With no agent open there is no run and nothing said: the two lines take no room.

### `.cm-scroll`

The log under the desk transcript's top rule, filling the pane between the head and the bottom row.

### `.cl`

One line of the conversation: who and when on top in the desk's monospace, the words below. The
operator's lines sit on the right in the selection colour, the agent's on the left in the page's
colour (the pane is the panel's), a question with the human colour's edge; tool calls and notes are
full-width and quiet, so the conversation reads as one.

### `.cl-tool .cl-text`

One monospaced line, cut with an ellipsis: the arguments are there to recognise the call, and the
desk's pane is where every byte of one is read.

### `#chatlog.no-tools .cl-tool`

The *tool calls* box: hidden lines are only hidden, so turning them back on needs no reload.

### `.asks .row, .approval .row`

The cards are the desk's (`.asks`, `.approval`); a question here also has its own answer field
(`.cq-answer`), and their buttons wrap rather than overflow a narrow pane.

### `.bottom .say`

The reply box is a `textarea` (Shift+Enter is a new line) in the desk's bottom row, beside the
pane's own buttons. `app.css` dresses `input`, `button` and `select` but not a `textarea`: given the
same panel, line, radius and focus ring here, one line tall and growing with what is typed
(`field-sizing`, where the browser has it).

### `@media (max-width: 720px)`

One column on a phone-width window: the list, or the open conversation with *← agents* to go back,
as `/m` does. The reply box takes the row's whole width and the buttons wrap under it. The pane is
the column's whole width and height: the desk's phone rule makes every pane but the open one a 56 px
rail (`.tile:not(.is-solo)` in `app.css`), and the chat's one pane is never a rail.

### `@media (pointer: coarse)`

44 px targets and a 16 px field on a touch screen, as on /m and /tidy.
