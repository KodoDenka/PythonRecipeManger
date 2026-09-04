# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project does

This is a data generation tool for a Minecraft mod ("knavesneeds"). It programmatically creates JSON files for crafting recipes, item models, weapon attributes, and recipe unlock advancements, and copies the matching item sprites out of `common/sprites/` — targeting both Fabric and Forge mod loaders.

Sprites are the single source of truth here: they live in `common/sprites/` and are exported into each loader's asset tree by the generator, rather than being copied into the downstream mod projects by hand.

## Running the generator

```
python main.py              # JSON + textures, about a second
python main.py --previews   # ...and the per-tier preview GIFs, minutes
python main.py --thumbnail  # ...and the mod thumbnail, seconds
python main.py --all        # everything
```

**Both render steps are opt-in, and separately so.** They cost minutes while the JSON and
textures — the part a mod build actually consumes — take about a second, so rebuilding 39
tiers of spin animation to change one recipe is a bad default. They are separate flags
because they answer different questions and neither implies the other: the thumbnail
advertises one mod, the previews document every tier with art.

Short forms `-p`, `-t`, `-a` work, as does `--preview`. Anything else is rejected with exit
2 rather than ignored, so a typo'd flag cannot silently give a run without the output it
asked for.

Because the two steps are independent, `preview/` is cleared selectively: a previews run
removes only the per-mod subfolders, a thumbnail run only the loose `thumbnail.*` files.
Clearing the whole folder either way would delete output the run has no intention of
rebuilding.

JSON and texture generation needs only the standard library (`json`, `os`, `shutil`, `time`). Preview GIF rendering additionally needs Pillow, and the 3D renderer needs numpy:

```
pip install -r requirements.txt
```

Both are imported lazily, and the run degrades in stages rather than failing: without numpy previews fall back to the 2D sprite renderer, and without Pillow the GIF step is skipped entirely with a warning. Every JSON file and texture is produced either way. The script clears and regenerates `fabric/` and `forge/` on every run, and `preview/` only on a run that is going to rebuild it — wiping previews the run then skips would leave the folder empty rather than stale, and a stale GIF is the better of the two. All three are gitignored.

## Architecture

Everything lives in `main.py`. The generation pipeline runs in this order:

1. **Keys** (`common/data/keys.json`) — loaded into a local dict mapping identifier → `[prefix, "namespace:identifier"]`.
2. **Tiers** (`common/data/tiers.json`) — loaded and resolved against the keys dict into the global `tiers` dict of `TierClass` instances. Each tier has a `mod_id`, plus resolved `material`, `handle`, and `binder` key tuples.
3. **Pattern loading** — reads `common/patterns/sword_patterns.json` into `SWORD_PATTERNS`. Each entry maps a weapon name to its 3-row crafting grid using `M` (material), `H` (handle), `B` (binder) placeholders.
4. **Recipe generation** (`create_recipe_data`) — iterates all tiers × all sword patterns and writes shaped crafting recipe JSONs. Binder key is only included if `B` appears in the pattern.
5. **Model generation** (`create_model_date`) — writes item model JSONs for both loaders.
6. **Weapon attributes** (`create_weapon_attributes_date`) — writes weapon attribute JSONs for both loaders.
7. **Unlock advancements** (`create_unlock_data`) — writes Fabric-only advancement JSONs for recipe unlocking.
8. **Textures** (`create_texture_data`) — copies each tier × weapon sprite from `common/sprites/` into both loaders, together with its `.png.mcmeta` where one exists. Tiers with no matching sprite are collected in `missing_sprites` and printed as a warning at the end of the run.
9. **Previews** (`create_preview_data` → `preview.py`, `--previews`) — renders one looping showcase animation per tier to `preview/{mod_id}/{tier}.{gif,webp}`.
10. **Thumbnail** (`create_thumbnail_data` → `preview.py`, `--thumbnail`) — renders the mod's showcase image to `preview/thumbnail.{gif,webp}`, from the tiers named in `common/data/thumbnail.json`.

