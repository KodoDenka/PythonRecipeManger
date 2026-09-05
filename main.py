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
    # Souls Weapons' translucent tier turns invisible in hand. The item needs a second
    # model the game swaps to on a predicate, so the tier declares the flag and
    # create_model_date() writes the pair.
    invisible_variant: bool = False

@dataclass(frozen=True, slots=True)
class ModClass:
    """One upstream mod: where its generated files live, and how a recipe tests for it.

    `namespace` is the data pack namespace the mod's recipes and models are written under.
    A mod with its own namespace (Blue Skies) already says which mod it belongs to by the
    namespace alone, so its item paths drop the mod id — see `get_item_path()`.

    `loaded_id` is the mod's *runtime* id, which is what a load condition has to name. It
    is not always the folder name: the 1.20.1 data calls Twilight Forest `twilight_forest`
    throughout its paths, but the mod's actual id is `twilightforest`, so a condition built
    from the folder name would never match and the recipe would never load.
    """
    mod_id: str
    namespace: str
    loaders: tuple[str, ...]
    loaded_id: str

@dataclass(frozen=True, slots=True)
class VersionProfile:
    """The data pack conventions of one Minecraft version.

    Every field here is something that changed between 1.20.1 and 1.21.1, and each was read
    off the corresponding mod repo rather than inferred, because getting one wrong produces
    files the game loads without complaint and then silently ignores.

    - `loaders` — 1.21 replaced Forge with NeoForge.
    - `recipe_dir` / `advancement_dir` — 1.21 made the data pack folder names singular.
    - `result_key` / `result_count` — a 1.20 recipe result is `{"item": id}`; a 1.21 one is
      `{"id": id, "count": n}`.
    - `conditional_advancements` — 1.21 repeats the recipe's load conditions on the unlock
      advancement. Without them the advancement loads for a mod that is not installed.
    - `item_predicate` — how an inventory_changed trigger names an item. "list" is 1.20's
      `{"items": [id]}` with tags in a separate `tag` field; "string" is 1.21's
      `{"items": id}`, where a tag is the same field with a `#` prefix.
    """
    loaders: tuple[str, ...]
    recipe_dir: str
    advancement_dir: str
    result_key: str
    result_count: bool
    conditional_advancements: bool
    item_predicate: str

# Keyed by the --mc argument. The GUI reads this dict to populate its version selector, so
# adding a version here is all it takes to offer it there too.
VERSION_PROFILES: dict[str, VersionProfile] = {
    "1.20.1": VersionProfile(
        loaders=("fabric", "forge"),
        recipe_dir="recipes",
        advancement_dir="advancements",
        result_key="item",
        result_count=False,
        conditional_advancements=False,
        item_predicate="list",
    ),
    "1.21.1": VersionProfile(
        loaders=("fabric", "neoforge"),
        recipe_dir="recipe",
        advancement_dir="advancement",
        result_key="id",
        result_count=True,
        conditional_advancements=True,
        item_predicate="string",
    ),
}

DEFAULT_VERSION = "1.21.1"

# How each loader spells "only load this if that mod is present". Keyed by loader rather
# than by version because the spelling belongs to the loader: Fabric's has not changed
# across these versions, and NeoForge's is Forge's with a different prefix.
LOADER_CONDITIONS = {
    "fabric": ("fabric:load_conditions",
               lambda mod: {"condition": "fabric:all_mods_loaded", "values": [mod]}),
    "forge": ("conditions",
              lambda mod: {"type": "forge:mod_loaded", "modid": mod}),
    "neoforge": ("neoforge:conditions",
                 lambda mod: {"type": "neoforge:mod_loaded", "modid": mod}),
}

# The namespace this mod's own assets live under. Mods listed in mods.json with a different
# namespace (Blue Skies) get their recipes and models written there instead.
DEFAULT_NAMESPACE = "knavesneeds"

tiers: dict[str, TierClass] = {}
mods: dict[str, ModClass] = {}
# Base grids, and the per-tier overrides that replace them for one tier's weapon.
SWORD_PATTERNS: dict = {}
TIER_PATTERNS: dict = {}

