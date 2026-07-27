# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project does

This is a data generation tool for a Minecraft mod ("knavesneeds"). It programmatically creates JSON files for crafting recipes, item models, weapon attributes, and recipe unlock advancements, and copies the matching item sprites out of `common/sprites/` — targeting both Fabric and Forge mod loaders.

Sprites are the single source of truth here: they live in `common/sprites/` and are exported into each loader's asset tree by the generator, rather than being copied into the downstream mod projects by hand.

## Running the generator

```
python main.py
```

JSON and texture generation needs only the standard library (`json`, `os`, `shutil`, `time`). Preview GIF rendering additionally needs Pillow:

```
pip install -r requirements.txt
```

Pillow is imported lazily inside `create_preview_data()`, so without it the run still produces every JSON file and texture and just skips the GIF step with a warning. The script clears and regenerates `fabric/`, `forge/`, and `preview/` on every run; all three are gitignored.

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

`main.py` holds the JSON pipeline; `preview.py` is the only separate module, kept apart because it is the sole consumer of the optional Pillow dependency.

## Preview GIFs

Each tier's GIF spins its weapons toward the camera like a coin. Width follows `|cos(angle)|`, so each weapon owns exactly one half turn — edge-on, through full-face, back to edge-on — and the texture swaps to the next weapon at the edge-on frame, where the sprite is a 1px sliver and the cut is invisible. Sprites are never mirrored past edge-on: they are flat textures with no back face, and a mirrored weapon reads as wrong rather than as rotated.

Tuning constants live at the top of `preview.py` (`SPIN_FRAMES`, `HOLD_FRAMES`, `FRAME_MS`, `SCALE`, `MIN_BRIGHTNESS`). Two things to know before changing them:

- Sprites are 16/48px depending on weapon type (sai/cutlass/chakram are 16, halberd is 48, the rest 32) and that difference is intentional. Everything composites onto a `BASE_SPRITE`-sized canvas so relative scale survives — do not normalise each sprite to fill the frame.
- Pillow merges consecutive identical frames on save, so the hold frames collapse into one long-duration frame. A GIF reporting fewer frames than were generated is expected; total playback time is unchanged.

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

A sprite only exports if a tier in `tiers.json` references it — sprite folders with no corresponding tier are silently ignored, so adding art alone is not enough to make an item appear.

## Extending the project

**Add a new weapon type**: add an entry to `common/patterns/sword_patterns.json` with a 3×3 pattern using `M`, `H`, `B` placeholders (use spaces for empty cells). No Python changes needed.

**Add a new mod/material tier**: add the mod's items to `common/data/keys.json`, then add entries to `common/data/tiers.json` referencing those key names, and drop the sprites into `common/sprites/` in one of the layouts above. No Python changes needed for standard tiers. Run `python main.py` and check the warning block — it lists any tier × weapon whose sprite could not be found.

**Add a new supported mod with a custom namespace**: add items to `common/data/keys.json`, add tiers to `common/data/tiers.json`, then update `get_result_item()` and the `namespace` local variable in each `create_*` function if the mod needs non-default namespace/path conventions (Blue Skies is the existing example).