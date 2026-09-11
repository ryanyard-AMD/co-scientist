# Device Geometry

A `DeviceConceptCard` describes an architecture in prose. The `geometry` block on
that card is the numeric spec that actually gets simulated — the payload
co-scientist sends to repro's `POST /api/v1/device-sim`. Its field names mirror
repro's `DeviceGeometryRequest` exactly.

Before this block existed, `_resolve_geometry` scraped three values out of the
card's prose (layout, element count, listener distance) and hardcoded the other
fourteen. Every candidate therefore simulated as the same canonical device with
three knobs jiggled, which made `compare` and `optimize` compare near-identical
things. The block exists so candidates can differ physically.

## Coordinate frame

Metres. The array face sits at the local origin and its boresight points along
`+y`. `x` is lateral, `z` is vertical.

- A listener at `[0, 0.6, 0]` is 60 cm straight ahead of the array.
- A dark zone at `[0.4, 0.6, 0]` is a second person 40 cm to the side, same distance.

## The knobs

| Knob | Unit | What it buys |
|---|---|---|
| `layout` | — | `cap` \| `planar` \| `ula` \| `ring`. Array topology (see below). |
| `n_elements` | count | Degrees of freedom for the contrast solver; the dominant cost, power and calibration driver of the real build. |
| `pitch` | m | Element spacing for `ula`/`planar`. Above half a wavelength at the top band edge (~21 mm at 8 kHz) grating lobes appear. |
| `cap_radius` | m | Sphere radius for `cap`. Smaller = tighter curvature = wider angular splay for the same element count. |
| `cap_deg` | deg | Cap half-angle. 5 is effectively flat; 80 wraps the outer elements nearly sideways. |
| `ring_radius` | m | Radius of the ring of modules around the listener. |
| `listener` | m `[x,y,z]` | Centre of the bright zone. `y` is the boresight distance — the single most consequential number on the card. |
| `dark` | m `[x,y,z]` | Centre of the zone to keep quiet. Its offset from `listener` is the separation the device must achieve. |
| `zone_half_extent` | m | Half-width of each cubic zone. 0.09 is roughly one head; larger means holding contrast over a moving listener. |
| `freqs` | Hz | 1–8 audio frequencies to evaluate. PAL devices are weakest at the low end. |
| `room_dims` | m `[Lx,Ly,Lz]` | Enclosing room. |
| `t60` | s | Reverberation time. 0 is the anechoic bound, 0.4 a small treated office, 0.8+ a hard room where reflections wreck contrast. |
| `array_origin` | m `[x,y,z]` | Where the array sits, if not the origin. |
| `pal_model` | bool | `true` = parametric-array (ultrasonic, self-demodulating) loudspeaker; `false` = conventional direct-radiating drivers. Changes the physics, not just a constant. |
| `carrier` | Hz | PAL ultrasonic carrier. 40 kHz is typical. |
| `aperture` | m | PAL element aperture radius. Larger narrows the demodulated beam (more contrast) but makes each element physically bigger, constraining `pitch`. |
| `sidelobe_floor` | ratio | Off-axis amplitude floor. 0.056 (−25 dB) is what real PAL hardware measures. |
| `nearfield_length` | m | Berktay beam-formation length — the distance over which the demodulated beam narrows. 0 disables the taper. |

Plus two non-simulated fields: `design_intent` (one sentence naming the physical
trade this geometry makes) and `clamped` (see below).

### Layouts

- **`ula`** — one horizontal line of elements, all facing `+y`. Cheapest to build;
  azimuth steering only.
- **`planar`** — square grid in the x–z plane, all facing `+y`. Adds elevation
  control at the cost of element count.
- **`cap`** — elements on a spherical cap opening toward `+y`, each facing radially
  outward so they splay off boresight. Buys angular diversity inside a compact
  aperture.
- **`ring`** — modules on a horizontal ring centred on the listener, each aimed
  inward. Diversity comes from azimuthal separation rather than one aperture — the
  tabletop or room-periphery deployment. `ring_radius` and `listener` interact: the
  ring is built around the listener point.

