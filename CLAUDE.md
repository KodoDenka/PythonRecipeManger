# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project does

This is a data generation tool for a Minecraft mod ("knavesneeds"). It programmatically creates JSON files for crafting recipes, item models, weapon attributes, and recipe unlock advancements, and copies the matching item sprites out of `common/sprites/` — targeting both mod loaders of whichever Minecraft version is selected.

Sprites are the single source of truth here: they live in `common/sprites/` and are exported into each loader's asset tree by the generator, rather than being copied into the downstream mod projects by hand.

There are four entry points, and only the first is part of the generation pipeline:

- `main.py` — the generator. Stdlib-only, and importable without side effects.
- `python -m gui` — a PySide6 editor for the tier, key and pattern data, which shells out to `main.py` to generate. Needs PySide6; nothing else does.
- `spritegen.py` — a hand-run sprite authoring tool, described near the end of this file.
- `sheetgen.py` — a hand-run contact-sheet tool for showing the art to people, described under "Tier sheets".

## Running the generator

```
python main.py                       # 1.21.1 JSON + textures into ./fabric and ./neoforge
python main.py --mc 1.20.1           # ...the 1.20.1 profile instead (./fabric, ./forge)
python main.py --mc 1.21.1 <path>    # ...into a multiloader mod project root
python main.py --previews            # ...and the per-tier preview GIFs, minutes
python main.py --thumbnail           # ...and the mod thumbnail, seconds
python main.py --all                 # everything
```

`--mc` (`-m`, or `--mc=<version>`) picks the Minecraft version; it defaults to `1.21.1`, and the known versions are the keys of `VERSION_PROFILES` in `main.py`. The GUI reads that dict to fill its version selector, so adding a version there offers it in both places at once.

A bare path argument is the **multiloader mod project root** to generate into, and output lands in `<root>/<loader>/src/main/resources/`. Omit it and the run stages into the local `./<loader>` folders instead, which is the safe default: those are gitignored scratch space that holds nothing but generated files. `.env` holds a saved path per version as `MOD_PATH_<version with dots as underscores>` — see `.env.example` — which is what the GUI's output-path box reads and writes. `main.py` itself does not read `.env`; the GUI passes the path on the command line.

**Both render steps are opt-in, and separately so.** They cost minutes while the JSON and
textures — the part a mod build actually consumes — take about a second, so rebuilding 39
tiers of spin animation to change one recipe is a bad default. They are separate flags
because they answer different questions and neither implies the other: the thumbnail
advertises one mod, the previews document every tier with art.

Short forms `-p`, `-t`, `-a` work, as does `--preview`. Anything else is rejected with exit
2 rather than ignored, so a typo'd flag cannot silently give a run without the output it
asked for — and, now that a run can write into a real mod checkout, cannot silently give a
run that writes somewhere other than where it was pointed. An unknown `--mc` version, a
missing `--mc` value, an output root that does not exist, and a second bare path argument
are all exit 2 as well.

Because the two steps are independent, `preview/` is cleared selectively: a previews run
removes only the per-mod subfolders, a thumbnail run only the loose `thumbnail.*` files.
Clearing the whole folder either way would delete output the run has no intention of
rebuilding.

JSON and texture generation needs only the standard library (`json`, `os`, `shutil`, `time`). Preview GIF rendering additionally needs Pillow, and the 3D renderer needs numpy:

```
pip install -r requirements.txt
```

Both are imported lazily, and the run degrades in stages rather than failing: without numpy previews fall back to the 2D sprite renderer, and without Pillow the GIF step is skipped entirely with a warning. Every JSON file and texture is produced either way. PySide6 is needed only by `python -m gui`; the generator never imports Qt.

**How the previous run's output is cleared depends on where it went**, and the two cases are not the same risk:

- **Staging locally** (no path argument), `./<loader>` is emptied wholesale. Those folders hold nothing but generated files, and that is what drops a tier you have since deleted from `tiers.json`. The loader folders are the *current profile's* — a 1.21.1 run does not touch a `./forge` left behind by a 1.20.1 one. All of `./fabric`, `./forge`, `./neoforge` and `preview/` are gitignored.
- **Writing into a mod project**, it cannot: those trees also hold the hand-written lang files, item model templates and loader metadata the mod is built from. So the run deletes per tier instead, walking only the directories `generated_dirs()` names and leaving everything else alone.

