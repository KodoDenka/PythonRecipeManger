# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project does

This is a data generation tool for a Minecraft mod ("knavesneeds"). It programmatically creates JSON files for crafting recipes, item models, weapon attributes, and recipe unlock advancements, and copies the matching item sprites out of `common/sprites/` — targeting both Fabric and Forge mod loaders.

Sprites are the single source of truth here: they live in `common/sprites/` and are exported into each loader's asset tree by the generator, rather than being copied into the downstream mod projects by hand.

## Running the generator

```
python main.py
```

JSON and texture generation needs only the standard library (`json`, `os`, `shutil`, `time`). Preview GIF rendering additionally needs Pillow, and the 3D renderer needs numpy:

```
pip install -r requirements.txt
```

Both are imported lazily, and the run degrades in stages rather than failing: without numpy previews fall back to the 2D sprite renderer, and without Pillow the GIF step is skipped entirely with a warning. Every JSON file and texture is produced either way. The script clears and regenerates `fabric/`, `forge/`, and `preview/` on every run; all three are gitignored.

## Architecture

Everything lives in `main.py`. The generation pipeline runs in this order:

1. **Keys** (`common/data/keys.json`) — loaded into a local dict mapping identifier → `[prefix, "namespace:identifier"]`.
2. **Tiers** (`common/data/tiers.json`) — loaded and resolved against the keys dict into the global `tiers` dict of `TierClass` instances. Each tier has a `mod_id`, plus resolved `material`, `handle`, and `binder` key tuples.
3. **Pattern loading** — reads `common/patterns/sword_patterns.json` into `SWORD_PATTERNS`. Each entry maps a weapon name to its 3-row crafting grid using `M` (material), `H` (handle), `B` (binder) placeholders.
4. **Recipe generation** (`create_recipe_data`) — iterates all tiers × all sword patterns and writes shaped crafting recipe JSONs. Binder key is only included if `B` appears in the pattern.
5. **Model generation** (`create_model_date`) — writes item model JSONs for both loaders.
6. **Weapon attributes** (`create_weapon_attributes_date`) — writes weapon attribute JSONs for both loaders.
7. **Unlock advancements** (`create_unlock_data`) — writes Fabric-only advancement JSONs for recipe unlocking.
8. **Textures** (`create_texture_data`) — copies each tier × weapon sprite from `common/sprites/` into both loaders. Tiers with no matching sprite are collected in `missing_sprites` and printed as a warning at the end of the run.
9. **Preview GIFs** (`create_preview_data` → `preview.py`) — renders one looping showcase GIF per tier to `preview/{mod_id}/{tier}.gif`.

Steps 1–8 are driven by `tiers.json`, because recipes, models and advancements need real item IDs. Step 9 is driven by `discover_sprite_tiers()` walking `common/sprites/` instead, so a mod whose art has landed but whose recipes have not still gets a showcase GIF. Those are flagged `[art only, no recipes]` in the run output.

`main.py` holds the JSON pipeline; `preview.py` is the only separate module, kept apart because it is the sole consumer of the optional Pillow dependency.

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
- `EASING` in `preview.py` shapes progress through the half turn so the weapon decelerates into the held frame instead of stopping dead. It only redistributes angles across existing frames, so it never changes the loop duration. Blended against linear rather than applied neat, since a pure cubic stalls at face-on and bunches frames there, silently lengthening the hold.
- `TILT` tilts the camera off the equator so top faces stay visible. `fit_scale()` must be given the same tilt or tall weapons clip, since tilting mixes depth into the vertical extent.
- The specular sweep (`SPEC_STRENGTH`, `SPEC_WIDTH` in `render3d.py`) follows `sin(2*spin)^2`, which is zero both edge-on and face-on. Face-on **must** stay zero: that is the frame the GIF holds, and a highlight peaking there would freeze mid-blade for the whole hold.
- `SPEC_STEPS` bands the highlight instead of letting it fall off smoothly. This is a file size control, not just a look: a smooth gradient spends the GIF's 255 colours on near-identical shades and compresses badly, costing ~75% more per file for no visible gain. Raise it only alongside a size check.

## Output path conventions

- Blue Skies items use the namespace `blues_skies`; all others use `knavesneeds`.
- Blue Skies result items are `blue_skies:{tier}/{weapon}`; others are `knavesneeds:{mod_id}/{tier}/{weapon}`.
- Fabric conditions use `fabric:load_conditions` / `fabric:all_mods_loaded`; Forge uses `conditions` / `forge:mod_loaded`.
- Models and textures both use the singular `item` subfolder, set once as `ITEM_ROOT` in `main.py`. Every model `parent`, `layer0` reference, and output path derives from it, so the generated JSON and the files on disk cannot disagree.
- Textures always go to the `knavesneeds` namespace, even for Blue Skies tiers whose *models* live under `blues_skies` — the sprites ship with this mod regardless of which mod the tier comes from.

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

## Extending the project

**Add a new weapon type**: add an entry to `common/patterns/sword_patterns.json` with a 3×3 pattern using `M`, `H`, `B` placeholders (use spaces for empty cells). No Python changes needed.

**Add a new mod/material tier**: add the mod's items to `common/data/keys.json`, then add entries to `common/data/tiers.json` referencing those key names, and drop the sprites into `common/sprites/` in one of the layouts above. No Python changes needed for standard tiers. Run `python main.py` and check the warning block — it lists any tier × weapon whose sprite could not be found.

**Add a new supported mod with a custom namespace**: add items to `common/data/keys.json`, add tiers to `common/data/tiers.json`, then update `get_result_item()` and the `namespace` local variable in each `create_*` function if the mod needs non-default namespace/path conventions (Blue Skies is the existing example).