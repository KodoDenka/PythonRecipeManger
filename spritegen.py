"""Sprite generation from blank templates and material palettes.

The existing art in `common/sprites/` is, for the most part, one drawing per weapon
recoloured per material. This module makes that relationship explicit so new materials
can be drawn by choosing a palette instead of repainting fifteen sprites:

- `extract()` reads the existing sprites and writes a library of **blanks** to
  `common/blanks/` — one neutral, greyscale-ramped PNG per weapon per silhouette — plus
  the palette each existing tier used, to `common/data/palettes.json`.
- `render()` takes a blank and a palette and produces a finished sprite.

Nothing here overwrites `common/sprites/`. Extraction only reads it, and generated sprites
go to `GENERATED_DIR`. The hand-drawn art stays the source of truth for every tier that
already has it; this is for the tiers that do not.

Why a palette swap rather than a tint: tinting multiplies a single hue across the whole
ramp, so it can only ever produce a colour-shifted copy of the reference material — the
darks stay proportionally dark and the ramp keeps the reference's contrast curve. A real
material has its own ramp: `deorum` is a bright yellow metal with a long light end,
`warden` is dark and low-contrast. Each shade is chosen independently here, which is why
`Palette` stores a list of colours per family rather than one colour plus a curve.

Two shade families are recognised, and a palette sets each independently:

- `material` — the shades that change with the tier. Seven of them on the standard blank.
- `handle` — the grip. Four shades. 22 of the 39 tiers share the same wooden grip
  (`DEFAULT_HANDLE`), so a palette may omit it and inherit that, but 17 tiers do recolour
  it and they need their own.

Needs Pillow. `main.py` does not import this — sprite generation is an authoring step run
by hand, not part of the per-run JSON pipeline.
"""

import json
import os
import colorsys
from dataclasses import dataclass, field

SPRITES_DIR = "common/sprites"
BLANKS_DIR = "common/blanks"
PALETTES_PATH = "common/data/palettes.json"
# Hand-authored palettes live apart from the extracted ones because `extract` rewrites
# PALETTES_PATH wholesale -- anything typed by hand in there would be lost on the next run.
CUSTOM_PALETTES_PATH = "common/data/palettes_custom.json"
BLANKS_INDEX = "common/blanks/blanks.json"
# Generated sprites land here rather than in common/sprites, so a run can never clobber
# hand-drawn art. Copy out of it once a tier looks right.
GENERATED_DIR = "generated_sprites"

# The wooden grip shared by 22 of the 39 tiers, darkest first. A palette that omits a
# handle ramp inherits this, which is what keeps a new tier's palette down to the seven
# material shades that actually distinguish it.
DEFAULT_HANDLE = ["#281e0b", "#493615", "#684e1e", "#896727"]

# A slot is assigned to `handle` when this fraction of the tiers drawing a blank agree on
# one exact colour for it. The grip is drawn identically across tiers that share it, while
# material shades differ in every tier, so agreement separates the two families cleanly.
# Below 1.0 because a handful of tiers restyle the grip without changing the silhouette.
AGREEMENT = 0.6

# Upper bound on distinct shades in one blank. The standard blank uses 11 and needs no
# capping; greathammer is anti-aliased and runs to ~250, most of which are near-duplicates
# from the same ramp. Merging those into a bounded ramp is what makes a detailed sprite
# palette-swappable at all — a 250-entry palette is not something anyone would author by
# hand. Also keeps every slot's grey distinct in the blank PNG, since the ramp below has
# to fit inside BLANK_GREY_RANGE.
MAX_SLOTS = 48

# Grey range used to draw material slots in a blank. Bounded away from pure black and
# white so the blank still reads as a weapon on either page background, and wide enough
# that MAX_SLOTS shades stay visually distinct.
BLANK_GREY_RANGE = (0x30, 0xF0)