# Not every tier is crafted at a bench. Better End forges its weapons from a head and a
# handle, Better Nether's cincinnasite_diamond is a smithing upgrade of our own
# cincinnasite weapon, and Forbidden Arcanus' draco_arcanus comes out of a Hephaestus Forge
# ritual. parts.json / smithing.json / rituals.json declare those tiers, and the generator
# has to stay off them: a shaped recipe for one is not merely unused, it is a second and
# wrong way to obtain a weapon the host mod means you to earn.
#
# Writing the smithing, anvil and ritual recipes themselves is not implemented yet — see
# the TODO by load_crafting_rules(). Until it is, these tiers keep their models, weapon
# attributes and textures, and the run leaves their recipe folders alone entirely.
NO_RECIPE_TIERS: set[str] = set()
NO_ADVANCEMENT_TIERS: set[str] = set()
# tier -> the item whose acquisition unlocks the recipe, when it is not the tier material.
# A smithing recipe is unlocked by holding its template, not by mining its ore.
ADVANCEMENT_TRIGGER: dict[str, str] = {}

# Set from --mc before anything reads them.
PROFILE: VersionProfile = VERSION_PROFILES[DEFAULT_VERSION]
# Where generated files land. None means the local ./<loader> staging folders; a path means
# a multiloader mod project root, and output goes to <root>/<loader>/src/main/resources/.
OUTPUT_ROOT: str | None = None

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

# Which tiers the thumbnail is allowed to show. Required, and deliberately not inferred:
# common/sprites/ carries art for forty-odd tiers across a dozen upstream mods, and none of
# those ship in the mod a thumbnail advertises. Discovering the list from the sprite tree
# put other people's materials in our showcase.
THUMBNAIL_CONFIG = "common/data/thumbnail.json"

def data_dir(version):
    """Where a version's keys/tiers/mods live."""
    return f"common/data/{version}"

def patterns_dir(version):
    """Where a version's base grids and per-tier overrides live."""
    return f"common/patterns/{version}"

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
            invisible_variant=bool(entry.get("invisible_variant", False)),
        )

def load_mods(file_path):
    """Read mods.json into the global `mods` table.

    Every field but `mod_id` has a default, so an entry only has to state what it does
    differently: most mods ship under the knavesneeds namespace, load on every loader the
    version supports, and are named the same at runtime as in their paths.
    """
    raw = return_json_data(file_path)
    for mod_id, entry in raw.items():
        mods[mod_id] = ModClass(
            mod_id=mod_id,
            namespace=entry.get("namespace", DEFAULT_NAMESPACE),
            loaders=tuple(entry.get("loaders", PROFILE.loaders)),
            loaded_id=entry.get("loaded_id", mod_id),
        )

def load_crafting_rules(version):
    """Read the tiers that are obtained some way other than a shaped recipe.

    All three files are optional — 1.20.1 declares none of them — and each one's own
    `_comment` is the specification for what it means.

    TODO: only the *exclusions* are implemented. The recipes these tiers should get
    instead — Better End's anvil head plus assembly smithing_transform, Better Nether's
    upgrade transform, Forbidden Arcanus' forge ritual — are fully described in the data
    but nothing generates them yet, so those recipes are still maintained by hand in the
    mod repo. Until that lands, `generated_dirs()` deliberately leaves their recipe folders
    out of the clear step so a run cannot delete the hand-written ones.
    """
    parts_path = f"{data_dir(version)}/parts.json"
    if os.path.isfile(parts_path):
        for mod_id, entry in return_json_data(parts_path).items():
            if mod_id.startswith("_"):
                continue
            template = entry.get("assembly", {}).get("template")
            for tier_name in entry.get("tiers", {}):
                NO_RECIPE_TIERS.add(tier_name)
                if template:
                    ADVANCEMENT_TRIGGER[tier_name] = template

    smithing_path = f"{data_dir(version)}/smithing.json"
    if os.path.isfile(smithing_path):
        for tier_name, entry in return_json_data(smithing_path).items():
            if tier_name.startswith("_"):
                continue
            NO_RECIPE_TIERS.add(tier_name)
            if entry.get("template"):
                ADVANCEMENT_TRIGGER[tier_name] = entry["template"]

    rituals_path = f"{data_dir(version)}/rituals.json"
    if os.path.isfile(rituals_path):
        for tier_name in return_json_data(rituals_path):
            if tier_name.startswith("_"):
                continue
            # No bench recipe and no unlock advancement: the ritual is the only way in,
            # and an advancement would advertise a recipe book entry that does not exist.
            NO_RECIPE_TIERS.add(tier_name)
            NO_ADVANCEMENT_TIERS.add(tier_name)