The rule that makes the scoped clear safe is **clear exactly what you are about to write**. `generated_dirs()` therefore omits the recipe folder of a tier the run generates no recipe for, so the hand-written smithing and ritual recipes described under "Tiers that are not crafted" survive a run. The cost of scoping is that a tier *removed* from `tiers.json` is no longer cleaned out of a mod project, because nothing left in the data still names it.

## Architecture

The generator lives in `main.py`. The generation pipeline runs in this order, and every step from 1 to 9 is scoped to the version `--mc` selected:

1. **Mods** (`common/data/<version>/mods.json`) — loaded into the global `mods` dict of `ModClass` instances, one per upstream mod: its data pack `namespace`, the `loaders` it has a build for, and its `loaded_id`. Then **crafting rules** (`parts.json`, `smithing.json`, `rituals.json`, all optional) — see "Tiers that are not crafted".
2. **Keys** (`common/data/<version>/keys.json`) — loaded into a local dict mapping identifier → `[prefix, "namespace:identifier"]`.
3. **Tiers** (`common/data/<version>/tiers.json`) — loaded and resolved against the keys dict into the global `tiers` dict of `TierClass` instances. Each tier has a `mod_id`, plus resolved `material`, `handle`, and `binder` key tuples, and an optional `invisible_variant` flag.
4. **Pattern loading** — reads `common/patterns/<version>/sword_patterns.json` into `SWORD_PATTERNS`, and the optional `tier_patterns.json` into `TIER_PATTERNS`. Each base entry maps a weapon name to its 3-row crafting grid using `M` (material), `H` (handle), `B` (binder) placeholders; an override replaces that grid for one tier's weapon, letting a tier add or drop a binder without forking the whole pattern set.
5. **Recipe generation** (`create_recipe_data`) — iterates all tiers × all sword patterns and writes shaped crafting recipe JSONs, once per loader the tier's mod actually ships on. Binder key is only included if `B` appears in the resolved pattern.
6. **Model generation** (`create_model_date`) — writes item model JSONs. A tier flagged `invisible_variant` gets a second `_invisible` model and an `overrides` block on the first.
7. **Weapon attributes** (`create_weapon_attributes_date`) — writes weapon attribute JSONs.
8. **Unlock advancements** (`create_unlock_data`) — writes the advancement JSONs that unlock each recipe, per loader.
9. **Textures** (`create_texture_data`) — copies each tier × weapon sprite from `common/sprites/` into each of the mod's loaders, together with its `.png.mcmeta` where one exists. Tiers with no matching sprite are collected in `missing_sprites` and printed as a warning at the end of the run.
10. **Previews** (`create_preview_data` → `preview.py`, `--previews`) — renders one looping showcase animation per tier to `preview/{mod_id}/{tier}.{gif,webp}`.
11. **Thumbnail** (`create_thumbnail_data` → `preview.py`, `--thumbnail`) — renders the mod's showcase image to `preview/thumbnail.{gif,webp}`, from the tiers named in `common/data/thumbnail.json`.

Steps 5 to 9 all write only to the loaders in `mod_loaders()`, the intersection of the version's loaders and the mod's own. Blue Skies has no Fabric build, so generating Fabric recipes for it ships files that can never load — and on 1.21.1 would create a `blue_skies` namespace in the Fabric jar that exists nowhere else.

Steps 1–9 are driven by `tiers.json`, because recipes, models and advancements need real item IDs, and are therefore per version. Steps 10–11 are driven by `discover_sprite_tiers()` walking `common/sprites/` instead, so a mod whose art has landed but whose recipes have not still gets a showcase GIF. Those are flagged `[art only, no recipes]` in the run output. Being sprite-driven, they are also the same for every version — `preview/` and `common/data/thumbnail.json` are not versioned, because the art is not.

The three packages beside the generator are not part of that pipeline. `core/` is a stdlib-only data layer over the same JSON files (plus `.env`), `catalog/` reads item ids and icons out of installed mod jars into `.cache/`, and `gui/` is the PySide6 editor built on both. The dependency runs one way: `gui/` imports `main.py` — for `VERSION_PROFILES`, and to run it as a subprocess — and `main.py` imports none of them.