# Pixels this faint are treated as fully transparent. The art carries a few hundred stray
# near-zero-alpha texels -- one tier leaves a 6px alpha-5 smudge on a single sprite -- and
# left alone each becomes its own shade and lands in every palette extracted from it. Real
# translucency in the set is alpha 106 and up (the `translucent` tier draws at 164/165), so
# nothing intended survives below this.
ALPHA_FLOOR = 32

# How many stops an extracted palette is allowed. Separate from MAX_SLOTS, which bounds a
# blank's detail: a blank may carry 48 shades and still render from a 12-stop palette,
# because slots sample the ramp rather than index it. Kept small because a palette is meant
# to be typed out by hand for a new material -- pooling every weapon's shades untrimmed
# gives a clean tier like `deorum` a 37-stop ramp, which is nobody's idea of authorable.
MATERIAL_STOPS = 12
HANDLE_STOPS = 6

WEAPONS_PATH = "common/patterns/sword_patterns.json"


@dataclass(frozen=True, slots=True)
class Slot:
    """One recolourable shade in a blank.

    `family` is "material" or "handle"; `position` is where the shade sits on that
    family's ramp, 0.0 darkest to 1.0 lightest. Position rather than an index because a
    blank with 30 shades has to render from a palette that only defines 7 — the ramp is
    sampled, not indexed. `alpha` is carried per slot so partially transparent art (the
    `translucent` tier) survives a recolour.
    """
    key: tuple[int, int, int]  # the grey this slot is drawn as in the blank PNG
    family: str
    position: float
    alpha: int = 255


@dataclass(slots=True)
class Blank:
    weapon: str
    variant: str
    size: tuple[int, int]
    slots: list[Slot] = field(default_factory=list)
    # tiers whose existing art this blank was derived from, for provenance
    sources: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Palette:
    """A material's shades, darkest first. `handle` defaults to the shared wooden grip.

    An `accent` ramp makes the material two-tone: below `split` the body is read off
    `material`, above it off `accent`, with `blend` worth of crossfade either side so the
    changeover is not a hard line. Because slot positions track how lit a texel is, the
    accent lands on edges, top faces and outer curves -- a glowing edge, not a painted
    part. Colouring one *specific* part instead would mean authoring the accent per slot
    in the blanks, which the extraction cannot infer: measured across all 39 tiers, the
    existing art is single-tone plus the shared grip, so there is nothing to learn from.
    """
    material: list[str]
    handle: list[str] = field(default_factory=lambda: list(DEFAULT_HANDLE))
    accent: list[str] | None = None
    split: float = 0.62
    blend: float = 0.10

    def shade(self, position):
        """The colour for a material slot at `position`, two-tone aware."""
        if not self.accent:
            return sample_ramp(self.material, position)
        split = min(0.999, max(0.001, self.split))
        body_at = lambda p: sample_ramp(self.material, min(1.0, p / split))
        if position <= split - self.blend:
            return body_at(position)
        accent = sample_ramp(self.accent, min(1.0, max(0.0, (position - split) / (1 - split))))
        if position >= split + self.blend or self.blend <= 0:
            return accent
        t = (position - (split - self.blend)) / (2 * self.blend)
        return tuple(round(b + (a - b) * t) for b, a in zip(body_at(position), accent))


# --- colour helpers ----------------------------------------------------------------

def hex_to_rgb(value):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def rgb_to_hex(rgb):
    return "#%02x%02x%02x" % tuple(int(round(c)) for c in rgb[:3])


