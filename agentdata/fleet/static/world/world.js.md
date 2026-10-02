# `world/world.js`

The reasoning for this script, kept out of the source (decisions 18 and 19 on #429). The source keeps
its code and the JSDoc types `tsc` reads; the server strips every comment from what it serves
(`agentdata/fleet/strip.py`).

A `###` heading is the declaration or statement the notes sit in or above, in source order.

### The file

/world (#626), the operator's verdict on #400 (2026-10-02): *"we need a option that allows a user to
move around in the browser, preferably at a minimum of 100 frames per second ... the agents become
objects. And when they need a user, a user has to move to the agent to interact with it ... don't
focus too much on themes. Just assume it is a rainy day. And that it can be day or night, depending
on what the local time is."*

A classic script after `common.js` (its `q`, `post`, `pageUrl`, `patchList` and setters), which
imports the vendored three.js r160 itself with `import(q(...))`, as the ink layer does: nothing from a
CDN, and the token on the URL. It reads `/api/fleet` and the stream like the phone page and the chat
view, and posts the desk's own verbs, so it adds no route and no rule. The player's character is
`world/hero.js` (`WorldHero`), loaded before this script.

Unlike the desk's ink and the map's scene, which draw zero frames at rest, the world draws every
display frame: moving through a place is the point of it. It stops when the tab is hidden, because
`requestAnimationFrame` does.

### `var V_STATE`

The states' colours in the scene. The scene is the world's own look (the operator: don't focus on
themes), so these are fixed: a palette reaches the HUD, which is drawn in the page's tokens, never
the rain.

### `var V_DAY`

Rainy daylight is overcast: the zenith brighter than the horizon, and the fog the horizon's colour,
so the towers fade into the rain instead of standing out against it. Night is near black with a
blue-grey haze, lit by the lamps.

### `var V_REACH`

You talk to an agent only within 3.2 m of it and facing it (`V_FACING`, about 57° either side). That
is the operator's rule, *a user has to move to the agent to interact with it*: nothing on this page
answers, approves or sends from a distance.

### `var V_BUDGET_MS`

The frame budget, 10 ms: 100 frames a second. The page cannot draw faster than the display refreshes
(`requestAnimationFrame` is the display's clock), so a 120 or 144 Hz display runs at its own rate
and a 60 Hz one at 60; what the page controls is that a frame never needs more than the budget,
which `vTune` holds by lowering the render resolution.

### `var V_RAIN`

6,000 streaks in one draw call. The rain is a box of streaks around the camera, animated entirely in
the vertex shader from `uTime`, so no drop is touched on the CPU after it is made.

### `var V_CAP`

The figures are instanced: every agent's base, body, ring, visor and beacon is one draw call each,
however many agents there are, up to 64. The scene is 13 draw calls whatever the fleet's size: the
names are words on the page, not in the scene (`drawLabels`). Your character adds its own ten (twelve
in a wheelchair, `WorldHero`), whatever the fleet's size too.

### `var V_LOOK_KEY`

Your character's look is kept in the browser (`localStorage`), as the desk keeps a skin: it is how you
appear to yourself on this machine, not a fact about the fleet, so the server never stores it.

### `var V_STRIDE`

Radians of leg swing per metre walked: about a 0.9 m stride at the character's height, so the feet
do not slide on the ground at a walk or a run.

### `function vHour`

`?hour=` pins the clock, for tests and screenshots; otherwise the local time decides, read again
every minute.

### `function vDaylight`

Dawn from 06:00 to 07:30 and dusk from 18:30 to 20:00, eased: 1 is overcast day, 0 is night.

### `function vContext`

WebGL2, else WebGL (three.js r160 draws on either), else nothing: a browser without either gets
`#wnogl`, which says why and links the chat view and the desk, where the same agents are.

### `function vRain`

Each streak is two vertices sharing a drop's random `xyz`; `w` says which end. The box (44 m wide,
22 m high) follows the camera through `fract`, so a drop stays where it is in the world until it
leaves the box and comes in on the other side: walking through the rain, not carrying it. Streaks
fade with distance in the shader rather than through the scene's fog, which a `ShaderMaterial`
would have to include.

### `function vSplash`

Rings where drops land: one instanced ring drawn 160 times, each growing and fading on its own phase
and moving to a new spot each cycle, in a 16 m square around the player.

### `function vProps`

The ground is one large plane in a wet material (low roughness, a little metalness) that reflects
the sky through `scene.environment` and the lamps by night. The plaza is a stone curb at the
agents' circle, not a second disc: a disc of 64 thin triangles under point lights shaded triangle by
triangle in SwiftShader, and the wet ground already reads as the square. The towers are one
instanced box, far enough into the fog to be silhouettes. Eight lamps, with four point lights
between them, which light the wet ground at night and are off by day.

### `function vFigures`

The agents' parts, instanced: a plinth, a capsule body tinted towards its state's colour, a floating
ring and a visor in its state's colour (unlit, so they glow at night), and, for an agent that needs
a person, a tall beam that ignores the fog so it can be seen across the plaza.

### `function vLayout`

The agents stand on a circle, sorted by name, facing its centre; the circle grows with their number.
A row that leaves takes its figure and its label with it.

### `function vSpinRings`

A running agent's ring turns; a needs-you ring bobs. Under reduced motion they hold still.

### `function vWeather`

Day and night move together: the sky, the fog, the light, the lamps, the beam, the rain's colour and
your character's fill (`WorldHero.fill`).
The fog thins by day (0.014) so the towers read as shapes in the rain; it thickens at night.

### `function vReflect`

The sky, rendered once into an environment map (`PMREMGenerator`), is what the wet ground reflects.
It is made again only when the weather is (once a minute without `?hour=`), never per frame.

### `function vPad`

The first connected gamepad, in the Gamepad API's standard mapping: axes 0 and 1 the left stick,
2 and 3 the right; buttons 0 A, 1 B, 3 Y, 7 RT, 9 Start, 10 L3, 12 to 15 the D-pad.

### `function vStep`

One step of the walk: the left stick or WASD moves (Shift, RT or L3 runs), the right stick, the
mouse (with pointer lock) or Q and the arrows turn. The agents are solid (you stop a metre from
one), and the world ends 20 m past the circle. A new press of A beside an agent opens it. With a
conversation open, the pad drives the panel instead (`vPanelPad`); with the character picker open it
drives the picker (`vWhoPad`). Start opens and closes the picker, Y changes the view.

The distance walked is what the character's legs swing by (`vState.walk`, backwards when you back
up) and what a wheelchair's wheels turn by (`vState.rolled`); the speed, as a share of a walk, is how
far they swing.

### `function vCamera`

Third person by default, as the operator's picture is a character you see: the camera 3.4 m behind
and 2 m up, looking past the character's shoulder to a point ahead of it, and tilted by the pitch.
In a conversation it swings 1.3 m to the side, so you see your character presenting to the agent and
the agent beside it. First person (V, or Y) is the eye at 1.6 m, as before. While you choose who you
are, the camera stands in front of the character and looks at it.

### `function vHeroFrame`

The character stands where you stand and faces where you face. Standing still, the stride eases to
the nearest step where both feet are down, so it never stops mid-stride. `talk` blends into the
presenting pose over about an eighth of a second, and at once under reduced motion. In first person
the character is hidden: you are behind its eyes.

### `function vLoadLook`

`?who=N` starts from the Nth preset (for tests and screenshots); otherwise the look kept in this
browser, read through `WorldHero.normal` so a stale or hand-edited one cannot break the build. None
means a first visit.

### `function vLook`

A choice in the picker builds the character again and keeps the look at once: there is no "save",
what you see is who you are.

### `function vView`

The view is also written on `body[data-view]`, where a test or a stylesheet can read it.

### `function vWho`

The picker: the keys and pointer lock let go and a conversation closes, so nothing walks or answers
while you choose, and the keyboard lands on the preset you are wearing. Closing it hands the keyboard
back to the scene. A first visit opens it (`vStart`): you choose who you are before you walk.

### `function vLookKey`

Two looks are the same when their normal forms are; a preset reads as chosen only when every option
matches it.

### `function drawWho`

The presets, then one row of choices per option, each row a radio group with its label. Colours are
swatches named by their place in the row ("skin 3 of 8"), never by a word for a person's colour.
The scarf colour row shows only when the hair is a headscarf or a wrap.

### `function vWhoRows`

The picker as a grid for the pad: Done, the presets, then each visible option row.

### `function vWhoPad`

Up and down move between rows, left and right along one (wrapping), A chooses, B or Start closes.
The left stick moves too, with a repeat delay, as in a conversation.

### `function vNearest`

The agent within reach and in front of you, the nearest if several: the one E or A talks to.

### `function vFrame`

The simulation steps with the frame, capped at 50 ms so a stall does not throw you across the plaza.
`FleetWorld.hold(true)` stops the steps (the frame still draws) so a test can drive `step()` itself.

### `function vTune`

Once a second. The display's own frame interval is the fastest the page has seen (the 5th
percentile). On a display at 100 Hz or slower the target is that interval: hold the display's rate.
On a faster one the target is the 10 ms budget: a 144 Hz display may run at 100 fps before the
resolution drops. A median frame 15% over the target lowers the render scale by 15%, down to half
resolution; one under it raises it again, up to the device's pixel ratio or 1.5, whichever is lower.

