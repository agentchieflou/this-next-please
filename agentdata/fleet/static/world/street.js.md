# `world/street.js`

The reasoning for this script, kept out of the source (decisions 18 and 19 on #429). The source keeps
its code and the JSDoc types `tsc` reads; the server strips every comment from what it serves
(`agentdata/fleet/strip.py`).

A `###` heading is the declaration or statement the notes sit in or above, in source order.

### The file

What is on the streets: lamps, trees, traffic lights, hydrants, bins, newspaper boxes, parking meters,
bus shelters, parked cars, traffic and people under umbrellas. A city at night is its lights and the
things that move; this is where both are.

A classic script after `world/city.js` (its plan). It defines one global, `WorldStreet`. The street
furniture is one merged mesh, the trees one more, the cars four instanced meshes for each of two
models, the people two: a little over twenty draw calls for every street, however many cars.

### `var PAINT`

Car colours as they are on real streets: mostly black, white, grey and silver, some dark blue, red
and green, a few yellow (taxis).

### `var REACH`

How far down the avenues the traffic drives before it turns, in the fog where the turn is not seen.

### `function car`

A car from three.js's own shapes: the body extruded from a side profile with wheel arches and
bevelled edges, the cabin from its own profile, roof and pillars, wheels with rims, bumpers, plates,
a grille, head and tail lights. A sedan and an SUV.

### `function shape`

The body narrows at the nose and tail and the cabin leans in towards the roof, as a car's does, and
then `WorldKit.smooth` shades it smooth where it curves and sharp at its creases.

### `function person`

A walker in a coat, its legs and one arm marked (`aLimb`) so the vertex shader can swing them, the
other arm up, holding an umbrella.

### `function umbrella`

The canopy, its underside and its stick.

### `function materials`

Car paint with a clear coat (`MeshPhysicalMaterial`), dark glass, trim, lamps (unlit, brighter at
night); people whose legs and arms swing as they walk, and who bob; umbrellas; street furniture;
the shelters' glass; the traffic lights, whose shader switches green, amber and red on a 30-second
cycle, the two directions half a cycle apart; and the light cones under the street lamps, the rain
lit in them, added to what is behind.

### `function segments`

Each side of each street between two crossings, stopping at the ring road.

### `function lampPost`

A street lamp every 24 m on both sides: a pole, an arm over the road and a head, sodium orange or LED
white, one in a few dozen failing. Each is one of the kit's lights, a halo and a cone.

### `function tree`

A street tree on the avenues: a pit, a trunk, two branches and a crown of leaf cards.

### `function put`

One of Poly Haven's scanned props (`WorldAssets`) at a spot, if it loaded and the spot is within reach
(110 m, 75 m on the `low` path; past that the fog has it). Says whether it did, so the caller can build
its own instead.

### `function facing`

The turn that faces a prop on the sidewalk towards the road.

### `function litter`

What collects beside a bin on a side street: one to three black bags and the odd cardboard box,
against the wall.

### `function backStreet`

The side streets' own things: an air-conditioning unit against a wall, and, at a few corners, a pair
of concrete barriers across the no-parking zone by the crossing.

### `function clutter`

What stands on a sidewalk: a hydrant, a bin, a newspaper box (half of them a utility cabinet) or a
parking meter, by seed. The hydrant, the bin and the cabinet are scans where they loaded, and the
bin on a side street gets its litter.

### `function signals`

A traffic light on each corner of a crossing: a pole, a mast arm over the road, a head facing the
oncoming traffic, its lamps tagged with their colour and their direction for the shader.

### `function tag`

The traffic-light attribute on a piece (a shelter's advertising light has none: it stays lit).

### `function shelter`

A bus shelter: posts, a roof, a bench, a glass back, and a lit advertising panel.

### `function loopPath`

The route a car drives: in along an avenue, a quarter of the way round the ring (the plaza on its
left, as on a roundabout where traffic drives on the right), out along the next avenue, and round in
the fog to come back in, through all four avenues. Two lanes, two loops. A third loop circles the
ring on its inside lane.

### `function measure`

A route's length along its points, to place a car by distance.

### `function along`

The point and heading a distance along a route.

### `function build`

The street for a plaza of radius `P`. What is far from where you can walk is left out: furniture past
150 m, trees past 160, lamps past 215 (their light is seen down the avenues), and parked cars past
120 m (none on the `low` path, nor people). One parked car in a dozen is under a cover (a scan). The
scans are instanced, one draw call per prop however many stand in the street, and share their
geometry across rebuilds (`userData.shared`, never disposed). Returns the footprints you walk round,
the lamps' lights, and how many cars, parked cars, people and scanned props there are.

### `function traffic`

The cars, spaced along their loops, each with its own top speed, and the parked cars along the side
streets' kerbs, each its own colour, their lights off.

### `function walkers`

People on the sidewalks, each with a pace, walking up and down their stretch of sidewalk.

### `function frame`

Every frame: a car keeps its distance from the one ahead and stops at a red light at the crossing
ahead, then drives on; its headlights light the road ahead of it and its tail lights the road behind
(the kit's moving lights). The people walk. Under reduced motion nothing moves.

### `function stopLine`

How far ahead is the stop line of the next crossing on an avenue, if there is one within 16 m.