Both preview steps share `resolve_preview_runtime()`, which imports `preview.py` and settles on a renderer once so a missing dependency warns a single time rather than once per step.

`main.py` holds the JSON pipeline. `preview.py` is kept apart because it is the sole consumer of the optional Pillow dependency in that pipeline, and `render3d.py` because it is the only consumer of numpy. `spritegen.py` is not part of the pipeline at all — it is a sprite-authoring tool run by hand, and `main.py` does not import it.

## Minecraft versions

A version is a `VersionProfile` in `main.py` plus a folder of data under `common/data/<version>/`
and `common/patterns/<version>/`. Every field of the profile is something that changed between
1.20.1 and 1.21.1, and **each was read off the corresponding mod repo rather than inferred**,
because getting one wrong produces files the game loads without complaint and then silently
ignores.

| | 1.20.1 | 1.21.1 |
|---|---|---|
| `loaders` | `fabric`, `forge` | `fabric`, `neoforge` |
| `recipe_dir` | `data/<ns>/recipes/` | `data/<ns>/recipe/` |
| `advancement_dir` | `data/<ns>/advancements/` | `data/<ns>/advancement/` |
| result block | `{"item": id}` | `{"id": id, "count": 1}` |
| `conditional_advancements` | no | yes |
| `item_predicate` | `{"items": [id]}`, tags in a `tag` field | `{"items": id}`, a tag is `#`-prefixed |

`conditional_advancements` is the one that is easy to miss: 1.21 repeats the recipe's load
conditions on the unlock advancement, and without them the advancement loads for a mod that is
not installed and its `rewards` clause points at a recipe that does not exist.

Loader conditions live in `LOADER_CONDITIONS`, keyed by **loader rather than by version**,
because the spelling belongs to the loader — Fabric's has not changed across these versions,
and NeoForge's is Forge's with a different prefix.

### mods.json

`common/data/<version>/mods.json` describes each upstream mod, and every field but the key has
a default, so an entry only states what it does differently:

```json
"twilight_forest": { "namespace": "knavesneeds", "loaders": ["fabric", "forge"], "loaded_id": "twilightforest" }
```

- `namespace` (default `knavesneeds`) — the data pack namespace this mod's recipes and models
  are written under. Blue Skies is the one mod with its own.
