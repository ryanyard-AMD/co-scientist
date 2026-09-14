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
| `ring_radius` | 0.10..2.00 m | Absolute floor. The binding constraint is the clearance rule below. |
| `pitch` | 0.005..0.10 m | 5 mm is physical element collision; 100 mm is deep grating-lobe territory. |
| `zone_half_extent` | 0.02..0.40 m | Under 2 cm is sub-head; over 40 cm is not a personal zone. |
| `t60` | 0..2.0 s | 0 is the anechoic bound; over 2 s the image-source truncation is no longer valid. |
| `carrier` | 20..80 kHz | Usable PAL ultrasonic carrier band. |
| `aperture` | 0.002..0.05 m | Sets the Berktay beamwidth. |
| `sidelobe_floor` | 0.001..0.5 | 0.056 (−25 dB) is what real PAL hardware measures. |
| `nearfield_length` | 0..3.0 m | 0 disables the near-field taper. |

### Ring clearance, and why contrast can't pick the radius

The simulator centres a `ring` on the listener, so `ring_radius` is the distance from
every module to the bright-zone **centre**. The zone is a cube, so its corners reach
`sqrt(3) × zone_half_extent`; a ring inside that radius is sitting in the volume it is
supposed to be illuminating. `_clear_ring` therefore clamps

```
ring_radius >= sqrt(3) * zone_half_extent + aperture     # 0.166 m at defaults
```

This matters because **acoustic contrast is monotone in `ring_radius`** — shrinking the
ring moves the sources toward the listener's head, so bright-zone energy climbs as 1/r²
while the dark zone stays put. Measured on a 16-element ring at 60 cm zone separation,
`t60` 0.4:

| `ring_radius` | 0.30 | 0.20 | 0.15 | 0.12 | 0.10 |
|---|---|---|---|---|---|
| contrast (dB) | 49.70 | 53.99 | 63.55 | 66.91 | 67.39 |

The number keeps rising with no improvement in zone *control*, so an unconstrained
sweep converges on headphones rather than a periphery array. The clearance rule stops
the physically absurd end of that range; it does not make contrast a valid objective for
this knob. **Fix `ring_radius` from the use case** — a tabletop deployment is ~0.3 m —
and sweep the knobs that trade off against something.

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

## Where the geometry shows up

- **`compare`** adds `layout`, `n_elements`, `listener_distance_m`, `zone_separation_m`,
  `predicted_contrast_db` and `meets_target`. Each row is built by re-resolving the card
  and re-applying the overrides the last simulate carried — **not** by reading
  `simulation["resolved_geometry"]`, whose keys repro renames on the way out
  (`listener_m`, `cap_radius_m`, `freqs_hz`). An unsimulated card shows `—`.
- **`export_device`** gains a `## Resolved Geometry` section — every knob, the
  `design_intent`, and a `> Clamped:` callout per record — and a
  `## Predicted Performance` section once the card has been simulated. The JSON format
  carries the same block under `resolved_geometry`. This is the buildable spec.
- **The roadmap agent** sees `listener_m`, `zone_separation_m`, `t60_s` and `pal_model`
  alongside the contrast number, so it can tell a 25 dB result at 40 cm separation in an
  anechoic room from the same number at 1.1 m in a reverberant one.
- **`cs device simulate`** prints a yellow `clamped` row when the card carries clamp
  records, so an envelope edit is visible at the moment you are refining.

## Upgrading a legacy card

A card written before the `geometry` column carries `{}` and resolves entirely off the
prose scrape — three knobs inferred, fifteen defaulted. `set-geometry` is how it stops
being stuck there:

```bash
# See what it currently resolves to.
cs device export <DEVICE_ID> <GOAL_ID> | sed -n '/## Resolved Geometry/,/^##/p'

# Commit the card to a physical design instead of the defaults.
cs device set-geometry <DEVICE_ID> <GOAL_ID> \
    --set layout=ring --set ring_radius=0.5 --set n_elements=20 \
    --set listener=0,1.2,0 --set dark=1.1,1.2,0 --set t60=0.6

# No --set flags needed: the block is on the card now.
cs device simulate <DEVICE_ID> <GOAL_ID>
```

Each `--set` is merged onto whatever is already there, so a one-knob tweak does not wipe
the rest; `--replace` starts from an empty block. Values are clamped exactly as an agent
proposal would be, and the CLI prints a yellow `clamped` row for anything the envelope
moved. `positions`/`normals` are rejected here — a card commits to a `layout`, and
explicit coordinates stay a simulate-time override.

## Caveat: `generate` is not idempotent

Re-running `cs device generate` creates new cards; a hand-tuned geometry block on an
existing card is not carried over. That is true of every field on the card, but it is
more costly now that the block drives the simulation.
