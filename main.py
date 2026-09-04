import json
import os
import shutil
import time
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class TierClass:
    mod_id: str
    material: list[str]
    handle: list[str]
    binder: list[str]

tiers: dict[str, TierClass] = {}

count = 0

SPRITES_DIR = "common/sprites"
# Subfolder used under both assets/<ns>/textures/ and assets/<ns>/models/. Everything
# that builds a texture or model reference goes through this, so the generated JSON and
# the files on disk can't drift apart.
ITEM_ROOT = "item"

missing_sprites: list[tuple[str, str, str]] = []

# "3d" rasterises the real item models; "2d" is the sprite-squash fallback. Falls back
# automatically if the 3D renderer's dependencies are missing.
PREVIEW_MODE = "3d"

# The mod's showcase thumbnail: one weapon spun through every material, with the logo over
# it. Chakram because it is the roundest weapon in the set, so it reads at thumbnail size
# and keeps a consistent silhouette while the material changes underneath it.
THUMBNAIL_WEAPON = "chakram"
THUMBNAIL_PATH = "preview/thumbnail"
LOGO_PATH = f"{SPRITES_DIR}/LOGO.png"

def load_keys(file_path):
    return return_json_data(file_path)

def load_tiers(file_path, keys):
    raw = return_json_data(file_path)
    for name, entry in raw.items():
        tiers[name] = TierClass(
            mod_id=entry["mod_id"],
            material=keys[entry["material"]],
            handle=keys[entry["handle"]],
            binder=keys[entry["binder"]],
        )

def return_json_data(file_path):

    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"JSON file not found at {file_path}")
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            data = json.load(file)
        return data
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON format in file: {file_path}\nError: {e}")
    except Exception as e:
        raise RuntimeError(f"An error occurred while reading the file: {e}")



def create_recipe_data(loader):
    for tier_name, tier in tiers.items():
        for sword in SWORD_PATTERNS:
            create_shaped_recipe(
                sword=sword,
                name=tier_name,
                mod_id=tier.mod_id,
                material=tier.material,
                handle=tier.handle,
                binder=tier.binder,
                loader=loader,
            )

def get_loader_conditions(mod_id, loader):
    if loader == "fabric":
        return "fabric:load_conditions", [{"condition": "fabric:all_mods_loaded", "values": [mod_id]}]
    elif loader == "forge":
        return "conditions", [{"type": "forge:mod_loaded", "modid": mod_id}]
    print("Loader not recognized or supported.")
    return None, []

def get_result_item(mod_id, name, sword):
    if mod_id == "blue_skies":
        return f"blue_skies:{name}/{sword}"
    return f"knavesneeds:{mod_id}/{name}/{sword}"

def write_json(path: str, data: dict) -> None:
    global count
    count = count + 1
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def copy_file(src: str, dest: str) -> None:
    global count
    count = count + 1
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copyfile(src, dest)

def get_texture_ref(mod_id, name, sword):
    """The "layer0" texture id an item model points at.

    Always in the knavesneeds namespace, even for tiers whose models live under the
    blues_skies namespace, because the sprites ship with this mod.
    """
    return f"knavesneeds:{ITEM_ROOT}/{mod_id}/{name}/{sword}"

def get_texture_path(loader, mod_id, name, sword):
    """Where the sprite for get_texture_ref() has to land for the game to resolve it."""
    return f"{loader}/assets/knavesneeds/textures/{ITEM_ROOT}/{mod_id}/{name}/{sword}.png"