def has_shaped_recipe(tier_name):
    return tier_name not in NO_RECIPE_TIERS

def has_advancement(tier_name):
    return tier_name not in NO_ADVANCEMENT_TIERS

def get_mod(mod_id):
    """The ModClass for a tier's mod.

    A tier naming a mod that mods.json has never heard of would otherwise generate files
    under guessed conventions, so fall back to the plainest ones rather than crashing —
    the run reports the tier either way through its missing sprites.
    """
    mod = mods.get(mod_id)
    if mod is None:
        mod = ModClass(mod_id=mod_id, namespace=DEFAULT_NAMESPACE,
                       loaders=PROFILE.loaders, loaded_id=mod_id)
        mods[mod_id] = mod
    return mod

def mod_loaders(mod):
    """The loaders this mod's files are written for: the ones it and the version share.

    Blue Skies has no Fabric build, so generating Fabric recipes for it ships files that
    can never load — and on 1.21.1 would create a `blue_skies` namespace in the Fabric jar
    that exists nowhere else.
    """
    return [loader for loader in PROFILE.loaders if loader in mod.loaders]

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
        mod = get_mod(tier.mod_id)
        if loader not in mod_loaders(mod) or not has_shaped_recipe(tier_name):
            continue
        for sword in SWORD_PATTERNS:
            create_shaped_recipe(
                sword=sword,
                name=tier_name,
                mod=mod,
                material=tier.material,
                handle=tier.handle,
                binder=tier.binder,
                loader=loader,
            )

def get_loader_conditions(mod, loader):
    """The "only load me if that mod is present" wrapper for one loader.

    Built from the mod's `loaded_id`, not its folder name — see ModClass.
    """
    entry = LOADER_CONDITIONS.get(loader)
    if entry is None:
        print(f"Loader not recognized or supported: {loader}")
        return None, []
    field, build = entry
    return field, [build(mod.loaded_id)]

def get_item_path(mod, name, sword):
    """The `{tier}/{weapon}` path an item is known by within its namespace.

    A mod with its own namespace has already said which mod it is by the namespace, so the
    mod id is dropped: Blue Skies' pyrope longsword is `blue_skies:pyrope/longsword`, not
    `blue_skies:blue_skies/pyrope/longsword`. Everything else shares the knavesneeds
    namespace with every other mod and has to keep the mod id to stay unique.

    Recipes, models, advancements and weapon attributes all key off this, so an item's id
    and the paths of the four files describing it cannot drift apart.
    """
    if mod.namespace != DEFAULT_NAMESPACE:
        return f"{name}/{sword}"
    return f"{mod.mod_id}/{name}/{sword}"

def get_result_item(mod, name, sword):
    return f"{mod.namespace}:{get_item_path(mod, name, sword)}"

def get_loader_root(loader):
    """The folder that `data/` and `assets/` sit directly inside, for one loader.

    Local runs stage into ./<loader>; a run given a mod project root writes into that
    project's resource tree instead.
    """
    if OUTPUT_ROOT is None:
        return loader
    return f"{OUTPUT_ROOT}/{loader}/src/main/resources"

def get_recipe_path(loader, mod, name, sword):
    return (f"{get_loader_root(loader)}/data/{mod.namespace}/{PROFILE.recipe_dir}/"
            f"{get_item_path(mod, name, sword)}.json")

def get_advancement_path(loader, mod, name, sword):
    return (f"{get_loader_root(loader)}/data/{mod.namespace}/{PROFILE.advancement_dir}/"
            f"recipes/{get_item_path(mod, name, sword)}.json")

def get_attributes_path(loader, mod, name, sword):
    return (f"{get_loader_root(loader)}/data/{mod.namespace}/weapon_attributes/"
            f"{get_item_path(mod, name, sword)}.json")