- `loaders` (default: all of the version's) — the loaders the mod actually has a build for.
- `loaded_id` (default: the key) — the mod's **runtime** id, which is what a load condition has
  to name. It is not always the folder name: the 1.20.1 data calls Twilight Forest
  `twilight_forest` throughout its paths, but the mod's actual id is `twilightforest`, so a
  condition built from the folder name never matches and the recipe never loads. 1.21.1 renamed
  the folder to match and needs no `loaded_id`.

This table is what replaced the hardcoded Blue Skies special cases that used to sit in
`get_result_item()` and in a `namespace = ... if mod_id == "blue_skies"` line in each `create_*`
function. Adding a mod with unusual conventions is now a data change, not a code change.

### Tiers that are not crafted

Not every tier comes from a crafting bench, and three optional files per version say so. Each
one's own `_comment` is the specification; the short version:

- `parts.json` — Better End never crafts a tool from ingots. It forges a blade on an anvil,
  smiths a handle separately, and joins the two. Its tiers get **no shaped recipe**.
- `smithing.json` — Better Nether's `cincinnasite_diamond` is a smithing *upgrade* of our own
  cincinnasite weapon of the same shape. **No shaped recipe.**
- `rituals.json` — Forbidden Arcanus' `draco_arcanus` comes out of a Hephaestus Forge ritual.
  **No shaped recipe and no unlock advancement** — the ritual is the only way in, and an
  advancement would advertise a recipe book entry that does not exist.

A shaped recipe for one of these is not merely unused: it is a second and wrong way to obtain a
weapon the host mod means you to earn.

The tiers in the first two still get an unlock advancement, but it watches for the **smithing
template** rather than the tier material (`ADVANCEMENT_TRIGGER`) — a material that never passes
through your inventory on the way to the weapon cannot be what unlocks it.

**Only the exclusions are implemented.** The recipes these tiers should get *instead* — Better
End's anvil head plus assembly `smithing_transform`, Better Nether's upgrade transform,
Forbidden Arcanus' forge ritual — are fully described in those files, down to anvil levels and
ritual costs, but nothing generates them yet; they are still maintained by hand in the mod repo.
That is why `generated_dirs()` leaves those tiers' recipe folders out of the clear step. See the
TODO on `load_crafting_rules()`.

### Invisible variants

A tier with `"invisible_variant": true` in `tiers.json` — currently only Souls Weapons'
`translucent` — gets two models per weapon instead of one: the normal model gains an `overrides`
block keyed on the `knavesneeds:invisible` predicate, and a companion `_invisible` model carries
a `display` transform scaling the third-person hands to zero. Both share the one sprite, so the
variant costs a model file and no extra art. "Invisible" here means only that the item is not
drawn in the hand of a player someone else is looking at; it still draws in the inventory and in
first person.

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

## Tier sheets

`sheetgen.py` renders the material set as static contact sheets for showing to people —
an artist briefing, mainly. It is hand-run and not part of the pipeline: it reads
`common/sprites/` and writes PNGs to `sheets/` (gitignored), and `main.py` does not import
it.

```
python sheetgen.py            # one sheet per tier, plus the all-tiers overview
python sheetgen.py --tier 4   # just that one
```

One sheet per progression tier, a row per material and a column per weapon, plus an
overview stacking all seventeen materials in progression order. The per-tier sheets answer
"do these three read as siblings"; the overview answers "does the set read as a
progression".

**The sheets go in `sheets/`, not in `preview/`.** A `--previews` run rmtrees every
subfolder of `preview/`, so a `preview/sheets/` would be deleted by the next preview
render.

- **Every weapon is drawn at the same size.** Sprites are 16/32/48px by weapon type, but
  the game maps each onto the same 16×16 quad, so scaling each sprite to its own pixel
  count would tell an artist the halberd is three times the size of the sai. Scale factors
  are integers (6x/3x/2x onto a 96px cell) so the upscale stays nearest-neighbour crisp.
- **The greathammer is rasterised from its model; every other weapon is its sprite,
  pasted.** Greathammer is the one weapon with an `elements` template, so its PNG is a UV
  atlas for that model rather than a flat item sprite — pasted straight in, it reads as a
  scrambled block of coloured squares in every material, which is also true of the
  hand-drawn reference tiers. The other fourteen are `minecraft:item/generated`, whose
  in-game look *is* the sprite. Rendering those through `render3d` too would cost the
  `bloom` haloes, which sit below the alpha 128 `build_quads` extrudes at and would
  silently vanish from exactly the materials that use them.
- Rasterising needs numpy and the mod's model templates (`preview.TEMPLATES_DIR`, the same
  sibling checkout the previews want). Missing either warns once and falls back to the raw
  atlas, since the other fourteen columns are unaffected either way.
- Animated materials are shown on **frame 0**, and the sheet does not say which those are.
  A still is what gets marked up, and the preview GIFs already show the motion properly.
- **The only caption is `no art yet`, on a row with no art.** No footer, no frame counts,
  no "still" labels, no marking of which rows borrow Simply Swords' art. These sheets go to
  people who already know the set and are shown alongside a written brief; a label on every
  row for something the reader knows just crowds the art. A row without a caption centres
  its name.

### tier_groups.json

`common/data/tier_groups.json` is the progression: five tiers, seventeen materials, in
order. `sheetgen.py` is its only reader — `main.py` is driven by `tiers.json` and knows
nothing about progression tiers.

A material names a sprite folder in `"sprites"` — a selector in the same form
`thumbnail.json` uses — and the five built from vanilla ingots rather than from one of our
materials are additionally flagged `"vanilla": true`.

The vanilla tiers wear **Simply Swords' own art**, copied into
`common/sprites/simplyswords/` from the mod jar, which is the reference the twelve new
materials are pitched against — so a sheet shows the whole progression rather than four
blank rows. Nothing marks those rows as borrowed on the sheet itself; the `vanilla` flag is
descriptive only, and no code currently reads it.

**Copper is the one material with no art at all**, and is deliberately left with no
`sprites`. Simply Swords ships iron, gold, diamond and netherite; its only copper texture
is a single longsword in the MythicMetals compat set, which is that mod's copper and not a
weapon set. Copper stays in the list and draws as an empty row, so the gap is visible
rather than silently absent. An empty cell is a hollow box rather than nothing, so a gap
reads as a gap and not as a sprite that failed to load.