def luminance(rgb):
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def sample_ramp(ramp, position):
    """Read a colour off a ramp at `position` (0..1), interpolating between stops.

    Blanks carry more shades than a palette defines, so the ramp has to be resampled
    rather than indexed. Interpolation happens in HLS: a straight RGB blend between two
    stops of a saturated ramp cuts through the desaturated middle of the colour cube and
    the midtones come out muddy, which is exactly where a weapon's readable shading is.
    """
    if not ramp:
        raise ValueError("empty ramp")
    if len(ramp) == 1:
        return hex_to_rgb(ramp[0])

    stops = [hex_to_rgb(c) for c in ramp]
    scaled = max(0.0, min(1.0, position)) * (len(stops) - 1)
    low = int(scaled)
    high = min(low + 1, len(stops) - 1)
    t = scaled - low
    if low == high or t == 0:
        return stops[low]

    a = colorsys.rgb_to_hls(*[c / 255 for c in stops[low]])
    b = colorsys.rgb_to_hls(*[c / 255 for c in stops[high]])
    # Hue is circular: blending 350deg to 10deg the short way crosses red, the long way
    # crosses the whole wheel and produces a colour from neither stop.
    hue_delta = (b[0] - a[0] + 0.5) % 1.0 - 0.5
    blended = colorsys.hls_to_rgb(
        (a[0] + hue_delta * t) % 1.0,
        a[1] + (b[1] - a[1]) * t,
        a[2] + (b[2] - a[2]) * t,
    )
    return tuple(int(round(c * 255)) for c in blended)


# --- sprite discovery --------------------------------------------------------------

def load_weapons():
    with open(WEAPONS_PATH, "r", encoding="utf-8") as handle:
        return list(json.load(handle).keys())


def discover_sprites(weapons):
    """Map (tier, weapon) to a sprite path across all four folder layouts.

    Same exact-filename rule as `main.py:find_sprite()` — candidates are built from the
    weapon name, so the `*_head.png` alternates and `*2.png` drafts sitting in several
    folders can never match.
    """
    found = {}
    for root, _, files in os.walk(SPRITES_DIR):
        names = {f for f in files if f.lower().endswith(".png")}
        if not names:
            continue
        tier = os.path.relpath(root, SPRITES_DIR).replace(os.sep, "/")
        leaf = os.path.basename(root)
        for weapon in weapons:
            for candidate in (f"{leaf}_{weapon}.png", f"{weapon}.png"):
                if candidate in names:
                    found[(tier, weapon)] = os.path.join(root, candidate)
                    break
    return found


def _pixels(image):
    """RGBA tuples for an image. Via tobytes() because Image.getdata() is deprecated."""
    raw = image.convert("RGBA").tobytes()
    return [tuple(raw[i:i + 4]) for i in range(0, len(raw), 4)]


_READ_CACHE = {}


def read_rgba(path):
    """Load a sprite as a flat list of RGBA tuples plus its size.

    Fully transparent pixels are flattened to a single value: PNGs carry whatever RGB was
    under a cleared pixel, and those invisible differences would otherwise split slots and
    make identical silhouettes compare as different.
    """
    if path in _READ_CACHE:
        return _READ_CACHE[path]

    from PIL import Image

    image = Image.open(path).convert("RGBA")
    pixels = [(0, 0, 0, 0) if p[3] < ALPHA_FLOOR else p for p in _pixels(image)]
    _READ_CACHE[path] = (pixels, image.size)
    return _READ_CACHE[path]


# --- extraction --------------------------------------------------------------------

def _silhouette(pixels):
    return tuple(p[3] > 0 for p in pixels)


def _colour_counts(pixels):
    counts = {}
    for p in pixels:
        if p[3]:
            counts[p] = counts.get(p, 0) + 1
    return counts


def _merge_to_limit(counts, limit):
    """Reduce a colour set to at most `limit` shades by merging nearest neighbours.

    Ordered by luminance and repeatedly collapsing the closest adjacent pair, weighted by
    pixel count so a shade covering one pixel is merged before one covering fifty. Only
    the anti-aliased sprites reach this; the standard 11-shade blank passes through
    untouched.
    """
    shades = sorted(counts, key=lambda c: (luminance(c), c))
    if len(shades) <= limit:
        return {c: c for c in shades}

    groups = [[c] for c in shades]
    while len(groups) > limit:
        best, best_cost = None, None
        for i in range(len(groups) - 1):
            left, right = groups[i][-1], groups[i + 1][0]
            weight = min(
                sum(counts[c] for c in groups[i]),
                sum(counts[c] for c in groups[i + 1]),
            )
            cost = abs(luminance(left) - luminance(right)) * weight
            if best_cost is None or cost < best_cost:
                best, best_cost = i, cost
        groups[best:best + 2] = [groups[best] + groups[best + 1]]

    mapping = {}
    for group in groups:
        # the group's most-used shade stands in for it, so the merged sprite keeps a
        # colour that was actually drawn rather than an invented average
        keeper = max(group, key=lambda c: counts[c])
        for c in group:
            mapping[c] = keeper
    return mapping


