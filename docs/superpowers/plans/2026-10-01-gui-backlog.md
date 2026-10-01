# GUI backlog: requested, not designed or built

Planning notes from user requests on 2026-10-01. **All four items were
implemented on 2026-10-01** (see the spec amendments in §7, §8, §12, §13.6,
§13.7 and §15). The notes below are kept as the design record; where the build
differs, the spec wins. Not built: Option B (globe view) of the ground item.

## 3D trajectory card: camera modes (implemented 2026-10-01)

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

## 3D trajectory card: ground beyond the map tiles (Option A implemented 2026-10-01)

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

## Plot event markers: readability (implemented 2026-10-01)

User report: event marker labels overlap when two events are close in time,
and markers default to the same colour as the line they mark, so they are hard
to see. Fix ideas: stagger or collision-avoid labels (or collapse close events
into one label with a count), and draw markers in a contrasting colour or
with an outline/halo rather than the series colour.

## Camera card: demo flight video, synced to launch (implemented 2026-10-01)

Built as camera `mode: demo`; see spec §15 and `tools/README.md`.

- **Default clip:** `.sdr/media/l3_flight_onboard.mp4`, "L3 Flight" by kjmath
  (YouTube `tfCgWSBuRZg`, embedded on
  [the flyer's L3 write-up](https://kjmath.github.io/portfolio/projects/L3-rocket/)):
  an amateur NAR Level 3 certification flight, expected apogee about 8,090 ft,
  aft-looking camera in a 3D-printed aeroshell. 163 s, 640×360 H.264, about
  0.7 Mb/s. Liftoff (first motor plume) is at 9.0 s; the igniter flickers at
  8.4 s. Fetched with `yt-dlp` (YouTube's `mweb` client, format 18); it is under
  standard YouTube terms, so it is for in-group proof-of-concept demos only and
  is never committed. Chosen over the first clip because IREC rockets fly to
  about 10,000 ft, not 178 miles.
- **Earlier clip:** NASA "Riding on a Sounding Rocket" (public domain,
  [Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Riding_on_a_Sounding_Rocket.webm)),
  liftoff at about 30.6 s in the local `sounding_rocket_onboard.mp4`. It still
  works by setting the card's clip and liftoff fields.
- **Loop length:** the demo replay gives about 68 s from LAUNCH to
  `flight_reset`, so each loop shows liftoff and the first minute of the clip.