### Not in the block

`positions` and `normals` (explicit per-element coordinates) are deliberately
excluded. An LLM authoring 32×3 float lists burns output tokens against the
`max_tokens` truncation guard and says nothing a `layout` doesn't. They remain
reachable as simulate-time overrides.

## Resolution order

`_resolve_geometry` merges four layers, later winning:

1. **Simulator defaults** — `_default_geometry()`.
2. **Prose inference** — `_legacy_geometry()`, reading layout/element count from
   `hardware.speakers` and boresight distance from `form_factor.listener_distance_cm`.
   This layer is frozen: cards written before the `geometry` column depend on
   resolving exactly as they always have. A card with `geometry = {}` is unchanged.
3. **The card's geometry block** — `_card_geometry()`, only the knobs it actually set.
4. **Per-run overrides** — `_apply_overrides()` at the call site.

When layer 3 moves the `listener` without saying where the dark zone went, the dark
zone follows at the same 40 cm lateral offset — otherwise it would stay pinned at
layer 2's boresight distance.

## The envelope, and when it is applied

`GEOMETRY_BOUNDS` in `services/device.py` records what repro's simulator can
meaningfully handle, with the physical reason for each bound:

| Knob | Range | Why |
|---|---|---|
| `n_elements` | 4..64 | Under 4 there are too few DOF to steer; over 64 the image-source room build dominates runtime. |
| `cap_radius` | 0.03..0.60 m | Under 3 cm cannot hold elements; over 60 cm stops being a device. |
| `cap_deg` | 5..80° | Under 5° degenerates to planar; over 80° the outer elements face away from the listener. |
| `ring_radius` | 0.10..2.00 m | Modules must sit outside the listener zone and inside the room. |
| `pitch` | 0.005..0.10 m | 5 mm is physical element collision; 100 mm is deep grating-lobe territory. |
| `zone_half_extent` | 0.02..0.40 m | Under 2 cm is sub-head; over 40 cm is not a personal zone. |
| `t60` | 0..2.0 s | 0 is the anechoic bound; over 2 s the image-source truncation is no longer valid. |
| `carrier` | 20..80 kHz | Usable PAL ultrasonic carrier band. |
| `aperture` | 0.002..0.05 m | Sets the Berktay beamwidth. |
| `sidelobe_floor` | 0.001..0.5 | 0.056 (−25 dB) is what real PAL hardware measures. |
| `nearfield_length` | 0..3.0 m | 0 disables the near-field taper. |

`freqs` are normalised to 1–8 values in 100 Hz..20 kHz (deduped, sorted).
`room_dims` components clamp to 1..20 m. Vector knobs must be three finite numbers
or they are dropped. An unrecognised `layout` is mapped through `_infer_layout` to
the nearest simulator topology. If the bright and dark cubes overlap, the dark zone
is pushed out along its largest-separation axis — contrast is physically undefined
for overlapping zones.

**Clamping applies on persistence only** — in `generate` and in `set_geometry`. Every
adjustment is recorded as a `GeometryClamp` (`key`, `proposed`, `applied`, `bound`,
`reason`) on the block's `clamped` list, so an envelope edit is visible rather than
silent.

`_resolve_geometry` does **not** re-clamp on read. Re-clamping would let the stored
`clamped` record drift out of sync with the geometry that is actually simulated.

**Simulate-time overrides are never clamped.** `_apply_overrides` still rejects keys
outside the allowlist so a typo can't silently no-op, but a human asking for
`n_elements=128` or `t60=3.0` is deliberately probing outside the envelope. That is
the escape hatch; repro will reject genuinely invalid values itself.

If sweeps start timing out at the top of the `n_elements` range, lower the ceiling
rather than raising `repro_client_timeout` — that is the clamp doing its job.

## Caveat: `generate` is not idempotent

Re-running `cs device generate` creates new cards; a hand-tuned geometry block on an
existing card is not carried over. That is true of every field on the card, but it is
more costly now that the block drives the simulation.
