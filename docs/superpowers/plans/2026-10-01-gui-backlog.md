# GUI backlog: requested, not designed or built

Planning notes from user requests on 2026-10-01. Nothing here is implemented.
Each item needs a short design pass (and spec amendment where noted) before
code. Keep within the dependency list in `AGENTS.md`.

## 3D trajectory card: camera modes

Today the card (`tools/sdr_web/src/cards/Trajectory3dCard.svelte`) has a fixed
start pose (`camera.position (-2500, 1800, 3500)`, target `(0, 400, 0)`) and
free `OrbitControls`. Requested additions:

1. **Follow (framed, tangential).** Keep the whole flight line in view as it
   grows, viewed side-on so the shape of the arc reads.
   - Framing: bounding sphere of the drawn track points (after vertical
     exaggeration); distance = `r / sin(fov/2)` times a margin, target at the
     sphere centre. Ease toward the new pose each frame rather than jumping.
   - Tangential direction: look perpendicular to the dominant horizontal
     direction of the track (pad-to-current ground vector, or the principal
     axis of the ground track). Add hysteresis so the camera does not flip
     sides as the track bends.
   - Edge case: a near-vertical flight has no meaningful horizontal direction.
     Below a drift threshold, keep the last azimuth (or a configured default).
   - Any user drag/zoom drops to free mode until the mode is re-selected.
2. **Orbit (framed).** Same framing, with the azimuth advancing slowly
   (a few degrees per second) around the track centre. User input pauses it.
3. Card config: a `camera` field (`free` | `follow` | `orbit`) plus the orbit
   rate. It needs a card-types/spec amendment and loader validation like the
   other card fields.

## 3D trajectory card: ground beyond the map tiles

Today the ground is one plane of z15 tiles covering ±4 km around the pad
(`groundTiles(pad, 15, 4)` in `lib/cards/traj.ts`). Zooming out shows its
edge against a blank background.

- **Option A (recommended): extend and fade.**
  - Lay a much larger, lower plane under the z15 plane using the coarser
    outer-zoom tiles that `./sdr maps fetch` already caches (`OUTER_ZOOMS`
    5–13 in `tools/sdr_cli/maps.py`). Where no tile exists, fill with the
    average colour of the z15 canvas border.
  - Add `scene.fog` and a scene background in that same averaged colour, so
    the ground fades into the horizon instead of a hard edge (the "YouTube
    ambient mode" look). A radial alpha falloff on the outer plane softens it
    further.
  - No new dependency; works offline with the existing tile cache.
- **Option B: globe view (SpaceX-style).**
  - Possible with a textured three.js sphere using low-zoom tiles, but at
    IREC scale (apogee around 3 km, drift of a few km) the trajectory is
    sub-pixel from any altitude where the globe's curvature shows. Over 10 km
    the Earth drops only about 8 m.
  - Most useful as a short "fly-in from orbit" intro that settles on the
    local view, not as the working view.
  - A full Earth engine (e.g. CesiumJS) would be a new dependency, which
    `AGENTS.md` does not allow without approval. It also wants online terrain
    data.
  - Suggest A first, B later only as an optional intro.

## Plot event markers: readability

User report: event marker labels overlap when two events are close in time,
and markers default to the same colour as the line they mark, so they are hard
to see. Fix ideas: stagger or collision-avoid labels (or collapse close events
into one label with a count), and draw markers in a contrasting colour or
with an outline/halo rather than the series colour.

## Camera card: demo flight video, synced to launch

Wanted: a demo video that plays in the camera card, roughly synced so liftoff
in the video lines up with the LAUNCH event. The real camera (analog FPV) is
later work and does not go through the FPGA.

- Candidate footage: NASA "Riding on a Sounding Rocket" (public domain,
  [Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Riding_on_a_Sounding_Rocket.webm)),
  liftoff about 20.5 s into the file. A local H.264 copy lives in the ignored
  `.sdr/media/` directory, not in the repository.
- Needed: an aiohttp route serving files from `.sdr/media/`, a card setting
  for the launch offset, and card logic that holds the pad frame until LAUNCH,
  then plays from offset + time since launch. This changes the camera card's
  spec (it currently only embeds an http(s) URL and plays immediately).