def _assign_families(members, slot_colours, known_handles=None):
    """Split a blank's shades into the `material` and `handle` families.

    A shade the tiers agree on is the grip: tiers that share the wooden handle draw it
    with identical pixels, while every material shade differs from tier to tier. Where
    there is only one source tier there is nothing to compare, so fall back to matching
    against the known shared grip.
    """
    families = {}
    for slot, per_tier in slot_colours.items():
        if len(members) > 1:
            counts = {}
            for colour in per_tier.values():
                counts[colour] = counts.get(colour, 0) + 1
            top, hits = max(counts.items(), key=lambda kv: kv[1])
            families[slot] = "handle" if hits >= AGREEMENT * len(members) else "material"
        else:
            # Only one tier drew this silhouette, so there is nothing to compare against.
            # Fall back to the grip that tier used on the silhouettes it shares with
            # others, which a first pass over the multi-tier blanks has already learned.
            only = next(iter(per_tier.values()))
            grip = known_handles or {hex_to_rgb(c) for c in DEFAULT_HANDLE}
            families[slot] = "handle" if only[:3] in grip else "material"
    return families


def _representative(members, weapon, sprites):
    """Pick the tier whose drawing defines the blank's structure.

    The modal shade count, not the first or the simplest. Most tiers render a weapon with
    the same number of shades and that count is the intended structure; the outliers are
    anti-aliased repaints on one side and, on the other, tiers whose palette happened to
    repeat a colour and so collapsed two shades into one. Either extreme would bake a
    wrong structure into the blank -- over-segmented from the first, missing a
    distinction from the second.

    Ties on that count are broken by brightness, not alphabetically. The modal count says
    how many shades the drawing uses but nothing about *where* on the ramp they sit, and
    slot positions are read off the representative alone -- so a tier that draws the
    weapon at an extreme of the group's brightness hands every other tier its bias. That
    is not hypothetical: chakram's mode is five shades, and the alphabetically-first tier
    holding it was `amethyst_imbuement/glowing`, the brightest of the thirty sharing the
    silhouette. Its five slots all sat high on the ramp and every tier's chakram rendered
    27% brighter than the art it came from. Picking the tier nearest the group's median
    brightness brings that to within 1%.
    """
    counts = {}
    brightness = {}
    for tier in members:
        pixels, _ = read_rgba(sprites[(tier, weapon)])
        counts[tier] = len(_colour_counts(pixels))
        lit = [luminance(p) for p in pixels if p[3] > ALPHA_FLOOR]
        if lit:
            brightness[tier] = sum(lit) / len(lit)
    tally = {}
    for n in counts.values():
        tally[n] = tally.get(n, 0) + 1
    modal = max(tally.items(), key=lambda kv: (kv[1], -kv[0]))[0]
    tied = sorted(t for t in members if counts[t] == modal)
    rated = [t for t in tied if t in brightness]
    if not rated:
        return tied[0]
    ordered = sorted(brightness.values())
    median = ordered[len(ordered) // 2]
    return min(rated, key=lambda t: abs(brightness[t] - median))


def _tier_ramps(weapons, sprites, handles):
    """The full ramp each tier paints with, pooled across all fifteen of its weapons.

    A tier is one material, so its shades are a property of the tier, not of the weapon --
    `dusk_wood` draws its whole set from seven material shades and four grip shades. Slot
    positions are indices into this pooled ramp, which is what lets one palette drive every
    weapon: a six-shade chakram takes six places on the same ramp an eleven-shade longsword
    spreads across, instead of each stretching to fill it.
    """
    ramps = {}
    for (tier, weapon), path in sprites.items():
        if weapon not in weapons:
            continue
        pixels, _ = read_rgba(path)
        grip = handles.get(tier, set())
        bucket = ramps.setdefault(tier, {"material": {}, "handle": {}})
        for colour, count in _colour_counts(pixels).items():
            family = "handle" if colour[:3] in grip else "material"
            bucket[family][colour] = bucket[family].get(colour, 0) + count

    out = {}
    for tier, families in ramps.items():
        out[tier] = {}
        for family, counts in families.items():
            if not counts:
                out[tier][family] = []
                continue
            stops = MATERIAL_STOPS if family == "material" else HANDLE_STOPS
            merge = _merge_to_limit(counts, stops)
            kept = {merge[c] for c in counts}
            out[tier][family] = sorted(kept, key=lambda c: (luminance(c), c))
    return out


def _ramp_position(shade, ramp):
    """Where a shade sits on its tier's ramp, 0.0 darkest to 1.0 lightest."""
    if not ramp:
        return 0.0
    if len(ramp) == 1:
        return 0.0
    best = min(range(len(ramp)),
               key=lambda i: sum((a - b) ** 2 for a, b in zip(shade[:3], ramp[i][:3])))
    return best / (len(ramp) - 1)


def build_blank(weapon, variant, members, sprites, limit=MAX_SLOTS,
                known_handles=None, ramps=None):
    """Derive one blank from the tiers that drew a weapon with the same silhouette."""
    representative = _representative(members, weapon, sprites)
    pixels, size = read_rgba(sprites[(representative, weapon)])
    counts = _colour_counts(pixels)
    merge = _merge_to_limit(counts, limit)
    canonical = [p if p[3] == 0 else merge[p] for p in pixels]

    shades = sorted({p for p in canonical if p[3]}, key=lambda c: (luminance(c), c))

    # what each source tier drew at each of the representative's shades, which is both the
    # family signal and the extracted palette
    slot_colours = {shade: {} for shade in shades}
    for tier in members:
        other, other_size = read_rgba(sprites[(tier, weapon)])
        if other_size != size:
            continue
        tally = {shade: {} for shade in shades}
        for base, actual in zip(canonical, other):
            if base[3] == 0 or actual[3] == 0:
                continue
            bucket = tally[base]
            bucket[actual] = bucket.get(actual, 0) + 1
        for shade, bucket in tally.items():
            if bucket:
                slot_colours[shade][tier] = max(bucket.items(), key=lambda kv: kv[1])[0]

    families = _assign_families(members, slot_colours, known_handles)
    ramp = (ramps or {}).get(representative, {})
    slots = []
    for family in ("material", "handle"):
        for shade in [s for s in shades if families[s] == family]:
            slots.append(Slot(key=shade[:3], family=family, alpha=shade[3],
                              position=_ramp_position(shade, ramp.get(family, []))))

    blank = Blank(weapon=weapon, variant=variant, size=size, sources=list(members))
    blank.slots = slots
    return blank, canonical, shades, slot_colours, families


def _blank_grey(index, total):
    low, high = BLANK_GREY_RANGE
    if total <= 1:
        return (high, high, high)
    step = low + (high - low) * index / (total - 1)
    value = int(round(step))
    return (value, value, value)


def _display_map(blank):
    """Colour each slot is drawn as in the blank PNG, keyed by (rgb, alpha).

    Material shades become a neutral grey ramp; the grip keeps the shared wood, so a blank
    still reads as a weapon with a handle rather than a uniform grey blob. Keyed on alpha
    too, since a translucent shade can share its RGB with an opaque one.

    Spread by index rather than by ramp position: `render()` recovers a slot by looking its
    colour up in this map, so two slots sharing a colour would make one of them
    unrecoverable. Positions collide whenever a blank carries more shades than its tier's
    ramp has stops; indices cannot.
    """
    display, used = {}, set()
    for family in ("material", "handle"):
        shades = [s for s in blank.slots if s.family == family]
        for index, slot in enumerate(shades):
            if family == "material":
                colour = _blank_grey(index, len(shades))
            else:
                spread = index / (len(shades) - 1) if len(shades) > 1 else 0.0
                colour = sample_ramp(DEFAULT_HANDLE, spread)
            # rounding can still land two neighbours on one value in a crowded ramp
            while colour in used:
                colour = (colour[0], colour[1], min(colour[2] + 1, 255))
            used.add(colour)
            display[(slot.key, slot.alpha)] = colour + (slot.alpha,)
    return display


def write_blank_png(blank, canonical, path):
    """Draw the blank.

    The PNG is the artefact worth looking at, but it is not what `render()` reads back --
    the slot table in `blanks.json` is, keyed by these exact colours. Greys are spread
    across `BLANK_GREY_RANGE` so no two material slots collide, which is what keeps that
    lookup total.
    """
    from PIL import Image

    display = _display_map(blank)
    image = Image.new("RGBA", blank.size)
    image.putdata([(0, 0, 0, 0) if p[3] == 0 else display[(p[:3], p[3])]
                   for p in canonical])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    image.save(path)
    return display


def _group_silhouettes(weapon, drawn):
    """Split the tiers that drew a weapon into groups sharing one exact silhouette.

    Silhouette is the grouping axis because it is the thing a palette cannot change: two
    tiers with the same outline are the same drawing recoloured, and two with different
    outlines are different drawings that both deserve a blank.
    """
    groups = {}
    for tier in sorted(drawn):
        pixels, size = read_rgba(drawn[tier])
        groups.setdefault((size, _silhouette(pixels)), []).append(tier)
    # largest group first: that is the drawing most tiers share, and it becomes "base"
    return sorted(groups.values(), key=lambda m: (-len(m), m[0]))


def _learn_handles(weapons, sprites):
    """Work out which colours each tier uses for the grip, before any blank is written.

    Only silhouettes drawn by several tiers can reveal this, by agreement. Tiers that also
    own a private silhouette need the answer carried over, since a group of one has
    nothing to agree with -- that is what this pass is for.
    """
    handles = {}
    for weapon in weapons:
        drawn = {tier: path for (tier, w), path in sprites.items() if w == weapon}
        if not drawn:
            continue
        for members in _group_silhouettes(weapon, drawn):
            if len(members) < 2:
                continue
            _, _, shades, slot_colours, families = build_blank(
                weapon, "probe", members, sprites)
            for shade in shades:
                if families[shade] != "handle":
                    continue
                for tier, colour in slot_colours[shade].items():
                    handles.setdefault(tier, set()).add(colour[:3])
    return handles


def extract(limit=MAX_SLOTS):
    """Read `common/sprites/` and write the blank library and the extracted palettes."""
    weapons = load_weapons()
    sprites = discover_sprites(weapons)
    tiers = sorted({tier for tier, _ in sprites})
    print(f"found {len(sprites)} sprites across {len(tiers)} tiers")

    handles = _learn_handles(weapons, sprites)
    ramps = _tier_ramps(weapons, sprites, handles)
    print(f"learned grip colours for {len(handles)} tiers")

    index = {"weapons": {}}
    for weapon in weapons:
        drawn = {tier: path for (tier, w), path in sprites.items() if w == weapon}
        if not drawn:
            continue

        variants = {}
        for rank, members in enumerate(_group_silhouettes(weapon, drawn)):
            # the rest are named after a tier that draws them, so a silhouette is
            # recognisable by the material it came from when picking one to build on
            variant = "base" if rank == 0 else members[0].replace("/", "_")
            known = handles.get(members[0]) if len(members) == 1 else None
            blank, canonical, shades, slot_colours, families = build_blank(
                weapon, variant, members, sprites, limit, known, ramps)
            path = f"{BLANKS_DIR}/{weapon}/{variant}.png"
            display = write_blank_png(blank, canonical, path)

            variants[variant] = {
                "size": list(blank.size),
                "sources": blank.sources,
                "slots": [
                    {
                        "colour": rgb_to_hex(display[(s.key, s.alpha)]),
                        "family": s.family,
                        "position": round(s.position, 4),
                        "alpha": s.alpha,
                    }
                    for s in blank.slots
                ],
            }

        index["weapons"][weapon] = variants
        print(f"  {weapon:12s} {len(variants):2d} blank(s): "
              + ", ".join(f"{v}({len(s['slots'])})" for v, s in variants.items()))

    os.makedirs(os.path.dirname(BLANKS_INDEX), exist_ok=True)
    with open(BLANKS_INDEX, "w", encoding="utf-8") as handle:
        json.dump(index, handle, indent=2)

    tidy = {}
    for tier in sorted(ramps):
        material = [rgb_to_hex(c) for c in ramps[tier]["material"]]
        handle = [rgb_to_hex(c) for c in ramps[tier]["handle"]]
        out = {"material": material}
        # the shared wooden grip is the default, so only tiers that restyle it say so
        if handle and handle != DEFAULT_HANDLE:
            out["handle"] = handle
        tidy[tier] = out
    os.makedirs(os.path.dirname(PALETTES_PATH), exist_ok=True)
    with open(PALETTES_PATH, "w", encoding="utf-8") as handle:
        json.dump(tidy, handle, indent=2)

    print()
    print(f"wrote {BLANKS_INDEX} and {PALETTES_PATH}")
    return index, tidy


# --- rendering ---------------------------------------------------------------------

def load_index():
    with open(BLANKS_INDEX, "r", encoding="utf-8") as handle:
        return json.load(handle)


def load_palettes():
    """Extracted palettes, with any hand-authored ones layered over the top."""
    raw = {}
    for path in (PALETTES_PATH, CUSTOM_PALETTES_PATH):
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as handle:
            raw.update(json.load(handle))
    palettes = {}
    for name, entry in raw.items():
        palettes[name] = Palette(
            material=entry["material"],
            handle=entry.get("handle") or list(DEFAULT_HANDLE),
            accent=entry.get("accent"),
            split=entry.get("split", 0.62),
            blend=entry.get("blend", 0.10),
        )
    return palettes


def render(weapon, variant, palette, index=None):
    """Recolour a blank with a palette and return the finished sprite."""
    from PIL import Image

    index = index or load_index()
    try:
        spec = index["weapons"][weapon][variant]
    except KeyError:
        raise KeyError(f"no blank {weapon}/{variant}; run `python spritegen.py extract`")

    lookup = {}
    for slot in spec["slots"]:
        if slot["family"] == "material":
            colour = palette.shade(slot["position"])
        else:
            colour = sample_ramp(palette.handle, slot["position"])
        lookup[hex_to_rgb(slot["colour"]) + (slot["alpha"],)] = tuple(colour) + (slot["alpha"],)

    blank = Image.open(f"{BLANKS_DIR}/{weapon}/{variant}.png").convert("RGBA")
    out = []
    for pixel in _pixels(blank):
        if pixel[3] == 0:
            out.append((0, 0, 0, 0))
            continue
        recoloured = lookup.get(pixel)
        if recoloured is None:
            # a blank should only ever contain its own slot colours; anything else means
            # the PNG and blanks.json have drifted apart
            raise ValueError(f"{weapon}/{variant}: colour {rgb_to_hex(pixel)} has no slot")
        out.append(recoloured)

    image = Image.new("RGBA", blank.size)
    image.putdata(out)
    return image


def generate(tier, palette, variants=None, out_dir=None):
    """Render a whole weapon set for one material into GENERATED_DIR."""
    index = load_index()
    variants = variants or {}
    out_dir = out_dir or os.path.join(GENERATED_DIR, tier.replace("/", os.sep))
    os.makedirs(out_dir, exist_ok=True)

    written = []
    for weapon, available in index["weapons"].items():
        variant = variants.get(weapon, "base")
        if variant not in available:
            print(f"  ! {weapon}: no variant {variant!r}, skipping")
            continue
        image = render(weapon, variant, palette, index)
        path = os.path.join(out_dir, f"{weapon}.png")
        image.save(path)
        written.append(path)
    print(f"wrote {len(written)} sprites to {out_dir}")
    return written


# --- fidelity check ----------------------------------------------------------------

def verify(limit=None):
    """Re-render every existing sprite from its blank and report how close it lands.

    A blank plus an extracted palette is a lossy description of hand-drawn art — merged
    shades and per-tier touch-ups do not survive the round trip. This says by how much, so
    a blank that has drifted too far from the art to be worth generating from is visible
    rather than assumed.
    """
    index = load_index()
    palettes = load_palettes()
    weapons = load_weapons()
    sprites = discover_sprites(weapons)

    rows = []
    for weapon, variants in index["weapons"].items():
        for variant, spec in variants.items():
            for tier in spec["sources"]:
                if tier not in palettes or (tier, weapon) not in sprites:
                    continue
                original, size = read_rgba(sprites[(tier, weapon)])
                made = _pixels(render(weapon, variant, palettes[tier], index))
                if len(made) != len(original):
                    continue
                opaque = sum(1 for p in original if p[3])
                if not opaque:
                    continue
                error = sum(
                    max(abs(a - b) for a, b in zip(o[:3], m[:3]))
                    for o, m in zip(original, made) if o[3] or m[3]
                )
                exact = sum(1 for o, m in zip(original, made) if o == m)
                rows.append((error / opaque, 100 * exact / len(original), tier, weapon,
                             variant))

    rows.sort()
    print(f"{'tier':34s} {'weapon':12s} {'variant':16s} {'mean err':>8s} {'exact':>7s}")
    for err, exact, tier, weapon, variant in (rows if limit is None else rows[-limit:]):
        print(f"{tier:34s} {weapon:12s} {variant:16s} {err:8.1f} {exact:6.1f}%")
    if rows:
        mean = sum(r[0] for r in rows) / len(rows)
        perfect = sum(1 for r in rows if r[0] == 0)
        print(f"\n{len(rows)} sprites, mean channel error {mean:.1f}/255, "
              f"{perfect} reproduced exactly")
    return rows


# --- cli ---------------------------------------------------------------------------

def main(argv):
    command = argv[1] if len(argv) > 1 else "help"

    if command == "extract":
        extract()
    elif command == "verify":
        verify(limit=int(argv[2]) if len(argv) > 2 else 20)
    elif command == "list":
        index = load_index()
        for weapon, variants in index["weapons"].items():
            print(f"{weapon}:")
            for variant, spec in variants.items():
                print(f"  {variant:20s} {len(spec['slots']):3d} slots  "
                      f"{len(spec['sources'])} tier(s)")
    elif command == "palettes":
        for name, palette in load_palettes().items():
            print(f"{name:34s} {' '.join(palette.material)}")
    elif command == "generate":
        if len(argv) < 3:
            print("usage: spritegen.py generate <tier> [--from <existing-tier>]")
            return 1
        tier = argv[2]
        palettes = load_palettes()
        source = argv[4] if len(argv) > 4 and argv[3] == "--from" else tier
        if source not in palettes:
            print(f"no palette for {source!r}; try `python spritegen.py palettes`")
            return 1
        generate(tier, palettes[source])
    else:
        print(__doc__)
        print("commands: extract | list | palettes | generate <tier> | verify [n]")
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv))
