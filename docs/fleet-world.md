# The world

`/world` (#626) is the fleet as a place: a wet plaza in the rain, one robot per agent, and you, a
character you choose, walked with a controller or the keyboard. The operator chose it as the next thing to explore
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
there. On a phone-width desk (640 px and under) the link gives its room to the others: the world is
walked with keys or a controller, and `/world` still opens there.

## Moving

| | Keyboard and mouse | Controller (standard mapping) |
| --- | --- | --- |
| walk | W A S D, or the arrows | left stick |
| look | the mouse, after a click on the scene (pointer lock); Q and ← → turn | right stick |
| run | Shift | RT, or press the left stick |
| talk to the agent in front of you | E or Enter | A |
| in a conversation | Tab | the D-pad (or the left stick) between buttons, A to press |
| step back | Esc | B |
| third or first person | V | Y |
| choose your character | C (Esc closes) | Start (B or Start closes; the D-pad moves, A picks) |
| show fps and frame time | F3 or \` | — |

## Your character

The operator, with a picture of a friendly cartoon figure in a light-grey shirt and navy trousers, one
arm out, presenting: *"Use some one like this as the main character. Create diverse character options
so everyone feels included."*

You see your character from behind and over its shoulder (third person, the default), or through its
eyes (first person, V or Y). It walks with you: legs swinging with the distance walked, so the feet
do not slide, arms against the legs. When you talk to an agent you turn to face it, the camera swings
to the side, and your character presents to it, one arm out, palm up, as in the picture.

The first visit opens **Who are you in the world?** (C or Start opens it again). Start from one of ten
looks, then change anything:

| | |
| --- | --- |
| skin | eight tones, deep to light |
| hair | a side part, curls, coils, long, a bun, locs, a buzz cut, none, a headscarf, a wrap |
| hair colour | black, browns, auburn, blond, silver, and blue |
| scarf or wrap | its own colour, when the hair is covered |
| face | none, a beard, a moustache |
| glasses | none, round, square |
| shirt, trousers | eight and five colours |
| build | slim, regular, broad |
| moves by | walking, or a wheelchair whose wheels turn as it rolls and whose rims the arms push |

No option or look is named for a gender: they are looks a person chooses, not a box they are put in.
The ten looks (*side part*, the operator's picture, then *curls*, *headscarf*, *locs*, *silver bun*,
*beard*, *wheelchair*, *long hair*, *wrap*, *bald*) between them span every skin tone, every hair
texture, both coverings, both kinds of glasses, all three builds and a wheelchair user. A colour is a
swatch named by its place in the row (*skin 3 of 8*), never by a word for a person's colour.

Your choice is kept in this browser (`localStorage`, `fleet.world.look`), not on the server: it is
how you appear to yourself on this machine. `?who=0..9` starts from a look, `?view=first` in first
person.

## The agents

Every `/api/fleet` row is a small robot on a circle around the plaza, sorted by name and facing the
middle. Each robot has a white shell tinted a pale colour from its name, a dark visor with eyes and a
smile, a chest light, an antenna and a hover base, and a ring at its waist. The eyes, the lights and
the ring are in its state's colour and glow at night. It bobs on its base, faster while it works,
when its ring turns too; under reduced motion it holds still. Over its head is a label with its name
and state in words. The label is page text, not a texture, so it stays sharp.

An agent that needs a person raises a red beam that shows through the rain and the fog (and fades
when you stand at it, so it never fills the view), its eyes pulse, and the HUD's
compass points at the nearest one with its distance. **You talk to an agent only within 3.2 m of it,
facing it.** That is the operator's rule ("a user has to move to the agent"): nothing on this page
answers, approves or sends from a distance. A conversation opens beside the agent, with:

- its state, its sentence, and its last words;
- the approval it is waiting on, if any (Approve, or Deny with a reason);
- its open questions, each with its choices as buttons, so a controller can answer without a keyboard;
- a message box (free text needs a keyboard; there is no on-screen keyboard yet).

Everything posts the desk's own verbs (`answer`, `approve`, `deny`, `send`, or `say` to a console), so
every refusal is the server's, in its words. The page adds no route.

## The place

The operator, 2026-10-02: *"We're looking for a far cry 3 / rdr2 / gta 6 / cyberpunk quality world
with rich assets and quality features that can run in browser."* The plaza is the middle of a
district you can walk into.

- **The plaza** is paved in rings of granite, with a brass compass at its centre. Eight cast-iron
  lamps stand round the agents' circle, with a bench between each pair and a tree behind each bench.
  The circle, the plaza and everything round it grow with the fleet.
- **The streets.** A ring road goes round the plaza and four avenues lead out of it, crossed by side
  streets every 64 m. They have:
  - lane markings, zebra crossings, stop lines and manhole covers;
  - granite kerbs, and gutters where the water gathers;
  - street lamps every 24 m (sodium orange or LED white), each with a cone of light in the rain;
  - traffic lights at every crossing, cycling red, amber and green;
  - trees, hydrants, bins, newspaper boxes, utility cabinets, parking meters and bus shelters;
  - on the side streets, bags and boxes by the bins, air-conditioning units against the walls,
    concrete barriers at a few corners, and the odd car under a cover.
- **The buildings.** About 150 of them, in five styles: brick walk-ups with fire escapes and water
  tanks, stucco with balconies, concrete, stone with cornices, and glass towers further out. They
  have:
  - windows set into the walls;
  - shopfronts with awnings, lit signs and neon;
  - rooftop air-conditioning units, antennas and billboards.

  Behind every window there is a room: its walls, floor, ceiling and furniture are drawn by the glass
  itself (interior mapping). By night some rooms are lit, warm or cool, switching on and off over the
  evening; some show only a television's flicker.
- **Life.** Cars drive the avenues and the ring road. They keep their distance and stop at red
  lights, with their headlights on the wet road at night. Cars are parked along the side streets,
  and people with umbrellas walk the sidewalks.
- **Walking.** You walk up to 150 m from the plaza. Buildings, benches, trees, lamp posts and street
  furniture are solid.

The shapes are built in the page from code: three.js's own shapes, merged by material, and
shaders. The surfaces and the small things are real:

- **Photo textures.** Brick, stucco, concrete, asphalt and sidewalk are Poly Haven's photographed
  materials, at the size each covers in reality (a 3 m photo of brick is laid 3 m wide). The rest
  (stone, granite, metal, roofing, wood, leaves) are baked on the GPU when the page loads
  (`world/bake.js`). Every surface has colour, roughness, occlusion and relief.
- **Scanned props.** The hydrants, bins, bags, boxes, cabinets, air-conditioning units, barriers and
  covered cars are Poly Haven's photo-scanned models, decimated to a few thousand triangles and
  drawn instanced: one draw call per kind of prop, however many stand in the street.
- **Real skies for light.** The light everything is lit and reflects by comes from two photographed
  city skies, an overcast square by day and a lamp-lit one by night, blended with the hour. The sky
  you see is still the page's own, raining.

The operator allowed them on 2026-10-03: *"If it is open source and safe, you may use Poly Haven
assets."* Every one is CC0 (public domain), credited by name and author in
`agentdata/fleet/static/world/cc0/LICENSE`. They were made small for a browser before they were
committed (WebP textures, decimated models, 512 x 256 skies): 4 MiB in all, in the package, served by
the fleet's own server like its scripts. Nothing comes from the internet. If a file is missing, the
world falls back to its own version of that thing (a baked material, the sky shader, a built
hydrant). Poly Haven has no people, so the characters are still the page's own. The world's script
is 61.5 KiB.

## Rain, day and night

It is always raining. There are 6,000 streaks in a box around you and rings where drops land, and
the streaks are lit by the lights they fall past. Everything is wet:

- surfaces are darker and glossier;
- puddles gather in the gutters and the low spots, and drops ring them;
- the street is a mirror of the city above it, sharp in a puddle and smeared on wet asphalt.

The local clock decides the light. Overcast day runs from about 07:30 to 18:30, with dawn from 06:00
and dusk until 20:00. By night:

- the lamps, the shop signs, the neon, the billboards and the cars' headlights light the street
  round them in their own colours;
- the windows light up;
- the city's glow shows on the low cloud.

Hundreds of lights, and a pixel adds up the nearest few. `?hour=0..23` pins the clock, for tests and
screenshots. The scene is the world's own look: a palette or skin you chose dresses the HUD, never
the rain.

## Frames

The frame budget is **10 ms**: 100 frames a second.

- **The display sets the ceiling.** The browser draws at most once per display refresh. A 120 or
  144 Hz display runs the world at its own rate; a 60 Hz display caps it at 60, whatever the GPU.
- **The frame is drawn the way open-world games draw theirs** (`world/render.js`): light in high
  dynamic range, a reflection of the scene for the wet street, ambient occlusion, bloom round every
  light, the ACES tone curve and a grade. There are no shadow maps: under overcast cloud and in the
  rain, occlusion is the shadow.
- **The quality fits the GPU.** `?quality=low|medium|high|ultra` chooses; otherwise the GPU decides:
  - **high** for a discrete GPU: 4x MSAA, the mirror at half resolution, 24 lights a pixel;
  - **medium** for an integrated one: FXAA, the mirror at a third, 16 lights;
  - **low** for WebGL1 or a software renderer: straight to the screen, no mirror, plainer facades,
    8 lights;
  - **ultra** only when asked for.

  Each tier draws the same scene, at a different cost.
- **The page keeps every frame within the budget.**
  - The draw calls do not grow with the fleet. The city is merged by material (a dozen draw calls
    for every building), and the robots, cars and people are instanced (four draw calls for every
    agent, every car and every walker). The names are page text.
  - Your character adds ten draw calls (twelve in a wheelchair). The parts that move together are
    one mesh each, all sharing one material, so a change of look compiles no shader.
  - When frames run long it lowers its render resolution. Once a second it compares the median frame
    with the display's rate (or the 10 ms budget on a display faster than 100 Hz), and steps down to
    half resolution at worst. If that is not enough, it drops a quality tier. It steps back up when
    there is room.
  - The surfaces are baked or uploaded once at load, and the sky's environment made once a minute,
    never per frame.
- **It stops drawing when the tab is hidden.**

`FleetWorld.inspect()` reports:

- `fps`, `frameMs` (the median interval) and `workMs` (the script's own time per frame);
- `scale` and `quality`;
- `calls` and `triangles` (the scene), and `passes` (the whole frame's draw calls);
- `town` (buildings, lights, cars, parked cars, people, scanned props);
- `cc0`, how many of the CC0 textures, skies and props loaded.

F3 shows the frame figures in the toolbar.

**On a software renderer** (SwiftShader in CI, or a virtual desktop without a GPU), the page draws
its lightest path: the `low` quality, plainer facades, no parked cars or walkers, props only within
75 m, half resolution, and the scene at most about ten times a second. The walk keeps the display's pace. The tests therefore
measure what does not depend on the machine:

- the draw calls (at most 64) and triangles (under 400,000) on that path;
- that the full pipeline compiles and draws (`?quality=high`), and that what reaches the screen is
  the frame, not a cleared canvas;
- that every CC0 file loads;
- the walk (`FleetWorld.hold` and `FleetWorld.step` advance it without waiting on frames), reach, and
  the verbs a conversation posts.

**The frame rate is the laptop's to measure:** open `/world`, press F3, and read the fps line in Edge
or Chrome on the operator's GPU.

## What it is not (yet)

- No multiplayer or physics; nobody else sees your character. The cars do not hit you, nor you them.
- You cannot enter the buildings: their rooms are drawn by the glass.
- No on-screen keyboard for free text with a controller.
- The scene is not themed.
- It is not the map's scene (#409–#414): that is a different page that draws zero frames at rest.