def find_sprite(mod_id, name, sword):
    """Locate a source sprite in common/sprites, or None if it hasn't been drawn.

    Sprite folders use two layouts (mod-scoped and tier-at-top-level) and two naming
    conventions (tier-prefixed and bare), so try each combination.

    Candidates are exact filenames built from the weapon name, which is what keeps variant
    art out: Better End's `*_head.png` alternates and the stray `*2.png` / `*3.png` drafts
    can never match, because no weapon is named `chakram_head` or `claymore2`.
    """
    candidates = [
        f"{SPRITES_DIR}/{mod_id}/{name}/{name}_{sword}.png",
        f"{SPRITES_DIR}/{mod_id}/{name}/{sword}.png",
        f"{SPRITES_DIR}/{name}/{name}_{sword}.png",
        f"{SPRITES_DIR}/{name}/{sword}.png",
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return None

def discover_sprite_tiers():
    """Find every tier that has artwork, whether or not it is wired into tiers.json.

    Previews are driven off the sprite folders rather than the tier data, so a mod whose
    art has landed but whose recipes have not still gets a showcase GIF. Recipes, models,
    textures and advancements stay driven by tiers.json — those need real item IDs.

    Two folder shapes exist: a mod folder holding tier folders, and a bare tier folder at
    the top level. A folder containing PNGs directly is a tier; one containing only
    folders is a mod. Returns (mod_id, tier_name) pairs, where mod_id is None for a
    top-level tier that tiers.json has never heard of.
    """
    found = []
    if not os.path.isdir(SPRITES_DIR):
        return found

    for entry in sorted(os.listdir(SPRITES_DIR)):
        path = os.path.join(SPRITES_DIR, entry)
        if not os.path.isdir(path):
            continue

        children = sorted(os.listdir(path))
        if any(child.lower().endswith(".png") for child in children):
            # A tier sitting at the top level. tiers.json is the authority on which mod it
            # belongs to, since the folder name alone does not say.
            mod_id = tiers[entry].mod_id if entry in tiers else None
            found.append((mod_id, entry))
            continue

        for child in children:
            if os.path.isdir(os.path.join(path, child)):
                found.append((entry, child))
    return found

def get_preview_path(mod_id, tier_name):
    """Output path without an extension; preview.py appends one per format."""
    if mod_id is None:
        return f"preview/{tier_name}"
    return f"preview/{mod_id}/{tier_name}"

def create_texture_data():
    animated = 0
    for tier_name, tier in tiers.items():
        for sword in SWORD_PATTERNS:
            source = find_sprite(tier.mod_id, tier_name, sword)
            if source is None:
                missing_sprites.append((tier.mod_id, tier_name, sword))
                continue
            # an animated sprite is a vertical strip of frames plus a sibling .png.mcmeta
            # naming the frame time. Without the .mcmeta the game has no reason to think
            # the PNG is anything but one very tall texture, so the two have to travel
            # together or the strip ships as a stretched still.
            meta = source + ".mcmeta"
            has_meta = os.path.exists(meta)
            for loader in ["fabric", "forge"]:
                dest = get_texture_path(loader, tier.mod_id, tier_name, sword)
                copy_file(source, dest)
                if has_meta:
                    copy_file(meta, dest + ".mcmeta")
            animated += has_meta
    if animated:
        print(f"  {animated} animated texture(s) exported with their .mcmeta.")

_preview_runtime = None

def resolve_preview_runtime():
    """Import preview.py and settle on a renderer, or (None, None) if Pillow is missing.

    Both the per-tier previews and the thumbnail need this, and both are optional extras
    on top of a run whose JSON and texture output is already complete — so a missing
    dependency warns rather than raising. Resolved once and cached, so the warnings are
    printed once no matter how many steps ask.
    """
    global _preview_runtime
    if _preview_runtime is not None:
        return _preview_runtime

    try:
        import preview
    except ImportError:
        print("\nSkipping preview GIFs: Pillow is not installed (pip install -r requirements.txt).")
        _preview_runtime = (None, None)
        return _preview_runtime

    mode = PREVIEW_MODE
    if not preview.renderer_available(mode):
        print("  numpy not installed, falling back to the 2D sprite renderer.")
        mode = "2d"

    _preview_runtime = (preview, mode)
    return _preview_runtime

def create_preview_data():
    """Render one spin-loop GIF per tier that has artwork, for the website.

    Driven by the sprite folders rather than tiers.json, so mods whose art exists but
    whose recipes do not are still showcased.
    """
    global count
    preview, mode = resolve_preview_runtime()
    if preview is None:
        return

    unresolved = []
    for mod_id, tier_name in discover_sprite_tiers():
        weapons = []
        for sword in SWORD_PATTERNS:
            source = find_sprite(mod_id, tier_name, sword)
            if source is not None:
                weapons.append((sword, source))

        if not weapons:
            # Art that follows none of the known naming conventions, so nothing matched.
            unresolved.append(f"{mod_id}/{tier_name}" if mod_id else tier_name)
            continue

        stem = get_preview_path(mod_id, tier_name)
        frames = preview.create_preview(weapons, stem, mode)
        count = count + len(preview.FORMATS)
        recipes = "" if tier_name in tiers else "  [art only, no recipes]"
        formats = "/".join(preview.FORMATS)
        print(f"  {stem}.{{{formats}}} ({len(weapons)} weapons, {frames} frames, {mode}){recipes}")

    if unresolved:
        print(f"\n  No sprite matched a weapon name in: {', '.join(unresolved)}")
        print("  Art there is named for a different tier or is a numbered variant.")

def is_wooden_tier(tier_name):
    """True for tiers crafted out of planks — Blue Skies' seven wood sets.

    Tested on the material item rather than the tier name, because `ironwood` is a metal
    and `turquoise_stone` is not, so neither the name nor its suffix is a reliable signal.
    Tiers that have art but no entry in tiers.json have no material to test and are
    treated as non-wooden.
    """
    tier = tiers.get(tier_name)
    return tier is not None and str(tier.material[1]).endswith("_planks")

def collect_thumbnail_weapons():
    """Gather THUMBNAIL_WEAPON's sprite from every material in the mod, in tier order.

    Wooden tiers are left out: they are seven near-identical entries out of a set of about
    thirty, and a showcase that spends a quarter of its loop cycling through planks sells
    the mod short.

    Returns (label, sprite_path) pairs. The label is the tier name rather than the weapon
    name, since here it is the material that changes from entry to entry.
    """
    weapons = []
    for mod_id, tier_name in discover_sprite_tiers():
        if is_wooden_tier(tier_name):
            continue
        source = find_sprite(mod_id, tier_name, THUMBNAIL_WEAPON)
        if source is not None:
            weapons.append((tier_name, source))
    return weapons

def create_thumbnail_data():
    """Render the mod's showcase loop to preview/thumbnail.{gif,webp}.

    Same spin as the per-tier previews with the axes swapped — one weapon through every
    material instead of one material through every weapon — plus the logo on top.
    """
    global count
    preview, mode = resolve_preview_runtime()
    if preview is None:
        return

    weapons = collect_thumbnail_weapons()
    if not weapons:
        print(f"  No {THUMBNAIL_WEAPON} sprites found, skipping the thumbnail.")
        return

    if not os.path.isfile(LOGO_PATH):
        print(f"  {LOGO_PATH} is missing, rendering the thumbnail without the logo.")

    frames = preview.create_thumbnail(weapons, THUMBNAIL_PATH, LOGO_PATH, mode)
    count = count + len(preview.FORMATS)
    formats = "/".join(preview.FORMATS)
    print(f"  {THUMBNAIL_PATH}.{{{formats}}} "
          f"({len(weapons)} materials, {frames} frames, {mode})")

def get_pattern(sword):
    """Return the 3-row grid for a weapon.

    Entries in sword_patterns.json wrap the grid in a {"pattern": [...]} object, but
    tolerate a bare list too so either shape works.
    """
    entry = SWORD_PATTERNS.get(sword, [])
    if isinstance(entry, dict):
        return entry.get("pattern", [])
    return entry

def create_shaped_recipe(sword, name, mod_id, material, handle, binder, loader):
    pattern = get_pattern(sword)
    result = get_result_item(mod_id, name, sword)
    condition_type, conditions = get_loader_conditions(mod_id, loader)

    recipe_keys = {
        "H": {str(handle[0]): str(handle[1])},
        "M": {str(material[0]): str(material[1])}
    }

    if any("B" in row for row in pattern):
        recipe_keys["B"] = {str(binder[0]): str(binder[1])}

    json_data = {
        condition_type: conditions,
        "type": "minecraft:crafting_shaped",
        "category": "equipment",
        "key": recipe_keys,
        "pattern": pattern,
        "result": {"item": result}
    }

    namespace = "blues_skies" if mod_id == "blue_skies" else "knavesneeds"
    filename = f"{loader}/data/{namespace}/recipes/{mod_id}/{name}/{sword}.json"

    write_json(filename, json_data)

def create_model_date():
    for tier_name, tier in tiers.items():
        for sword in SWORD_PATTERNS:

            namespace = "blues_skies" if tier.mod_id == "blue_skies" else "knavesneeds"

            json_data = {
                "parent" : f"knavesneeds:{ITEM_ROOT}/templates/{sword}",
                "textures" : {
                    "layer0" : get_texture_ref(tier.mod_id, tier_name, sword)
                }
            }


            for loader in ["fabric", "forge"]:
                filename = f"{loader}/assets/{namespace}/models/{ITEM_ROOT}/{tier.mod_id}/{tier_name}/{sword}.json"
                write_json(filename, json_data)


def create_weapon_attributes_date():
    for tier_name, tier in tiers.items():
        for sword in SWORD_PATTERNS:

            json_data = {
                "parent": f"knavesneeds:{sword}"
            }

            namespace = "blues_skies" if tier.mod_id == "blue_skies" else "knavesneeds"
            filename = f"fabric/data/{namespace}/weapon_attributes/{tier.mod_id}/{tier_name}/{sword}.json"
            write_json(filename, json_data)
            filename = f"forge/data/{namespace}/weapon_attributes/{tier.mod_id}/{tier_name}/{sword}.json"
            write_json(filename, json_data)

def create_unlock_data():
    for tier_name, tier in tiers.items():
        for sword in SWORD_PATTERNS:
            result = get_result_item(tier.mod_id, tier_name, sword)
            json_data = {
                "parent": "minecraft:recipes/root",
                "criteria": {
                    "has_material": {
                        "conditions": {
                            "items": [
                                {
                                    "items": tier.material
                                }
                            ]
                        },
                        "trigger": "minecraft:inventory_changed"
                    },
                    "has_the_recipe": {
                        "conditions": {
                            "recipe": result
                        },
                        "trigger": "minecraft:recipe_unlocked"
                    }
                },
                "requirements": [
                    [
                        "has_material",
                        "has_the_recipe"
                    ]
                ],
                "rewards": {
                    "recipes": [
                        result
                    ]
                },
                "sends_telemetry_event": False
            }

            namespace = "blues_skies" if tier.mod_id == "blue_skies" else "knavesneeds"
            filename = f"fabric/data/{namespace}/advancements/recipes/{tier.mod_id}/{tier_name}/{sword}.json"
            write_json(filename, json_data)

#Credit to https://stackoverflow.com/questions/185936/how-to-delete-the-contents-of-a-folder
def clear_old_data(folders=("fabric", "forge", "preview")):
    """Empty the generated output folders.

    `preview/` is only cleared on a run that is going to rebuild it. Wiping previews that
    the run then skips would leave the folder empty rather than stale, which is the worse
    of the two -- a stale GIF is still a GIF.
    """
    for folder in folders:
        if not os.path.isdir(folder):
            continue
        for filename in os.listdir(folder):
            file_path = os.path.join(folder, filename)
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
            except Exception as e:
                print('Failed to delete %s. Reason: %s' % (file_path, e))



def log_and_return_time(message, start_time):
    elapsed = (time.time() - start_time) * 1000
    print(f"{message} (took {elapsed:.2f}ms)")
    return time.time()

PREVIEW_FLAGS = ("--previews", "--preview", "-p")

if __name__ == '__main__':
    global SWORD_PATTERNS
    import sys

    # Previews are opt-in because they cost minutes while the JSON and textures -- the part
    # a mod build actually consumes -- take seconds. Rebuilding 39 tiers of spin animation
    # to change one recipe is a bad default.
    render_previews = any(flag in sys.argv[1:] for flag in PREVIEW_FLAGS)
    unknown = [a for a in sys.argv[1:] if a not in PREVIEW_FLAGS]
    if unknown:
        print(f"Unknown argument(s): {', '.join(unknown)}")
        print(f"usage: python main.py [{PREVIEW_FLAGS[0]}]")
        raise SystemExit(2)

    print("Starting data generation...")
    start_time = time.time()

    clear_old_data(("fabric", "forge", "preview") if render_previews
                   else ("fabric", "forge"))
    start_time = log_and_return_time("Cleared old data", start_time)

    keys = load_keys("common/data/keys.json")
    start_time = log_and_return_time("Loaded keys/ingredients data", start_time)

    load_tiers("common/data/tiers.json", keys)
    start_time = log_and_return_time("Loaded tiers", start_time)

    SWORD_PATTERNS = return_json_data("common/patterns/sword_patterns.json")
    start_time = log_and_return_time("Loaded sword patterns", start_time)

    create_recipe_data("fabric")
    start_time = log_and_return_time("Made recipes for Fabric", start_time)

    create_recipe_data("forge")
    start_time = log_and_return_time("Made recipes for Forge", start_time)

    create_model_date()
    start_time = log_and_return_time("Created model data", start_time)

    create_weapon_attributes_date()
    start_time = log_and_return_time("Created weapon attributes data", start_time)

    create_unlock_data()
    start_time = log_and_return_time("Created unlock data", start_time)

    create_texture_data()
    start_time = log_and_return_time("Copied textures", start_time)

    if render_previews:
        print("Rendering preview GIFs...")
        create_preview_data()
        start_time = log_and_return_time("Rendered preview GIFs", start_time)

        print("Rendering mod thumbnail...")
        create_thumbnail_data()
        start_time = log_and_return_time("Rendered mod thumbnail", start_time)
    else:
        print(f"Skipped previews and thumbnail "
              f"(pass {PREVIEW_FLAGS[0]} to render them).")

    if missing_sprites:
        print(f"\nWARNING: no sprite found for {len(missing_sprites)} item(s):")
        by_tier: dict[str, list[str]] = {}
        for miss_mod, miss_tier, miss_sword in missing_sprites:
            by_tier.setdefault(f"{miss_mod}/{miss_tier}", []).append(miss_sword)
        for tier_path, tier_swords in by_tier.items():
            if len(tier_swords) == len(SWORD_PATTERNS):
                print(f"  {tier_path}: all {len(tier_swords)} weapons")
            else:
                print(f"  {tier_path}: {', '.join(tier_swords)}")
        print("These items will render as missing textures in game.")

    print(f"\nFinished! Created {count} files.")