## Output formats

Each tier is written as both GIF and WebP from a single render pass — rasterising costs far more than encoding, so `create_preview()` builds the frames once and hands them to each saver in `FORMATS`. WebP is the better file at roughly half the bytes; GIF is kept as the fallback for anywhere WebP is unsupported.

Frame durations are stated explicitly rather than repeating the held frame. Repetition worked for GIF because Pillow's GIF encoder merges consecutive duplicates, but that is a GIF-specific optimisation the WebP encoder does not share and it would have written every duplicate out.

Note that Pillow's WebP *reader* does not expose per-frame durations — `info["duration"]` comes back empty regardless of what was written. To verify WebP timing, parse the container's `ANMF` chunks (bytes 12–14 of each chunk body are a 24-bit little-endian duration in ms) rather than trusting the reader.

## Output path conventions

- **One item path drives everything.** `get_item_path()` returns `{mod_id}/{tier}/{weapon}` for
  a mod in the shared `knavesneeds` namespace, and `{tier}/{weapon}` for a mod with a namespace
  of its own — Blue Skies has already said which mod it is by being in the `blue_skies`
  namespace, so repeating the mod id would give `blue_skies:blue_skies/pyrope/longsword`. The
  recipe, model, advancement and weapon-attribute paths and the result item id are all built
  from that one function, so an item's id and the four files describing it cannot drift apart.
- Result items are therefore `blue_skies:{tier}/{weapon}` for Blue Skies and
  `knavesneeds:{mod_id}/{tier}/{weapon}` for everything else.
- The namespace is **`blue_skies`, with no `s` on `blue`.** An earlier `blues_skies` typo sent
  every Blue Skies model to a namespace the mod does not have, where nothing could resolve it.
  The spelling now comes from `mods.json` rather than from a literal in each writer.
- Load conditions per loader: Fabric `fabric:load_conditions` / `fabric:all_mods_loaded`, Forge
  `conditions` / `forge:mod_loaded`, NeoForge `neoforge:conditions` / `neoforge:mod_loaded`. All
  three name the mod's `loaded_id`, not its `mod_id`.
- Models and textures both use the singular `item` subfolder, set once as `ITEM_ROOT` in `main.py`. Every model `parent`, `layer0` reference, and output path derives from it, so the generated JSON and the files on disk cannot disagree.
- **Textures are the exception to the item path**: they always go to the `knavesneeds` namespace
  *and* always keep the full `{mod_id}/{tier}/{weapon}`, even for Blue Skies tiers whose models
  live under `blue_skies`. The sprites ship with this mod regardless of which mod the tier comes
  from, so they cannot collapse the mod id the way a namespaced model can.
- An animated sprite is a vertical strip of frames plus a sibling `.png.mcmeta` naming the frame time. The two must travel together: without the `.mcmeta` the game has no reason to think the PNG is anything but one very tall texture, so the strip ships as a stretched still. `create_texture_data` copies the `.mcmeta` alongside the sprite for exactly that reason, and reports how many it moved.

## Sprite layout

`find_sprite()` accepts four layouts, checked in order, because the folders grew organically:

```
common/sprites/{mod_id}/{tier}/{tier}_{weapon}.png
common/sprites/{mod_id}/{tier}/{weapon}.png
common/sprites/{loaded_id}/{tier}/{tier}_{weapon}.png   # only if it differs from mod_id
common/sprites/{loaded_id}/{tier}/{weapon}.png
common/sprites/{tier}/{tier}_{weapon}.png          # tier at top level (Blue Skies woods/gems)
common/sprites/{tier}/{weapon}.png
```

The `loaded_id` pair exists because **the sprite tree is shared by every version while the mod
id is not.** The Twilight Forest art sits in `common/sprites/twilightforest/`, which is what
1.21.1 calls the mod; 1.20.1 calls the same mod `twilight_forest` and would otherwise find none
of its own art. Only the *source* folder is looked up both ways — the texture's output path
still uses the version's own `mod_id`, so it keeps matching the model that points at it.

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

