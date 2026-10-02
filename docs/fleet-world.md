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

The plaza is paved in rings of stone, with a brass compass at its centre, inside a kerb at the edge of
the agents' circle. Outside the kerb stand eight cast-iron street lamps, a wooden bench between each
pair and a tree in a stone planter behind each bench; the circle and its furniture grow with the
fleet. You walk around the benches, trees and lamp posts, not through them. Beyond the plaza is
asphalt, and puddles everywhere, which ripple in the rain and mirror the sky. A ring of 44 buildings,
62 to 120 m out, makes the skyline: facades in eight colours, windows and shopfronts, parapets,
setbacks and rooftop boxes. The sky is overcast with moving cloud.

Every asset is built in the page from three.js's own shapes and a few lines of shader
(`world/scenery.js`, `world/bots.js`): no model file, no texture, nothing fetched and no package.
The detail is in merged geometry and the shaders, never in more objects, so it costs no draw calls.

## Rain, day and night

It is always raining. The rain is 6,000 streaks in a box around you, plus rings where drops land in
the puddles. The local clock decides the light. Overcast day runs from about 07:30 to 18:30, with
dawn from 06:00 and dusk until 20:00. By night the lamps are lit, with a halo round each, they light
the rain falling past them and reflect in the wet ground; the city's windows light up, some warm and
some cool, and its glow shows on the low cloud.
`?hour=0..23` pins the clock, for tests and screenshots. The scene is the world's own look: a palette
or skin you chose dresses the HUD, never the rain.

## Frames

The frame budget is **10 ms**: 100 frames a second.

- **The display sets the ceiling.** The browser draws at most once per display refresh. A 120 or
  144 Hz display runs the world at its own rate; a 60 Hz display caps it at 60, whatever the GPU.
- **The page keeps every frame within the budget.**
  - The scene is at most 12 draw calls however many agents there are. The city, the plaza's
    furniture and each robot are merged into one mesh each, the robots are instanced (four draw calls
    for every agent), the rain is one draw call, and the names are page text. Your
    character adds ten (twelve in a wheelchair): the parts that move together are one mesh each, all
    sharing one material, so a change of look compiles no shader.
  - It has no shadows and no post-processing.
  - The wet ground's reflection of the sky is rendered once, not per frame.
  - When frames run long it lowers its render resolution. Once a second it compares the median frame
    with the display's rate (or the 10 ms budget on a display faster than 100 Hz), steps down to half
    resolution at worst, and back up when there is room.
- **It stops drawing when the tab is hidden.**

`FleetWorld.inspect()` reports `fps`, `frameMs` (the median interval), `workMs` (the script's own time
per frame), `scale`, `calls` and `triangles`; F3 shows the same in the toolbar.

CI draws in SwiftShader, on the CPU, at a few frames a second, so the tests measure what does not
depend on the machine: the draw calls (at most 12, plus the character's ten or twelve), the
triangles (under 80,000), the walk (`FleetWorld.hold` and `FleetWorld.step` advance it without waiting on frames),
reach, and the verbs a conversation posts. **The frame rate is the laptop's to measure:** open
`/world`, press F3, and read the fps line in Edge or Chrome on the operator's GPU.

## What it is not (yet)

- No multiplayer or physics; nobody else sees your character.
- No on-screen keyboard for free text with a controller.
- The scene is not themed.
- It is not the map's scene (#409–#414): that is a different page that draws zero frames at rest.