Steps 1–8 are driven by `tiers.json`, because recipes, models and advancements need real item IDs. Steps 9–10 are driven by `discover_sprite_tiers()` walking `common/sprites/` instead, so a mod whose art has landed but whose recipes have not still gets a showcase GIF. Those are flagged `[art only, no recipes]` in the run output.

Both preview steps share `resolve_preview_runtime()`, which imports `preview.py` and settles on a renderer once so a missing dependency warns a single time rather than once per step.

`main.py` holds the JSON pipeline. `preview.py` is kept apart because it is the sole consumer of the optional Pillow dependency in that pipeline, and `render3d.py` because it is the only consumer of numpy. `spritegen.py` is not part of the pipeline at all — it is a sprite-authoring tool run by hand, and `main.py` does not import it.

## Preview GIFs

Each tier's GIF spins its weapons toward the camera. Each weapon owns one half turn — edge-on, through face-on, back to edge-on — and the next weapon takes over at the edge-on frame, where the weapon is a sliver and the cut is invisible. The held frame is face-on, showing the weapon as the game draws it in an inventory slot.

`PREVIEW_MODE` in `main.py` selects the renderer:

**`"3d"` (default, `render3d.py`)** rasterises the actual item models. Two mesh sources:

- Templates with an `elements` list — currently only `greathammer` — are read directly, including per-element rotation. This is the case the 2D renderer could not fake.
- The other 14 weapons are `minecraft:item/generated`, which has no geometry. `extrude_sprite()` reproduces what the game builds for them: a 1px-thick slab with the sprite on front and back and a wall quad at every silhouette boundary texel.

Either way the model's `display.gui` transform is applied, so weapons are sized the way the game sizes them. Hand-built models rely on this — greathammer is authored ~43 units across against the standard 16 and only fits once its 0.45 GUI scale is applied.

**`"2d"`** squashes the sprite horizontally by `|cos(angle)|`. Kept as the fallback when numpy is missing. It never mirrors past edge-on, since a flat sprite has no back face and a mirrored weapon reads as wrong rather than as rotated.

Things to know before changing any of this:

- **Sprite resolution is detail, not size.** Sprites are 16/32/48px by weapon type, but Minecraft maps every item texture onto the same 16×16 quad, so a 48px halberd is not three times the size of a 16px sai in game — it is the same size with finer pixels. The 3D renderer reflects this. The 2D fallback does not: it preserves sprite pixel dimensions and so overstates large-sprite weapons.
- **One scale per GIF.** `fit_scale()` computes a single pixel scale across every weapon in the tier, bounding the horizontal extent by `hypot(x, z)` since rotation sweeps each vertex through a circle. Per-weapon fitting would make every weapon fill the frame and destroy the honest size comparison.
- **Pillow merges consecutive identical frames on save**, so the hold frames collapse into one long-duration frame. A GIF reporting fewer frames than were generated is expected; total playback time is unchanged.
- `TEMPLATES_DIR` in `preview.py` points at a sibling checkout of the knavesneeds mod by absolute path, overridable with `KNAVESNEEDS_TEMPLATES`. It only resolves on one machine — see the TODO there about moving templates into this project the way sprites were. If the path is missing, every weapon falls back to sprite extrusion, which costs real geometry on greathammer only.
- Spin speed is `SPIN_FRAMES` alone; hold length is `HOLD_FRAMES * FRAME_MS` and is independent of it. Raising `FRAME_MS` would slow the spin but stretch the hold with it.
- **Animated sprites are split before anything else touches them.** `load_sprite()` reads a vertical frame strip and its `.png.mcmeta` into a frame list; loading the strip whole would extrude a twelve-frames-tall slab in the 3D path and squash a 1:12 sliver in the 2D one. A strip whose `.mcmeta` is missing is still detected from its dimensions, since item textures are square.
- **The texture advances on elapsed milliseconds, not on spin steps** (`weapon_timeline`), so a 2-tick material visibly runs faster than a 4-tick one instead of both playing at whatever speed the spin happens to be.
- **An animated weapon spends the hold as real frames rather than one long one.** Freezing the texture for the length of the hold stops the material moving at exactly the moment the preview has stopped to show it off. Total duration is unchanged — `HOLD_FRAMES` frames of `FRAME_MS` instead of one frame of `HOLD_FRAMES * FRAME_MS` — and still weapons keep the single-long-frame encoding.
- **3D geometry comes from the union of every frame's silhouette.** The mesh is built once per weapon and reused across the spin, so a treatment that adds texels the first frame does not have would otherwise have nowhere to draw them. Note that `build_quads` extrudes at alpha > 128, so `bloom` haloes (alpha well below that) get no geometry and do not appear in 3D previews.
- Each weapon restarts its material animation from frame 0, so the texture loop and the spin loop do not have to divide into each other. The discontinuity lands on the edge-on handoff, where the weapon is a sliver and the cut is already invisible.
- The thumbnail shares these builders and so animates too, but `_save_thumbnail_gif()`'s shared-palette trick leans on only a small rectangle changing between frames. An animated material changes much more of the frame, so thumbnails built from animated tiers will be materially larger than the ~1MB the still ones cost.
- `EASING` in `preview.py` shapes progress through the half turn so the weapon decelerates into the held frame instead of stopping dead. It only redistributes angles across existing frames, so it never changes the loop duration. Blended against linear rather than applied neat, since a pure cubic stalls at face-on and bunches frames there, silently lengthening the hold.
- `TILT` tilts the camera off the equator so top faces stay visible. `fit_scale()` must be given the same tilt or tall weapons clip, since tilting mixes depth into the vertical extent.
- The specular sweep (`SPEC_STRENGTH`, `SPEC_WIDTH` in `render3d.py`) follows `sin(2*spin)^2`, which is zero both edge-on and face-on. Face-on **must** stay zero: that is the frame the GIF holds, and a highlight peaking there would freeze mid-blade for the whole hold.
- `SPEC_STEPS` bands the highlight instead of letting it fall off smoothly. This is a file size control, not just a look: a smooth gradient spends the GIF's 255 colours on near-identical shades and compresses badly, costing ~75% more per file for no visible gain. Raise it only alongside a size check — it also keeps the busiest frame at ~228 colours, and pushing past 255 would start costing the GIF real colour.

## Mod thumbnail

`preview/thumbnail.{gif,webp}` is the mod's showcase image. It runs the same spin as the
per-tier previews with the two axes swapped: one weapon cycling through **every material**,
rather than one material cycling through every weapon. The logo from `common/sprites/LOGO.png`
is composited over every frame.

**The tier list is required, not discovered.** `common/data/thumbnail.json` names which
tiers the thumbnail may show:

```json
{ "weapon": "chakram", "tiers": ["arpg_core"] }
```

`common/sprites/` holds art for forty-odd tiers across a dozen upstream mods, and none of
those ship in the mod a thumbnail advertises — discovering the list from the sprite tree put
other people's materials in our showcase. A missing file, an empty `tiers` list, or a
selector that matches no sprite folder all exit 2, and they do so **before anything is
cleared or written**, so a thumbnail that was asked for and cannot be built fails with
nothing half-generated behind it.

A selector is either a mod id, meaning every tier of that mod, or `"mod_id/tier"` for one
tier exactly; a bare name that is not a mod id is matched against top-level tier folders,
which is how Blue Skies' woods and gems sit in the tree. Order is preserved, so the config
also sets the order materials appear in the loop.

`weapon` defaults to `THUMBNAIL_WEAPON` — chakram, because it is the roundest item in the
set, so its silhouette stays constant while the material changes underneath it and it still
reads at thumbnail size.