def get_model_path(loader, mod, name, sword):
    return (f"{get_loader_root(loader)}/assets/{mod.namespace}/models/{ITEM_ROOT}/"
            f"{get_item_path(mod, name, sword)}.json")

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

    Always in the knavesneeds namespace, and always keeping the full mod id, even for tiers
    whose models live under another mod's namespace and drop it — the sprites ship with this
    mod regardless of which mod the tier comes from, so they cannot borrow that namespace's
    implied identity the way a model can. See get_item_path().
    """
    return f"knavesneeds:{ITEM_ROOT}/{mod_id}/{name}/{sword}"

def get_texture_path(loader, mod_id, name, sword):
    """Where the sprite for get_texture_ref() has to land for the game to resolve it."""
    return (f"{get_loader_root(loader)}/assets/knavesneeds/textures/{ITEM_ROOT}/"
            f"{mod_id}/{name}/{sword}.png")

def find_sprite(mod_id, name, sword):
    """Locate a source sprite in common/sprites, or None if it hasn't been drawn.

    Sprite folders use two layouts (mod-scoped and tier-at-top-level) and two naming
    conventions (tier-prefixed and bare), so try each combination.

    Candidates are exact filenames built from the weapon name, which is what keeps variant
    art out: Better End's `*_head.png` alternates and the stray `*2.png` / `*3.png` drafts
    can never match, because no weapon is named `chakram_head` or `claymore2`.

    A mod whose `loaded_id` differs from its `mod_id` is looked up under both, because the
    sprite tree is shared by every version while the mod id is not: the art sits in
    `common/sprites/twilightforest/`, which is what 1.21.1 calls the mod, but 1.20.1 calls
    the same mod `twilight_forest` and would otherwise find none of it.
    """
    mod = mods.get(mod_id)
    mod_dirs = [mod_id]
    if mod is not None and mod.loaded_id != mod_id:
        mod_dirs.append(mod.loaded_id)

    candidates = []
    for mod_dir in mod_dirs:
        candidates.append(f"{SPRITES_DIR}/{mod_dir}/{name}/{name}_{sword}.png")
        candidates.append(f"{SPRITES_DIR}/{mod_dir}/{name}/{sword}.png")
    candidates.append(f"{SPRITES_DIR}/{name}/{name}_{sword}.png")
    candidates.append(f"{SPRITES_DIR}/{name}/{sword}.png")

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
            for loader in mod_loaders(get_mod(tier.mod_id)):
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

def load_thumbnail_config(path=THUMBNAIL_CONFIG):
    """Read the thumbnail's weapon and tier selectors.

    Returns (weapon, selectors, include_wooden). Raises FileNotFoundError if the file is
    absent and ValueError if it names no tiers — the tier list is required, because the
    alternative is a showcase built from whatever art happens to be in the tree.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    config = return_json_data(path)
    selectors = config.get("tiers") or []
    if not selectors:
        raise ValueError(f"{path} lists no tiers")
    return (config.get("weapon", THUMBNAIL_WEAPON), selectors,
            bool(config.get("include_wooden", False)))


def resolve_thumbnail_tiers(selectors, include_wooden=False):
    """Turn the config's selectors into (mod_id, tier_name) pairs, in the order given.

    A selector is either a mod id, meaning every tier of that mod, or "mod_id/tier" for one
    tier exactly. A bare name that is not a mod id is matched against top-level tier
    folders, which is how Blue Skies' woods and gems sit in the sprite tree.

    Wooden tiers are dropped when a selector expands a whole mod — seven near-identical
    plank sets would eat a quarter of the loop — but never when a tier is named outright.
    A wildcard gets curated; a name gets obeyed. `include_wooden` turns the filter off.

    Returns (pairs, unknown) so the caller can refuse rather than quietly showing less than
    was asked for.
    """
    discovered = discover_sprite_tiers()
    by_mod = {}
    for mod_id, tier_name in discovered:
        by_mod.setdefault(mod_id, []).append(tier_name)

    chosen, unknown, seen = [], [], set()

    def take(mod_id, tier_name):
        if (mod_id, tier_name) not in seen:
            seen.add((mod_id, tier_name))
            chosen.append((mod_id, tier_name))

    for selector in selectors:
        if "/" in selector:
            mod_id, _, tier_name = selector.partition("/")
            if (mod_id, tier_name) in discovered:
                take(mod_id, tier_name)
            else:
                unknown.append(selector)
            continue
        if selector in by_mod:
            for tier_name in by_mod[selector]:
                if include_wooden or not is_wooden_tier(tier_name):
                    take(selector, tier_name)
            continue
        matches = [(m, t) for m, t in discovered if t == selector]
        if matches:
            for pair in matches:
                take(*pair)
        else:
            unknown.append(selector)
    return chosen, unknown