### `function drawLabels`

Each agent's name and state are a label on the page (`#wlabels`), placed over its head by projecting
that point through the camera every frame, and scaled by distance. Words in the DOM rather than
textures in the scene: nothing under `static/` asks for a 2D context (#257, held by
`tests/test_fleet_trace.py`), a label is as sharp as the page's own text at any resolution scale, and
the scene stays 13 draw calls whatever the fleet's size. A label behind you, beyond 48 m, off the
screen or under an open conversation is hidden. The transform is rounded to the pixel and the scale to
a twentieth, so a label is written only when it moves visibly: standing still writes nothing.

### `function drawHud`

The prompt names the agent within reach; the compass points at the nearest agent that needs you and
says how far. The arrow turns in 5° steps, so turning writes the DOM only when it moves a step.
`F3` (or the backquote) shows fps, frame time, the render scale and the draw calls (`?hud=1` at load).

### `function drawList`

The agents and their states in words, for a screen reader (`#wlist`), and how many need you in the
header.

### `function vTalk`

A conversation: the panel opens, the keys and pointer lock let go, and the keyboard lands on the
first choice, else Approve, else the message box, so a controller can answer at once. You turn to face
the agent, so your character presents to it.

### `function vPanelPad`

In a conversation the D-pad (or the left stick, with a repeat delay) moves between the panel's
buttons and fields, A presses the button that has the keyboard, and B steps back. A choice fills the
answer, so a question with choices is answered without a keyboard; free text needs one.

### `function vRefresh`

Each agent's stream cursor starts at its `last_seq`, as the chat view's does: the stream sends what
happens next, never every agent's history again.

### `window.FleetWorld`

What the tests and the laptop read: `inspect()` (the agents, the player, who is near, day or night,
the lamps, the draw calls and triangles, fps, frame and work time, the render scale, the view, the
picker, the look, and the character's place, turn and pose), `hold()` and
`step()` to walk without depending on the frame rate (CI draws in SwiftShader), and `teleport(repo)`
to stand within reach of an agent.