- **Wooden tiers are dropped when a selector expands a whole mod, never when a tier is
  named outright** — a wildcard gets curated, a name gets obeyed. `is_wooden_tier()` tests
  the tier's *material* item for a `_planks` suffix, not the tier name — `ironwood` is a
  metal and `turquoise_stone` is not stone-only, so neither the name nor its suffix is a
  usable signal. Blue Skies' seven wood sets are near-identical and would otherwise eat a
  quarter of the loop. `"include_wooden": true` turns the filter off.
- **The thumbnail spins faster** (`THUMB_SPIN_FRAMES`, `THUMB_HOLD_FRAMES`) because it has
  roughly twice as many entries as any tier has weapons. At the per-tier speed the loop would
  run past 40 seconds.
- **Its backdrop is opaque.** The logo's drop shadow is partial alpha, which the GIF path
  binarises away against a transparent frame, and a thumbnail lands on an unknown page
  background anyway. Keep it flat: the backdrop is most of the frame, and a gradient would be
  re-encoded on every one.
- **It has its own GIF saver.** Because the frames are opaque, `_save_thumbnail_gif()` uses
  disposal 1 and quantises every frame against one shared palette, which lets the encoder
  write only the rectangle that moved. That takes the file from ~2.5MB to under 1MB. Neither
  trick transfers to the per-tier previews, whose transparent frames need disposal 2. Note
  that passing `optimize=False` to Pillow's GIF save is *worse* than omitting it — it costs
  ~50% more — so leave it unset.
- The weapon is rendered at `CANVAS` and pasted into the larger `THUMB_CANVAS` square, so the
  bigger output costs compositing rather than rasterising. `THUMB_LIFT` raises it out of dead
  centre, since the logo claims the bottom of the frame.

## Drawn silhouettes

`forge.py` and `armoury.py` generate weapon geometry instead of borrowing it. This exists for
a reason beyond quality: every blank in `common/blanks/` is structure extracted from another
mod's sprites, so a set built only from those is a recolour of other people's art rather than
the mod's own. `spritegen.py` remains the right tool for reference and the wrong one for
shipping.

- **`forge.py` draws, `armoury.py` says what to draw.** The two change for different reasons —
  tuning how a bevel reads is a rendering decision, deciding a scythe's blade sweeps back over
  the haft is a design one.
- **One `Stroke` covers most of the vocabulary.** A katana's curved single edge, a scythe's
  sweep, a spear's straight haft and a warglaive's crescent are the same primitive with
  different control points and width profiles. That is what makes fifteen weapon types
  tractable without fifteen drawing routines.
- **Shading comes from the geometry, not from a source sprite.** Every primitive knows the
  signed across-distance of each texel, so the lit side of a blade is whichever side faces the
  light, however the blade curves.
- **Tone bands are hard steps, and there are three of them.** A blade is 3 texels wide at this
  canvas, so its pixel centres sample the across-coordinate at roughly -0.67, 0 and +0.67 — a
  fourth band above 0.62 is unreachable, which is why the first pass came out uniformly bright
  with no shadow side at all.
- **`outline()` skips texels below `floor`.** The band tables already put their darkest tone
  on the shadow side; outlining that texel too took a 3-wide blade down to two visible texels
  against a dark inventory slot.
- **Hafts sample higher on their ramp than blades do** (`HAFT_BANDS`). The handle ramp is
  already the darkest thing in a palette, so sampling its bottom end as well stacks two
  darkenings and the grip disappears.

### Style: what makes a tier recognisable by shape

A `Style` scales parts rather than replacing them, so one tier's fifteen weapons read as a
family while still differing from each other as much as they did. The furniture names are what
carry identity — guards (`cross`, `swept`, `ring`, `tsuba`, `winged`, `none`), pommels
(`disc`, `faceted`, `spike`, `ring`, `none`), grips (`plain`, `wrapped`, `ridged`) and edges
(`smooth`, `serrated`, `toothed`, `chipped`).

