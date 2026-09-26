# The desk's types

The desk is JavaScript with no build step, and it stays that way: the files ship as package data
and load in JCEF and Simple Browser behind a corporate proxy ([fleet-dashboard.md](fleet-dashboard.md)
§Why a web page). What TypeScript adds here is **checking**, and checking needs no build
([plan-panes.md](plan-panes.md) §Where this plan pushes back, item 1). So `tsc` reads JSDoc in the
page's own comments against the page's own code, emits nothing, and runs in CI. The page is still
the bytes in `agentdata/fleet/static/` (#236).

## Running it

```
npx --yes -p typescript@7.0.2 tsc -p tsconfig.json
```

It needs Node, and `npx` fetches the pinned compiler the first time. CI runs it as its own step in
the Linux job (`the desk's types`), and `tests/test_desk_types.py` runs the same command, so on a
machine with Node a type error is also a failing test. That test carries the `network` marker and
the real home, where npm keeps its cache and a laptop keeps its proxy settings. It skips where
there is no `npx`, where the compiler cannot be fetched, and whenever `AGENTDATA_OFFLINE` is set,
which skips it without trying.

The version is exact: a range would let a new release change what "clean" means under a branch nobody
touched. It is written in four places, the workflow, the test, this page and `tsconfig.json`'s
comment, and a test fails if they disagree. 7.0.2 is the native compiler. It reads JSDoc as 5.9 does:
on the first run, before anything was typed, it flagged the same places as 5.9.3 plus two
(`new Promise` resolves called with nothing), in under a second.

## The program: all of both files, typed in part

`tsconfig.json` is dev-only, at the repository root: `allowJs`, `checkJs`, `noEmit`, and `strict`
off to begin with. It names three files, `common.js`, `picker.js` and `app.js`, in the order the
pages load them, and nothing else.

**Why both.** `app.js` is a classic script. It reads `q`, `post`, `text` and the other setters as
globals that `common.js` declares, and a global resolves only inside one program.

**Why the picker (#362).** `picker.js` is the model picker, a classic script the desk and
/settings load between the two. It declares `createModelPicker`, `drawModelPicker` and `mpImpl` and
no other name: in one program a name it shared with `app.js` is a duplicate declaration, and on
/settings it shares the page with `settings.js`, which is not in the program.

**Why all of them.** The plan asked for the files D and E created and the desk-sync path A touched,
not all of `app.js`. But D and E created no files: the row, the tiers, the widths and the gutters are
sections of `app.js`, beside everything else. `// @ts-check` and `checkJs` switch a whole file on or
off, and nothing in between. So the checker reads all of both files, and the plan's limit is kept by
what is **typed**:

* **The typed part** carries JSDoc: the records below, and the functions that move them. That is
  where the checker knows what a value is.
* **The rest** carries only what the checker needed to read it without error. That is the kind of
  element a lookup returns, said at the lookup: `querySelector` answers `Element`, and the page means
  an input, a button or a canvas. With `strict` off, an unannotated parameter is `any`, so the rest is
  checked for names, arity and what the platform's own types say, and for little else.

`checkJs` sits in the config and not in `// @ts-check` pragmas: it is the same switch, said once where
the program is defined. A pragma would also make an editor that opens `app.js` without the config
check it alone, where none of `common.js`'s globals exist.

**Nothing is silenced.** `@ts-ignore`, `@ts-expect-error` and `@ts-nocheck` are refused by a test. A
cast says what a value is. A suppression says only "do not look", and the number below would mean
nothing if a diagnostic could be switched off where it stands.

## What is typed

| Type | What it is | Where it comes from |
|---|---|---|
| `DeskRecord` | the desk every window agrees on: `schema`, `selected`, `version`, `at`, `arrangement`, `windows`, `measure` | `desk_state()` in serve.py |
| `Arrangement` | `order`, `size` (read, never written), `pinned`, `hidden` | `_blank_arrangement()` |
| `WindowRecord` | one window's record: `open`, `focus`, `read`, `seen`, `held`, `section`, `widths`, `widths_at` | `WINDOW_FIELDS` |
| `Widths` | each pane's weight by repository, 0 a rail | #234 |
| `WindowWrite` | what this page writes to its record, which is not the whole of it: `open`, `widths`, `read`, `seen`, `section` | `saveWindow` |
| `DeskAnswer` | a desk as it arrives, with the envelope every POST carries (`ok`, `action`, `error`, `hint`, `code`) | the one door |
| `Pane` | an entry in `tiles`: its `.tile` element, the last event `seq`, the `row` it was drawn from | #233 |
| `Row` | an agent's row, typed in the fields the typed part reads and **open** for the rest | `/api/fleet` |
| `Tier` | `"rail"`, `"compact"` or `"full"` | `setTier`, the one writer |
| `Tiers` | the widths the tiers change at: `rail`, `compact`, `full`, `slack`, and `invalid` when the file's four were not drawn | `settings.tiers()`, on the theme payload (#235) |
| `Pixels`, `WidthsBefore`, `GutterHold` | a measured row, what a change of widths puts back, a gutter under the hand | #234 |
| `ModelEntry`, `ModelPick`, `ModelPickerOptions`, `ModelPickerState` | a catalogue entry, what a press reports, how a picker is built, and what it draws | `models.catalogue` (#360), `picker.js` (#362) |

The functions that carry them are:

* **The door and the writes (#230):** `saveWindow`, `acceptDesk`, `applyWindow`, `mergeDesk`,
  `choose`, `deskAsShown`, `patchRow`, `arrangeNow` and what reads the arrangement back.
* **The row (#233):** `makeTile`, `openName`, `openPane`, `backToPrevious`, the tiers (`paneTier`,
  `setTier`, the observer, and `applyTiers`, which takes the operator's widths, #235), grouping, the
  rail's face, and the keyboard's stops.
* **The widths (#234):** every function from `ownWidths` to `drawUndo`, the presets, and the gutters
  with their pointer and key handlers.

`WindowWrite` does some work of its own. A field one arrangement wrote and another read was the
snap-back (ground rule 2), so writing `zoomed`, or the retired `focus`, is a type error before it is
a bug on the glass. `Row` is open because the rest of the page reads many more of its fields, untyped.
A field the list does not name reads as `any`, not as an error, and closing it is the widening's job.

**The types are held to the server.** Types that describe a record are only true while they name what
the server sends. `tests/test_desk_types.py` compares:

* `DeskRecord` with the keys of `desk_state()`;
* `WindowRecord` with `WINDOW_FIELDS`;
* `Arrangement` with the blank arrangement;
* `WindowWrite` with the record, of which it must stay a strict part;
* `Tiers` with the keys of `settings.tiers()` (#235).

A field added to serve.py fails there until the page says what it is.

## What the check found

The plan makes widening the check a decision that only this number can justify: how many real
defects the check found in the typed part.

**In the typed part: none.** Everything it raised while the annotations went in was the annotations
learning what the code already knew. The window chain's first link resolves to nothing. A
`data-tier` read back from the DOM is a string until it is said to be a `Tier`. `nextElementSibling`
is an `Element`, and a pane is an `HTMLElement`. A gutter bound as an `Element` has no pointer events
in the platform's types. As an experiment, not enforced, `--strictNullChecks` over the same code
raised 85 diagnostics in the typed part, and none was real. They were markup the template guarantees,
`tiles.has` not narrowing `tiles.get`, and narrowing lost inside a closure. `--noUnusedLocals` found
two unused locals, which are dead code and harmless.

**In the rest of the two files, read with nothing typed: two, both latent, both fixed.** The first
run, before any JSDoc went in, reported 85 diagnostics across both files. Twelve were these two
defects:

1. **`var focus = openAgent` replaced `window.focus`** (`Duplicate identifier 'focus'`). A `var` at
   the top of a classic script *is* a property of `window`. In Chromium, `window.focus()` on the desk
   opened nobody, shut the notifications drawer and posted two window writes (`section: ""`, then
   `read`). The page's own comment already refused this trade for `open`. Nothing called the alias:
   the shells open an agent with `#tile=`, and the only test that named it asserted it was there. It
   went, the eight calls say `openAgent`, and the test that guards `open` guards `focus` too. `tsc`
   now reports any page global that collides with a platform one.
2. **`transparent()`'s fallback threw.** `(nums[i] || 0).trim()`: the number `0` has no `trim`, so
   the default for a colour with fewer than three parts was a `TypeError`, every second, from the
   ground's timer. Chromium serialises the glass skin's gradient colours as `rgb(r, g, b)` today, so
   it was not reachable. The fallback is `"0"` now.

The alias was nine diagnostics: the duplicate identifier, and eight calls checked against
`window.focus()`, which takes no argument. The fallback was three `trim`s. Neither defect shows in
the three hosts the desk runs in, so neither has a file in `tests/regressions/`.

None of the other 73 was a defect:

| Diagnostics | What they were |
|---|---|
| 51 | the kind of element a lookup returns: `querySelector` answers `Element`, `getElementById` `HTMLElement`, `cloneNode` `Node` |
| 14 | handlers whose event the platform types as its base `Event`, or whose `target` as an `EventTarget` |
| 4 | the window chain's first link, which resolves to nothing |
| 2 | two `new Promise` resolves called with nothing |
| 1 | `getArrangement`'s `{}`, beside a desk the checker had inferred as `{selected}` |
| 1 | `window.webkitAudioContext` |

## Widening it

On that number, the typed part does not argue for widening: it found nothing the tests had not. What
the check did earn came from reading the whole file:

* two latent defects that no test and no reader had found;
* a type for the window's writes that refuses a retired field;
* a test that fails when the server's records change under the page's types.

If it is widened, these are the next steps, each its own decision:

* closing `Row`;
* typing the setters in `common.js`, which today take anything;
* `strictNullChecks`, whose 85 in the typed part were all markup and closures;
* the other two pages, `settings.js` and `probe.js`.