def collect_thumbnail_weapons(weapon, pairs):
    """Gather `weapon`'s sprite for each selected tier, in the order the config gave.

    Returns (label, sprite_path) pairs and the tiers that had no such sprite. The label is
    the tier name rather than the weapon name, since here it is the material that changes
    from entry to entry.
    """
    weapons, missing = [], []
    for mod_id, tier_name in pairs:
        source = find_sprite(mod_id, tier_name, weapon)
        if source is None:
            missing.append(f"{mod_id}/{tier_name}" if mod_id else tier_name)
        else:
            weapons.append((tier_name, source))
    return weapons, missing

def create_thumbnail_data(selection):
    """Render the mod's showcase loop to preview/thumbnail.{gif,webp}.

    Same spin as the per-tier previews with the axes swapped — one weapon through every
    material instead of one material through every weapon — plus the logo on top.
    `selection` is (weapon, [(mod_id, tier_name)]) as resolved from THUMBNAIL_CONFIG.
    """
    global count
    preview, mode = resolve_preview_runtime()
    if preview is None:
        return

    weapon, pairs = selection
    weapons, missing = collect_thumbnail_weapons(weapon, pairs)
    if missing:
        print(f"  No {weapon} sprite for: {', '.join(missing)}")
    if not weapons:
        print(f"  No {weapon} sprites among the selected tiers, skipping the thumbnail.")
        return

    if not os.path.isfile(LOGO_PATH):
        print(f"  {LOGO_PATH} is missing, rendering the thumbnail without the logo.")

    frames = preview.create_thumbnail(weapons, THUMBNAIL_PATH, LOGO_PATH, mode)
    count = count + len(preview.FORMATS)
    formats = "/".join(preview.FORMATS)
    print(f"  {THUMBNAIL_PATH}.{{{formats}}} "
          f"({len(weapons)} materials, {frames} frames, {mode})")

def get_pattern(sword, name=None):
    """Return the 3-row grid for a weapon, honouring a tier's override if it has one.

    Entries in sword_patterns.json wrap the grid in a {"pattern": [...]} object, but
    tolerate a bare list too so either shape works. tier_patterns.json stores overrides as
    bare lists keyed tier -> weapon, letting one tier change a recipe's shape — adding or
    dropping a binder, say — without forking the whole pattern set.
    """
    override = TIER_PATTERNS.get(name, {}).get(sword) if name else None
    if override is not None:
        return override
    entry = SWORD_PATTERNS.get(sword, [])
    if isinstance(entry, dict):
        return entry.get("pattern", [])
    return entry

def get_result(mod, name, sword):
    """The recipe's `result` block, in this version's shape.

    1.20 names the item under `item` and leaves the count implicit; 1.21 renamed the field
    to `id` and writes the count out.
    """
    result = {PROFILE.result_key: get_result_item(mod, name, sword)}
    if PROFILE.result_count:
        result["count"] = 1
    return result

def create_shaped_recipe(sword, name, mod, material, handle, binder, loader):
    pattern = get_pattern(sword, name)
    condition_type, conditions = get_loader_conditions(mod, loader)

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
        "result": get_result(mod, name, sword)
    }

    write_json(get_recipe_path(loader, mod, name, sword), json_data)

# The predicate the game switches the held model on, and the transform that hides it.
# Scaling the third-person hands to zero is what "invisible" means here: the item still
# exists and still draws in the inventory and in first person, it just is not rendered in
# the hand of a player someone else is looking at.
INVISIBLE_PREDICATE = "knavesneeds:invisible"
INVISIBLE_SUFFIX = "_invisible"
INVISIBLE_DISPLAY = {
    "thirdperson_righthand": {"scale": [0, 0, 0]},
    "thirdperson_lefthand": {"scale": [0, 0, 0]},
}

def create_model_date():
    for tier_name, tier in tiers.items():
        mod = get_mod(tier.mod_id)
        for sword in SWORD_PATTERNS:

            json_data = {
                "parent" : f"knavesneeds:{ITEM_ROOT}/templates/{sword}",
                "textures" : {
                    "layer0" : get_texture_ref(tier.mod_id, tier_name, sword)
                }
            }

            hidden_data = None
            if tier.invisible_variant:
                item_path = get_item_path(mod, tier_name, sword)
                # Both models share the one sprite; only the display transform differs, so
                # the variant costs a model file and no extra art.
                hidden_data = {**json_data, "display": INVISIBLE_DISPLAY}
                json_data = {**json_data, "overrides": [{
                    "predicate": {INVISIBLE_PREDICATE: 1},
                    "model": f"{mod.namespace}:{ITEM_ROOT}/{item_path}{INVISIBLE_SUFFIX}",
                }]}

            for loader in mod_loaders(mod):
                path = get_model_path(loader, mod, tier_name, sword)
                write_json(path, json_data)
                if hidden_data is not None:
                    write_json(f"{path[:-len('.json')]}{INVISIBLE_SUFFIX}.json",
                               hidden_data)