- **A blade says what the weapon is; the furniture says whose it is.** Furniture is chosen per
  tier, not per weapon, which is the whole point — a player who has seen one Cryalt weapon
  knows the next by its faceted pommel and chipped edge before the colour registers.
- **Grip wrap is the largest improvement available to a handle** at this resolution. A plain
  rod reads as a dowel however well it is shaded, because a real grip's texture is banding
  across it rather than shading along it.
- **Edge treatments cut inward, never outward.** A tooth growing past the silhouette changes
  the weapon's reach and its fitted preview scale; a notch cut into it does not. They also
  spare the first fifth of the blade, so the ricasso stays clean.
- **Only the cutting side is modulated.** Modulating the whole width makes a blade that
  pulses in thickness — a wavy weapon rather than a serrated one.

### Where forged blanks live

`common/blanks/forged.json`, merged over `blanks.json` by `load_index()`. Same split as the
palettes and for the same reason: `extract` rewrites `blanks.json` wholesale from the sprite
tree, and a drawn blank has no sprite to be re-derived from. They carry an empty `sources`
list, so `verify` correctly skips them — there is no ground truth to compare a drawing to.

Regenerate with `python armoury.py`.

- **`to_blank()` quantises positions to 24 steps.** The geometry produces continuous values;
  without quantising, a curve mints a fresh slot for nearly every texel and blows past
  `MAX_SLOTS`. Forged blanks land at 11-13 slots.
- **`_mostly_grip()` measures grip share by area, not by slot count.** Slot count only tracks
  area for extracted blanks, where every shade came from a comparable patch of hand-drawn art.
  A wrapped grip mints a distinct handle slot every few texels, so a greathammer that is 27%
  grip by area reads as half grip by slot count and gets rejected for a fault it does not
  have. Measured by area, `chakram/betternether_cincinnasite` is still correctly caught at 87%.

## Output formats

Each tier is written as both GIF and WebP from a single render pass — rasterising costs far more than encoding, so `create_preview()` builds the frames once and hands them to each saver in `FORMATS`. WebP is the better file at roughly half the bytes; GIF is kept as the fallback for anywhere WebP is unsupported.

Frame durations are stated explicitly rather than repeating the held frame. Repetition worked for GIF because Pillow's GIF encoder merges consecutive duplicates, but that is a GIF-specific optimisation the WebP encoder does not share and it would have written every duplicate out.

Note that Pillow's WebP *reader* does not expose per-frame durations — `info["duration"]` comes back empty regardless of what was written. To verify WebP timing, parse the container's `ANMF` chunks (bytes 12–14 of each chunk body are a 24-bit little-endian duration in ms) rather than trusting the reader.

## Output path conventions

- Blue Skies items use the namespace `blues_skies`; all others use `knavesneeds`.
- Blue Skies result items are `blue_skies:{tier}/{weapon}`; others are `knavesneeds:{mod_id}/{tier}/{weapon}`.
- Fabric conditions use `fabric:load_conditions` / `fabric:all_mods_loaded`; Forge uses `conditions` / `forge:mod_loaded`.
- Models and textures both use the singular `item` subfolder, set once as `ITEM_ROOT` in `main.py`. Every model `parent`, `layer0` reference, and output path derives from it, so the generated JSON and the files on disk cannot disagree.
- Textures always go to the `knavesneeds` namespace, even for Blue Skies tiers whose *models* live under `blues_skies` — the sprites ship with this mod regardless of which mod the tier comes from.
- An animated sprite is a vertical strip of frames plus a sibling `.png.mcmeta` naming the frame time. The two must travel together: without the `.mcmeta` the game has no reason to think the PNG is anything but one very tall texture, so the strip ships as a stretched still. `create_texture_data` copies the `.mcmeta` alongside the sprite for exactly that reason, and reports how many it moved.

## Sprite layout

`find_sprite()` accepts four layouts, checked in order, because the folders grew organically:

