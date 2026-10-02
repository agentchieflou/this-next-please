# The world

`/world` (#626) is the fleet as a place: a wet plaza in the rain, one figure per agent, walked in
first person with a controller or the keyboard. The operator chose it as the next thing to explore
when asked which parked concepts came next (#400, 2026-10-02):

> the next thing we're going to explore is the 3d space. We have users that want the traditional setup
> that I requested earlier in this session, but we also have users that envision a future where they're
> able to interact with their agents via a controller. And in that instance, we need a option that
> allows a user to move around in the browser, preferably at a minimum of 100 frames per second, given
> that we know full games can be played in the browser at 120 frames per second. With this, right, the
> agents become objects. And when they need a user, a user has to move to the agent to interact with
> it. Given that this is a 3D space, don't focus too much on themes. Just assume it is a rainy day. And
> that it can be day or night, depending on what the local time is.

It is one more page beside the desk (`/`), the chat view (`/chat`) and the map (`/map`), never a
replacement for any of them. The desk's toolbar links it (*world*), and `/open?page=world` lands
there.

## Moving

| | Keyboard and mouse | Controller (standard mapping) |
| --- | --- | --- |
| walk | W A S D, or the arrows | left stick |
| look | the mouse, after a click on the scene (pointer lock); Q and ← → turn | right stick |
| run | Shift | RT, or press the left stick |
| talk to the agent in front of you | E or Enter | A |
| in a conversation | Tab | the D-pad (or the left stick) between buttons, A to press |
| step back | Esc | B |
| show fps and frame time | F3 or \` | — |

## The agents

Every `/api/fleet` row is a figure on a circle around the plaza, sorted by name and facing the middle.
Each figure has a plinth, a body tinted towards its state's colour, a floating ring and a visor in
that colour. Over its head is a label with its name and state in words. The label is page text, not a
texture, so it stays sharp. A running agent's ring turns.

An agent that needs a person raises a red beam that shows through the rain and the fog, and the HUD's
compass points at the nearest one with its distance. **You talk to an agent only within 3.2 m of it,
facing it.** That is the operator's rule ("a user has to move to the agent"): nothing on this page
answers, approves or sends from a distance. A conversation opens beside the agent, with:

- its state, its sentence, and its last words;
- the approval it is waiting on, if any (Approve, or Deny with a reason);
- its open questions, each with its choices as buttons, so a controller can answer without a keyboard;
- a message box (free text needs a keyboard; there is no on-screen keyboard yet).

Everything posts the desk's own verbs (`answer`, `approve`, `deny`, `send`, or `say` to a console), so
every refusal is the server's, in its words. The page adds no route.

## Rain, day and night

It is always raining. The rain is 6,000 streaks in a box around you, plus rings where drops land in
the puddles. The local clock decides the light. Overcast day runs from about 07:30 to 18:30, with
dawn from 06:00 and dusk until 20:00. By night the eight lamps are lit and reflect in the wet ground.
`?hour=0..23` pins the clock, for tests and screenshots. The scene is the world's own look: a palette
or skin you chose dresses the HUD, never the rain.

## Frames

The frame budget is **10 ms**: 100 frames a second.

- **The display sets the ceiling.** The browser draws at most once per display refresh. A 120 or
  144 Hz display runs the world at its own rate; a 60 Hz display caps it at 60, whatever the GPU.
- **The page keeps every frame within the budget.**
  - The scene is 13 draw calls however many agents there are. The rain is one draw call, the figures
    are instanced (each part is one draw call for every agent), and the names are page text.
  - It has no shadows and no post-processing.
  - The wet ground's reflection of the sky is rendered once, not per frame.
  - When frames run long it lowers its render resolution. Once a second it compares the median frame
    with the display's rate (or the 10 ms budget on a display faster than 100 Hz), steps down to half
    resolution at worst, and back up when there is room.
- **It stops drawing when the tab is hidden.**

`FleetWorld.inspect()` reports `fps`, `frameMs` (the median interval), `workMs` (the script's own time
per frame), `scale`, `calls` and `triangles`; F3 shows the same in the toolbar.

CI draws in SwiftShader, on the CPU, at a few frames a second, so the tests measure what does not
depend on the machine: the draw calls (at most 13), the triangles (under
60,000), the walk (`FleetWorld.hold` and `FleetWorld.step` advance it without waiting on frames),
reach, and the verbs a conversation posts. **The frame rate is the laptop's to measure:** open
`/world`, press F3, and read the fps line in Edge or Chrome on the operator's GPU.

## What it is not (yet)

- No multiplayer, physics or avatar body.
- No on-screen keyboard for free text with a controller.
- The scene is not themed.
- It is not the map's scene (#409–#414): that is a different page that draws zero frames at rest.