def create_weapon_attributes_date():
    for tier_name, tier in tiers.items():
        mod = get_mod(tier.mod_id)
        for sword in SWORD_PATTERNS:

            json_data = {
                "parent": f"knavesneeds:{sword}"
            }

            for loader in mod_loaders(mod):
                write_json(get_attributes_path(loader, mod, tier_name, sword), json_data)

def get_material_predicate(material):
    """How an inventory_changed trigger names the tier's material.

    1.20 keeps items and tags in separate fields — `{"items": [id]}` against
    `{"tag": id}`. 1.21 merged them into one item-or-tag string, with `#` marking a tag.
    """
    prefix, value = str(material[0]), str(material[1])
    if PROFILE.item_predicate == "string":
        return {"items": f"#{value}" if prefix == "tag" else value}
    if prefix == "tag":
        return {"tag": value}
    return {"items": [value]}

def get_unlock_material(tier_name, tier):
    """The item the unlock advancement watches for.

    Normally the tier's own material — you mine the ore, you learn the recipe. A tier
    obtained by smithing is unlocked by its template instead, since its material never
    passes through your inventory on the way to the weapon.
    """
    trigger = ADVANCEMENT_TRIGGER.get(tier_name)
    if trigger is not None:
        return ["item", trigger]
    return tier.material