```
common/sprites/{mod_id}/{tier}/{tier}_{weapon}.png
common/sprites/{mod_id}/{tier}/{weapon}.png
common/sprites/{tier}/{tier}_{weapon}.png          # tier at top level (Blue Skies woods/gems)
common/sprites/{tier}/{weapon}.png
```

A sprite only exports as a **texture** if a tier in `tiers.json` references it, so adding art alone is not enough to make an item appear in game. **Preview GIFs** are the exception and cover every sprite folder found on disk.

Candidates are exact filenames built from the weapon name, and that is what filters variant art. Better End ships `*_head.png` alternates alongside its base sprites, and there are stray `*2.png` / `*3.png` drafts in several folders; none can ever match, because no weapon is named `chakram_head` or `claymore2`. Do not loosen this to a prefix or glob match without another way to exclude them.

The flip side is that art named for a different tier than its folder never resolves — `plus_the_end/prideful` holds `endronium_*2.png` files, so it produces nothing. Unresolved folders are listed at the end of a run rather than passing silently.

## Sprite templates and palette swapping

`spritegen.py` is a separate authoring tool, not part of the `python main.py` pipeline.
It exists to draw a **new** material without repainting fifteen sprites: extract the
structure of the existing art once, then recolour it.

```
python spritegen.py extract          # rebuild the blank library from common/sprites/
python spritegen.py list             # weapons, silhouettes, slot counts
python spritegen.py palettes         # the ramp each existing tier paints with
python spritegen.py generate <tier> --from <existing-tier>
python spritegen.py verify [n]       # how closely blanks reproduce the real art
```

It reads `common/sprites/` and never writes there. Generated sprites go to
`generated_sprites/` (gitignored) to be copied in by hand once a tier looks right; the
hand-drawn art stays the source of truth for every tier that already has it.

Two things are committed, and both are generated by `extract`:

- `common/blanks/{weapon}/{variant}.png` — the blanks. Neutral grey material shades over
  the shared wooden grip, so they read as weapons rather than silhouettes.
- `common/blanks/blanks.json` — the slot table. **This is what `render()` reads**, keyed by
  the exact colours in the PNG. Recolouring a blank by hand in an image editor breaks that
  lookup and `render()` raises rather than guessing.
- `common/data/palettes.json` — the ramp each of the 39 existing tiers paints with, usable
  directly as `--from` for a new tier.

### How the art actually decomposes

Measured, not assumed — re-run `verify` after changing any of this:

- **A tier is one material, not fifteen drawings.** `dusk_wood` paints its whole set from
  7 material shades and 4 grip shades; `starlit_wood` is the same drawing with a different
  7. That is why a palette is per tier and drives every weapon.
- **Slots store a ramp *position*, not an index.** A blank may carry 48 shades and still
  render from a 12-stop palette, because slots sample the ramp. Positions are places on
  the *tier's* pooled ramp, never normalised within one weapon — a 6-shade chakram must
  take 6 places on the same ramp an 11-shade longsword spreads across, or the two come out
  of the same palette looking like different metals.
- **Silhouette is the variant axis.** A palette cannot change an outline, so each distinct
  outline gets its own blank: `base` is the one most tiers share, the rest are named after
  a tier that draws them. Longsword has 17, chakram 8, greathammer 4.
- **`_representative()` picks the modal shade count**, not the first or the simplest tier.
  The alphabetically-first tier is often an anti-aliased repaint (`ametrine`) and bakes a
  40-slot structure into what should be an 11-slot blank; the simplest is often a tier
  whose palette repeated a colour, which bakes in a *missing* distinction.
- **The grip is identified by agreement across tiers**, not by name or position: 22 of the
  39 tiers draw the same wooden handle pixel-for-pixel, so a shade the tiers agree on is
  the grip and one they all differ on is the material. A tier owning a private silhouette
  has nobody to agree with, so `_learn_handles()` runs first and carries the answer over.