**Animation is reserved for Tier V**, the top of the progression in
`common/data/tier_groups.json` — currently nebulium, erythryl, rhodynth and hesperynt.
Glykios and wyrdbright were authored animated and were turned back into stills by setting
their `frames` to 1 and regenerating; movement reads as *rarity*, so spending it three
tiers down leaves nothing for the top tier to escalate to. Faeglas sits in Tier V and is
still, which is fine — the rule is that nothing below Tier V animates, not that everything
in it must.

Turning an animation off is a one-number change (`frames` back to 8, 12, whatever it was)
followed by a regenerate, because the palette keeps the whole description of the effect.
The treatment list is untouched either way: `glykios`' `sparkle` and `wyrdbright`'s `pulse`
still apply, they just resolve to a single frame. Note that a treatment carrying a phase —
`sparkle`'s `twinkle`, here — does not necessarily land on frame 0 of the strip it used to
produce, so a de-animated tier is not always pixel-identical to its old first frame.
Wyrdbright's `pulse` was; glykios' sparkle specks moved slightly.

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
  `chakram/betternether_cincinnasite` is 87% handle-family *by area* against base's 0% — that
  tier drew the disc in colours the other tiers agreed on, so `_learn_handles` claimed it.
  It renders entirely from the handle ramp and ignores the material.
  `longsword/undergarden_utherium` is the other one, at 78%. `_mostly_grip()` judges against
  the same weapon's base blank rather than an absolute threshold, since a spear is
  legitimately half shaft at 56%.
- **Grip share is measured by area, not slot count.** Slot count is only a proxy, and a weak
  one — a blank whose grip carries many near-identical shades reads as far more grip than it
  is. Both known-bad blanks also separate more clearly by area (87%/78%) than by slot count
  (80%/67%), so it is the stricter measure as well as the more honest one.

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

**Add a new weapon type**: add an entry to `common/patterns/<version>/sword_patterns.json` with a 3×3 pattern using `M`, `H`, `B` placeholders (use spaces for empty cells), for each version that should have it. No Python changes needed. It will want a sprite per tier and an item model template in the mod repo before it renders.

**Draw a new tier's sprites**: write a material ramp and run `python spritegen.py generate <tier> --from <existing-tier>`, or pass a hand-written `Palette` — see the palette-swapping section above. Copy the result out of `generated_sprites/` into `common/sprites/`; nothing generates into the sprite tree automatically.

**Place a material in the progression**: add it to the right tier's `materials` list in `common/data/tier_groups.json`, pointing `sprites` at its folder. The list is ordered, and that order is the order it appears on a sheet. Nothing else reads this file, so it does not affect what is generated — only what the sheets show.

**Add a new mod/material tier**: add the mod's items to `common/data/<version>/keys.json`, then add entries to `common/data/<version>/tiers.json` referencing those key names, and drop the sprites into `common/sprites/` in one of the layouts above. No Python changes needed for standard tiers. Run `python main.py --mc <version>` and check the warning block — it lists any tier × weapon whose sprite could not be found. The tier and key files are per version, so a material that exists in only one version is added to only that one; the sprites are shared.

**Add a new supported mod**: add items to `common/data/<version>/keys.json`, add tiers to `tiers.json`, and add an entry to `mods.json` giving its `namespace`, `loaders` and `loaded_id` where those differ from the defaults. This no longer needs a Python change — the Blue Skies special cases that used to be hardcoded in `get_result_item()` and in each `create_*` function are now read from `mods.json`.

**Add a new Minecraft version**: add a `VersionProfile` to `VERSION_PROFILES` in `main.py`, and create `common/data/<version>/` (`keys.json`, `tiers.json`, `mods.json`) and `common/patterns/<version>/` (`sword_patterns.json`, `tier_patterns.json`). Copying the nearest existing version's folder and editing it is the intended route. The GUI picks the new version up from `VERSION_PROFILES` with no change of its own. Fill the profile in from a real mod repo of that version rather than from memory of what Mojang renamed — that is how the existing two were built, and it is the only way to catch things like 1.21's conditional advancements.

**Give a tier a different recipe shape**: add it to `common/patterns/<version>/tier_patterns.json` as `{tier: {weapon: [row, row, row]}}`, or paint it in the GUI's pattern editor. The override replaces the base grid for that one tier and weapon; every other tier keeps the base.