def create_unlock_data():
    for tier_name, tier in tiers.items():
        if not has_advancement(tier_name):
            continue
        mod = get_mod(tier.mod_id)
        for sword in SWORD_PATTERNS:
            result = get_result_item(mod, tier_name, sword)
            json_data = {
                "parent": "minecraft:recipes/root",
                "criteria": {
                    "has_material": {
                        "conditions": {
                            "items": [
                                get_material_predicate(
                                    get_unlock_material(tier_name, tier))
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

            for loader in mod_loaders(mod):
                # 1.21 repeats the recipe's load conditions here. Without them the unlock
                # advancement loads even when the mod it belongs to is absent, and the
                # rewards clause then points at a recipe that does not exist.
                data = json_data
                if PROFILE.conditional_advancements:
                    field, conditions = get_loader_conditions(mod, loader)
                    data = {field: conditions, **json_data}
                write_json(get_advancement_path(loader, mod, tier_name, sword), data)

#Credit to https://stackoverflow.com/questions/185936/how-to-delete-the-contents-of-a-folder
def clear_preview_data(previews, thumbnail):
    """Remove only the preview output this run is going to rebuild.

    `preview/` holds two independent things: the per-tier loops, in per-mod subfolders, and
    the thumbnail, as loose files at the top. Now that the two steps are separately opt-in,
    clearing the whole folder for a previews-only run would delete a thumbnail that run has
    no intention of regenerating.
    """
    if not os.path.isdir("preview"):
        return
    for filename in sorted(os.listdir("preview")):
        path = os.path.join("preview", filename)
        is_thumb = os.path.isfile(path) and filename.startswith(
            os.path.basename(THUMBNAIL_PATH))
        if not (thumbnail if is_thumb else previews and os.path.isdir(path)):
            continue
        try:
            shutil.rmtree(path) if os.path.isdir(path) else os.unlink(path)
        except Exception as e:
            print('Failed to delete %s. Reason: %s' % (path, e))


def generated_dirs(loader, mod, tier_name):
    """Every directory this run will write into for one tier on one loader.

    Only those: a tier the generator does not write recipes for keeps its recipe folder,
    because the recipes there are the hand-written smithing and ritual ones this tool
    cannot yet produce. Clearing exactly what the run is about to write is what makes the
    scoped clear safe — anything it skips writing, it also skips deleting.
    """
    base = get_loader_root(loader)
    item_dir = os.path.dirname(get_item_path(mod, tier_name, "any"))
    dirs = []
    if has_shaped_recipe(tier_name):
        dirs.append(f"{base}/data/{mod.namespace}/{PROFILE.recipe_dir}/{item_dir}")
    if has_advancement(tier_name):
        dirs.append(
            f"{base}/data/{mod.namespace}/{PROFILE.advancement_dir}/recipes/{item_dir}")
    dirs.append(f"{base}/data/{mod.namespace}/weapon_attributes/{item_dir}")
    dirs.append(f"{base}/assets/{mod.namespace}/models/{ITEM_ROOT}/{item_dir}")
    dirs.append(f"{base}/assets/knavesneeds/textures/{ITEM_ROOT}/{mod.mod_id}/{tier_name}")
    return dirs


def clear_old_data():
    """Remove the previous run's output, and only that.

    A local run stages into ./<loader>, which holds nothing but generated files, so those
    folders are emptied wholesale — that is what drops a tier you have since deleted.

    A run writing into a mod project cannot do the same: those trees also hold the hand
    written lang files, item model templates and loader metadata the mod is built from.
    So it deletes per tier instead, walking the five directories `generated_dirs()` names
    and leaving everything else untouched. The cost is that a tier removed from tiers.json
    is no longer cleaned up, since nothing left in the data still names it.
    """
    if OUTPUT_ROOT is None:
        for loader in PROFILE.loaders:
            if not os.path.isdir(loader):
                continue
            for filename in os.listdir(loader):
                file_path = os.path.join(loader, filename)
                try:
                    if os.path.isfile(file_path) or os.path.islink(file_path):
                        os.unlink(file_path)
                    elif os.path.isdir(file_path):
                        shutil.rmtree(file_path)
                except Exception as e:
                    print('Failed to delete %s. Reason: %s' % (file_path, e))
        return

    cleared = 0
    for tier_name, tier in tiers.items():
        mod = get_mod(tier.mod_id)
        for loader in mod_loaders(mod):
            for path in generated_dirs(loader, mod, tier_name):
                if not os.path.isdir(path):
                    continue
                try:
                    shutil.rmtree(path)
                    cleared += 1
                except Exception as e:
                    print('Failed to delete %s. Reason: %s' % (path, e))
    print(f"  Cleared {cleared} generated folder(s) under {OUTPUT_ROOT}.")



def log_and_return_time(message, start_time):
    elapsed = (time.time() - start_time) * 1000
    print(f"{message} (took {elapsed:.2f}ms)")
    return time.time()

PREVIEW_FLAGS = ("--previews", "--preview", "-p")
THUMBNAIL_FLAGS = ("--thumbnail", "-t")
ALL_FLAGS = ("--all", "-a")
VERSION_FLAGS = ("--mc", "-m")
USAGE = ("usage: python main.py [--mc <version>] [<mod-project-root>] "
         "[--previews] [--thumbnail] [--all]")

def parse_args(args):
    """Split the command line into (version, output_root, previews, thumbnail).

    A bare word is the mod project root to generate into; leaving it off stages to the
    local ./<loader> folders instead. Anything unrecognised is rejected with exit 2 rather
    than ignored, so a typo'd flag cannot quietly give a run without the output it asked
    for — and, now that a run can write into a real mod checkout, cannot quietly give a run
    that writes somewhere other than where it was pointed.
    """
    version = DEFAULT_VERSION
    output_root = None
    everything = False
    previews = thumbnail = False
    unknown, extra_paths = [], []

    index = 0
    while index < len(args):
        arg = args[index]
        if arg in VERSION_FLAGS:
            index += 1
            if index >= len(args):
                print(f"{arg} needs a version, one of: {', '.join(VERSION_PROFILES)}")
                print(USAGE)
                raise SystemExit(2)
            version = args[index]
        elif arg.startswith("--mc="):
            version = arg.partition("=")[2]
        elif arg in ALL_FLAGS:
            everything = True
        elif arg in PREVIEW_FLAGS:
            previews = True
        elif arg in THUMBNAIL_FLAGS:
            thumbnail = True
        elif arg.startswith("-"):
            unknown.append(arg)
        elif output_root is None:
            output_root = arg
        else:
            extra_paths.append(arg)
        index += 1

    if unknown:
        print(f"Unknown argument(s): {', '.join(unknown)}")
        print(USAGE)
        raise SystemExit(2)
    if extra_paths:
        print(f"Only one output root can be given; also got: {', '.join(extra_paths)}")
        print(USAGE)
        raise SystemExit(2)
    if version not in VERSION_PROFILES:
        print(f"Unknown Minecraft version: {version}")
        print(f"Known versions: {', '.join(VERSION_PROFILES)}")
        raise SystemExit(2)
    if output_root is not None and not os.path.isdir(output_root):
        print(f"Output root does not exist: {output_root}")
        print("Give the multiloader mod project root, or omit it to stage locally.")
        raise SystemExit(2)

    return version, output_root, everything or previews, everything or thumbnail

if __name__ == '__main__':
    import sys

    # Both render steps are opt-in because they cost minutes while the JSON and textures --
    # the part a mod build actually consumes -- take about a second. Rebuilding 39 tiers of
    # spin animation to change one recipe is a bad default. They are separately opt-in
    # because they answer different questions and neither implies the other.
    MC_VERSION, OUTPUT_ROOT, render_previews, render_thumbnail = parse_args(sys.argv[1:])
    PROFILE = VERSION_PROFILES[MC_VERSION]

    print(f"Starting data generation for Minecraft {MC_VERSION} "
          f"({'/'.join(PROFILE.loaders)})...")
    if OUTPUT_ROOT is None:
        print(f"  Staging locally into ./{', ./'.join(PROFILE.loaders)}")
    else:
        print(f"  Writing into {OUTPUT_ROOT}")
    start_time = time.time()

    load_mods(f"{data_dir(MC_VERSION)}/mods.json")
    load_crafting_rules(MC_VERSION)
    start_time = log_and_return_time(
        f"Loaded {len(mods)} mod profile(s), {len(NO_RECIPE_TIERS)} non-crafted tier(s)",
        start_time)

    keys = load_keys(f"{data_dir(MC_VERSION)}/keys.json")
    start_time = log_and_return_time("Loaded keys/ingredients data", start_time)

    load_tiers(f"{data_dir(MC_VERSION)}/tiers.json", keys)
    start_time = log_and_return_time(f"Loaded {len(tiers)} tiers", start_time)

    SWORD_PATTERNS = return_json_data(f"{patterns_dir(MC_VERSION)}/sword_patterns.json")
    # Per-tier overrides are optional; a version that has none just has an empty file.
    overrides_path = f"{patterns_dir(MC_VERSION)}/tier_patterns.json"
    TIER_PATTERNS = return_json_data(overrides_path) if os.path.isfile(overrides_path) else {}
    overridden = sum(len(swords) for swords in TIER_PATTERNS.values())
    start_time = log_and_return_time(
        f"Loaded {len(SWORD_PATTERNS)} patterns ({overridden} tier override(s))", start_time)

    # Resolved before anything is cleared or written, so a thumbnail that was asked for and
    # cannot be built fails with nothing half-generated behind it.
    thumbnail_selection = None
    if render_thumbnail:
        try:
            weapon, selectors, include_wooden = load_thumbnail_config()
        except FileNotFoundError:
            print()
            print(f"{THUMBNAIL_CONFIG} is missing, and the thumbnail needs it: it says "
                  f"which tiers belong to the mod being advertised.")
            print('  example: {"weapon": "chakram", "tiers": ["arpg_core"]}')
            raise SystemExit(2)
        except ValueError as e:
            print()
            print(f"{e}. The thumbnail needs an explicit tier list.")
            raise SystemExit(2)
        pairs, unresolved = resolve_thumbnail_tiers(selectors, include_wooden)
        if unresolved:
            print()
            print(f"{THUMBNAIL_CONFIG}: no sprite folder for {', '.join(unresolved)}")
            raise SystemExit(2)
        thumbnail_selection = (weapon, pairs)
        start_time = log_and_return_time(
            f"Resolved {len(pairs)} thumbnail tier(s)", start_time)

    clear_old_data()
    clear_preview_data(render_previews, render_thumbnail)
    start_time = log_and_return_time("Cleared old data", start_time)

    for mc_loader in PROFILE.loaders:
        create_recipe_data(mc_loader)
        start_time = log_and_return_time(
            f"Made recipes for {mc_loader.capitalize()}", start_time)

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
    else:
        print(f"Skipped preview GIFs (pass {PREVIEW_FLAGS[0]} to render them).")

    if render_thumbnail:
        print("Rendering mod thumbnail...")
        create_thumbnail_data(thumbnail_selection)
        start_time = log_and_return_time("Rendered mod thumbnail", start_time)
    else:
        print(f"Skipped mod thumbnail (pass {THUMBNAIL_FLAGS[0]} to render it).")

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