- **`ALPHA_FLOOR` discards near-invisible texels.** The art carries a few hundred stray
  alpha<32 pixels; each would otherwise become its own shade and land in every palette
  extracted from it. Real translucency (the `translucent` tier) is alpha 164+, so nothing
  intended is lost.
- **Ramps are capped at `MATERIAL_STOPS`/`HANDLE_STOPS`** because a palette is meant to be
  typed by hand. Pooling every weapon untrimmed gives a clean tier like `deorum` a 37-stop
  ramp, most of it greathammer's anti-aliasing. `MAX_SLOTS` is the separate, larger cap on
  a *blank's* detail.

`verify` reports a mean channel error around 25/255 across all 585 sprites, with each
blank's representative tier reproduced exactly. The rest is cross-application error —
applying one tier's palette to a blank another tier drew — and it is largest for
multi-hued tiers like `twilight_forest/fiery`, whose glow and steel sit at the same
luminance and so cannot be told apart by a single ramp. That error only measures how well
the blanks re-describe *existing* art; it does not bound anything about a new tier, which
has no ground truth to differ from.

Why a palette swap and not a tint: a tint multiplies one hue across the whole ramp, so it
can only produce a colour-shifted copy of the reference material, keeping its contrast
curve. Each shade is chosen independently here, which is what lets a bright yellow metal
and a dark low-contrast one both come out right.

### Two-tone palettes

A palette may carry a second ramp. `Palette.accent` takes over above `split` on the slot
position axis, with `blend` crossfading either side of the boundary, so one material can be
a dark body with a bright core. This needs **no change to the blanks** — it reinterprets
positions that were already there, and single-tone palettes (`accent: null`) render exactly
as before.

- **It cannot be extracted, only authored.** All 39 hand-drawn tiers are single-tone plus
  the shared grip; `extract` has never produced an accent and there is no art to learn one
  from. Two-tone entries are typed by hand.
- **The accent lands on whatever is *lit*, not on a named part.** Slot position is a rank on
  the tier's ramp, so `split` selects the brightest ~40% of the drawing, wherever that falls.
  Broad weapons get a lot of it (warglaive and claymore ~42% of texels at `split=0.62`) and
  thin ones very little (sai 13%, rapier 17%), so the same palette reads two-tone on a
  claymore and nearly single-tone on a sai.

### Surface treatments

A palette says what a material is made of; a treatment in `treatments.py` says what its
surface *does*. Colour alone runs out of distinctions well before twelve materials do, so
each `arpg_core` tier also declares an ordered `treatments` list, a grip ramp and a
silhouette map. Two tiers can share a hue family and still read as different substances.

A treatment receives a `Surface`: the rendered pixels plus, per pixel, the **family and
ramp position** the slot table shaded it from. That is what makes the effects structural.
`pulse` can brighten "the lit two thirds of the blade" because position already encodes
how lit a texel is, and `translucent` can spare the grip because family already
distinguishes it. Matching on output colour would break the moment two tiers shared a
shade.

Treatments compose in the order the tier lists them, each seeing the last one's output —
`bloom` after `pulse` haloes the swollen core, before it haloes the resting one, and both
are legitimate.

- **`_rand` needs its avalanche.** It is FNV followed by the murmur3 finaliser. FNV alone
  avalanches badly on keys as small and correlated as pixel coordinates: it returned
  0.33–0.94 with adjacent texels differing in the fourth decimal, so every treatment that
  thresholds against a density below 0.33 — `noise`, `sparkle`, `pit` — matched nothing at
  all and silently did nothing. It is deterministic on purpose, so a speck lands in the
  same place on every run and on every machine; art that moves under a regenerate cannot
  be hand-fixed afterwards.
- **`etch` scales its period with the canvas.** A fixed pixel period puts twice as many
  rungs on a 32px blank as on a 16px one, reading as inlay on one and a screen door on the
  other.
- **`facet` quantises the position, not the colour.** On a two-tone palette, quantising
  colour bands body and accent separately and leaves the split visible as a seam.
- **`bloom` only writes into transparent pixels**, so a sprite that already fills its frame
  is a no-op rather than a clipped rectangle. A halo is how a 16px sprite says emissive;
  there is no room for one inside the silhouette.

### Animated tiers

`frames > 1` renders the strip Minecraft wants: every frame stacked vertically into one
PNG with a `.png.mcmeta` beside it naming the frame time in ticks. That is the shippable
format, not a preview. `generate(..., preview=True)` additionally writes a GIF per animated
weapon, which the game never reads and a person browsing the folder does.

### Grips and silhouettes

- **A tier that omits `handle` inherits the same wooden grip as every other tier.** All
  twelve `arpg_core` materials did at first, which made every scythe shaft in the set
  identical — the largest block of shared pixels in the whole thing. Two-tone tiers now
  take a machined gunmetal or charcoal grip and single-tone ones a dark grip tinted from
  their own ramp.
- **`weapon_split` exists because the accent lands on whatever is lit.** See the two-tone
  section: one flat split gives a warglaive 42% accent and a sai 13%.
- **`variants` maps weapon → blank variant, falling back to `base`.** Falling back beats
  skipping — a tier missing three of its fifteen weapons is a broken item set, one wearing
  the base silhouette for three of them is merely less distinctive. No non-base variant
  covers all fifteen weapons (greathammer exists in only two, warglaive in few), so a tier
  declares a priority chain and the builder resolves it per weapon.
- **Some blanks are mostly grip and must not be used as variants.**
  `chakram/betternether_cincinnasite` has 80% handle-family slots against base's 0% — that
  tier drew the disc in colours the other tiers agreed on, so `_learn_handles` claimed it.
  It renders entirely from the handle ramp and ignores the material. `_mostly_grip()`
  catches this against the same weapon's base blank rather than an absolute threshold,
  since a spear is legitimately half shaft.

### Hand-authored palettes

`common/data/palettes_custom.json` holds palettes written by hand; `load_palettes()` reads it
over the top of `palettes.json`. It is a separate file because `extract` **rewrites
`palettes.json` wholesale**, so anything hand-typed in there is destroyed on the next run.

It currently holds the twelve `arpg_core/*` materials, which are the point of the project —
the 39 extracted tiers are reference art for building them.

### Picking a blank's representative tier

`_representative()` chooses which tier's drawing becomes the blank, by modal shade count with
a **median-brightness tie-break**. The tie-break is load-bearing, not tidiness: picking the
alphabetically-first tier of a tie made `amethyst_imbuement/glowing` — mean lit luminance
0.947 against the group's 0.538 — the source for every chakram blank, and every generated
chakram came out 27% brighter than the art it was meant to reproduce. Choosing the tier
nearest the median brings it inside 1%.

## Extending the project

**Add a new weapon type**: add an entry to `common/patterns/sword_patterns.json` with a 3×3 pattern using `M`, `H`, `B` placeholders (use spaces for empty cells). No Python changes needed.

**Draw a new tier's sprites**: write a material ramp and run `python spritegen.py generate <tier> --from <existing-tier>`, or pass a hand-written `Palette` — see the palette-swapping section above. Copy the result out of `generated_sprites/` into `common/sprites/`; nothing generates into the sprite tree automatically.

**Add a new mod/material tier**: add the mod's items to `common/data/keys.json`, then add entries to `common/data/tiers.json` referencing those key names, and drop the sprites into `common/sprites/` in one of the layouts above. No Python changes needed for standard tiers. Run `python main.py` and check the warning block — it lists any tier × weapon whose sprite could not be found.

**Add a new supported mod with a custom namespace**: add items to `common/data/keys.json`, add tiers to `common/data/tiers.json`, then update `get_result_item()` and the `namespace` local variable in each `create_*` function if the mod needs non-default namespace/path conventions (Blue Skies is the existing example).