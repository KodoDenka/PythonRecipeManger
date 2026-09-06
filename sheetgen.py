"""Contact sheets of the material set, one per progression tier.

A hand-run presentation tool, like `spritegen.py` and unlike `main.py`: it reads
`common/sprites/` and `common/data/tier_groups.json` and writes PNGs to `sheets/`.
Nothing in the generation pipeline imports it, and it writes nothing the mod consumes.

    python sheetgen.py              # every tier, plus the all-tiers overview
    python sheetgen.py --tier 4     # just that one

Each sheet is one tier: a row per material, a column per weapon type.

**Every sprite is drawn at the same size, whatever its pixel resolution.** Sprites are
16/32/48px by weapon type, but Minecraft maps every item texture onto the same 16x16
quad, so a 48px halberd is not three times the size of a 16px sai in the game -- it is
the same size with finer pixels. Scaling each sprite to its own pixel count would tell an
artist the halberd is huge. The scale factors (6x/3x/2x onto a 96px box) are integers so
the upscale stays nearest-neighbour clean.

Animated materials are drawn on frame 0, and the sheet does not say so. A still is what
an artist marks up, and the preview GIFs already show the motion properly.

**The greathammer is rasterised from its model, not pasted from its sprite.** It is the
one weapon with a hand-built `elements` template, so its PNG is a UV atlas for that model
and not a flat item sprite -- pasted straight in it reads as a scrambled block of
coloured squares in every material. Everything else is `minecraft:item/generated`, whose
in-game look *is* the sprite, and those are pasted unmodified: rendering them too would
cost the bloom haloes, which sit below the alpha 128 that `build_quads` extrudes at and
so would silently vanish from the very materials that use them.
"""

import json
import os
import sys
import time

from PIL import Image, ImageDraw, ImageFont

SPRITE_ROOT = os.path.join("common", "sprites")
GROUPS_PATH = os.path.join("common", "data", "tier_groups.json")
OUT_DIR = "sheets"

# The weapon columns, in the order they appear on every sheet: light one-handers first,
# then two-handers, then polearms, so a row reads roughly small-to-large.
WEAPONS = [
    "sai", "rapier", "cutlass", "katana", "longsword", "twinblade", "chakram",
    "claymore", "greataxe", "greathammer", "scythe", "warglaive", "glaive",
    "halberd", "spear",
]

CELL = 96           # the box every sprite is fitted into, whatever its resolution
GUTTER = 6
LABEL_W = 208       # the material-name column down the left
HEAD_H = 34         # the weapon-name row across the top
PAD = 28
TITLE_H = 86

BG = (18, 20, 26)
PANEL = (25, 28, 36)
ROW_ALT = (31, 35, 45)
GRID = (48, 53, 66)
TEXT = (232, 236, 244)
DIM = (138, 147, 166)
ACCENT = (223, 186, 106)

FONT_DIRS = [os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts"),
             "/usr/share/fonts/truetype/dejavu", "/Library/Fonts"]


def _font(names, size):
    """First of `names` that resolves, else Pillow's bitmap default.

    The default has no size control, so a sheet built without any of these fonts is ugly
    but still correct -- worth more than refusing to draw one.
    """
    for name in names:
        for directory in FONT_DIRS:
            path = os.path.join(directory, name)
            if os.path.isfile(path):
                try:
                    return ImageFont.truetype(path, size)
                except OSError:
                    pass
    return ImageFont.load_default()


BOLD = ["segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"]
REG = ["segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"]
MONO = ["consola.ttf", "cour.ttf", "DejaVuSansMono.ttf"]


def load_groups():
    with open(GROUPS_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)["tiers"]


def sprite_dir(selector):
    """Resolve a tier_groups selector to a sprite folder, the way thumbnail.json does.

    'mod_id/tier' names one tier; a bare name is a top-level folder, which is how Blue
    Skies' woods and gems sit in the tree.
    """
    path = os.path.join(SPRITE_ROOT, *selector.split("/"))
    return path if os.path.isdir(path) else None


def load_frame(path):
    """Frame 0 of a sprite, and how many frames the strip holds.

    An animated texture is a vertical strip of square frames; drawing the strip whole
    would put a 16-frames-tall sliver in a square cell. Frame count comes from the
    dimensions rather than the .mcmeta, since item textures are square and that is true
    whether or not the metadata is beside it.
    """
    with Image.open(path) as handle:
        sheet = handle.convert("RGBA")
    count = 1
    if sheet.width and sheet.height > sheet.width and not sheet.height % sheet.width:
        count = sheet.height // sheet.width
    if count > 1:
        sheet = sheet.crop((0, 0, sheet.width, sheet.width))
    return sheet, count


def fitted(sprite):
    """`sprite` scaled to the CELL box by an integer factor, nearest-neighbour.

    Integer so the pixels stay square and hard-edged. A sprite that does not divide CELL
    evenly falls back to the largest factor that fits rather than a fractional resize.
    """
    factor = max(1, CELL // max(sprite.width, sprite.height))
    out = sprite.resize((sprite.width * factor, sprite.height * factor), Image.NEAREST)
    if max(out.size) > CELL:
        out = out.resize((CELL, CELL), Image.NEAREST)
    return out


# --- weapons whose look comes from a model rather than from the sprite ---------------

# A standard item model is 16 units across, and CELL is what a 16px sprite fills, so this
# is pixels per model unit -- the scale that puts a modelled weapon at the same in-game
# size as the pasted sprites beside it rather than fitted to its own cell.
UNITS = CELL / 16.0

_runtime = None      # (render3d, templates_dir, extra_textures), or False if unavailable
_meshes = {}         # weapon -> (quads, model), or None if it has no elements template


def _model_runtime():
    """The 3D renderer and the mod's model templates, resolved once.

    Both are optional: numpy may not be installed, and `preview.TEMPLATES_DIR` points at a
    sibling checkout of the mod that only exists on some machines. Either missing means
    the modelled weapons fall back to their raw sprite, which is worth a warning but not a
    failed sheet -- the other fourteen columns are unaffected.
    """
    global _runtime
    if _runtime is not None:
        return _runtime
    try:
        import numpy as np
        import preview
        import render3d
    except ImportError as exc:
        print("no 3D renderer (%s); modelled weapons fall back to their atlas" % exc)
        _runtime = False
        return _runtime
    if not os.path.isdir(preview.TEMPLATES_DIR):
        print("model templates not found at %s;" % preview.TEMPLATES_DIR)
        print("  modelled weapons fall back to their atlas. Set KNAVESNEEDS_TEMPLATES.")
        _runtime = False
        return _runtime
    extras = {}
    for slot, path in preview.EXTRA_TEXTURES.items():
        if os.path.isfile(path):
            with Image.open(path) as handle:
                extras[slot] = np.array(handle.convert("RGBA"))
    _runtime = (render3d, preview.TEMPLATES_DIR, extras)
    return _runtime


def modelled(weapon, sprite):
    """`weapon` rasterised face-on from its model, or None if it has no model geometry.

    Face-on and untilted, which is the frame the preview GIFs hold and what the game draws
    in an inventory slot. The mesh is cached per weapon because it depends only on the
    template -- the material changes the texture, never the geometry.
    """
    runtime = _model_runtime()
    if runtime is False:
        return None
    render3d, templates_dir, extras = runtime

    if weapon not in _meshes:
        model = render3d.load_template(templates_dir, weapon)
        if model is None or not model.get("elements"):
            _meshes[weapon] = None
        else:
            quads = render3d.elements_to_quads(model["elements"])
            _meshes[weapon] = (render3d.apply_display(quads, model, "gui"), model)
    if _meshes[weapon] is None:
        return None

    import numpy as np
    quads, _ = _meshes[weapon]
    textures = dict(extras, layer0=np.array(sprite))
    return render3d.to_image(render3d.render(quads, textures, 0.0, CELL, UNITS, 0.0))


def save_png(img, path, attempts=6):
    """Write `img` to `path`, retrying briefly if something else is holding the file.

    On Windows a virus scanner or indexer commonly opens a PNG the instant it is closed
    and holds it for a few tens of milliseconds, which makes the *next* run's write of the
    same name fail with EINVAL. It lands on a different sheet each time, so a run that
    saved six files could fail on any one of them. Backing off and retrying is enough;
    nothing here is contended for longer than that.
    """
    delay = 0.1
    for attempt in range(attempts):
        try:
            img.save(path)
            return
        except OSError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)
            delay *= 2


def _text(draw, xy, text, font, fill, anchor="la"):
    draw.text(xy, text, font=font, fill=fill, anchor=anchor)


def build_sheet(tier, materials_override=None, title=None, subtitle=None):
    """One sheet: a row per material, a column per weapon."""
    materials = materials_override if materials_override is not None else tier["materials"]
    rows = len(materials)

    width = PAD * 2 + LABEL_W + len(WEAPONS) * (CELL + GUTTER) - GUTTER
    height = PAD * 2 + TITLE_H + HEAD_H + rows * (CELL + GUTTER) - GUTTER

    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)

    f_title = _font(BOLD, 40)
    f_sub = _font(REG, 17)
    f_row = _font(BOLD, 19)
    f_note = _font(REG, 13)
    f_col = _font(MONO, 13)

    name = title or tier["name"]
    _text(draw, (PAD, PAD), name.upper(), f_title, TEXT)
    if subtitle is None:
        subtitle = "  \u00b7  ".join(m["label"] for m in materials)
    _text(draw, (PAD, PAD + 48), subtitle, f_sub, ACCENT)

    grid_x = PAD + LABEL_W
    grid_y = PAD + TITLE_H

    # column headers, centred over their cells
    for i, weapon in enumerate(WEAPONS):
        cx = grid_x + i * (CELL + GUTTER) + CELL // 2
        _text(draw, (cx, grid_y + HEAD_H - 12), weapon, f_col, DIM, anchor="ms")

    body_y = grid_y + HEAD_H
    draw.line([(PAD, body_y - 4), (width - PAD, body_y - 4)], fill=GRID, width=1)

    missing = []
    for r, material in enumerate(materials):
        top = body_y + r * (CELL + GUTTER)
        band = ROW_ALT if r % 2 else PANEL
        draw.rectangle([PAD, top, width - PAD, top + CELL], fill=band)

        directory = sprite_dir(material["sprites"]) if material.get("sprites") else None
        # An empty row is the only thing a caption can say that the picture cannot. Which
        # tiers borrow Simply Swords' art, and which materials animate, are both things
        # the people these sheets go to already know, and a label per row for either just
        # crowds the art.
        note = "" if directory else "no art yet"

        # The name centres on the row when it stands alone, and lifts to make room only
        # for the rows that actually carry a note.
        _text(draw, (PAD + 14, top + CELL // 2 - (12 if note else 1)),
              material["label"], f_row, TEXT if directory else DIM)
        if note:
            _text(draw, (PAD + 14, top + CELL // 2 + 10), note, f_note, DIM)

        for i, weapon in enumerate(WEAPONS):
            x = grid_x + i * (CELL + GUTTER)
            path = os.path.join(directory, weapon + ".png") if directory else None
            if path and os.path.isfile(path):
                sprite, _ = load_frame(path)
                art = modelled(weapon, sprite) or fitted(sprite)
                img.paste(art, (x + (CELL - art.width) // 2,
                                top + (CELL - art.height) // 2), art)
            else:
                # An absent cell is drawn as a hollow box rather than left blank, so a
                # gap in the set reads as a gap and not as a sprite that failed to load.
                draw.rectangle([x + CELL // 3, top + CELL // 3,
                                x + CELL - CELL // 3, top + CELL - CELL // 3],
                               outline=GRID, width=1)
                if directory:
                    missing.append("%s/%s" % (material["label"], weapon))

    return img, missing


def main(argv):
    only = None
    args = argv[1:]
    while args:
        arg = args.pop(0)
        if arg in ("--tier", "-t"):
            if not args:
                print("--tier needs a number")
                return 2
            only = args.pop(0)
        else:
            print("unknown argument: %s" % arg)
            return 2

    tiers = load_groups()
    os.makedirs(OUT_DIR, exist_ok=True)

    picked = tiers
    if only is not None:
        picked = [t for i, t in enumerate(tiers, 1)
                  if str(i) == only or t["name"].lower() == only.lower()]
        if not picked:
            print("no such tier: %s" % only)
            return 2

    all_missing = []
    for index, tier in enumerate(tiers, 1):
        if tier not in picked:
            continue
        img, missing = build_sheet(tier)
        path = os.path.join(OUT_DIR, "tier_%d.png" % index)
        save_png(img, path)
        print("%-9s %2d materials  ->  %s  (%dx%d)"
              % (tier["name"], len(tier["materials"]), path, img.width, img.height))
        all_missing += missing

    if only is None:
        # The overview stacks every material in progression order onto one sheet, which is
        # the view that answers "does the set read as a progression" -- the per-tier
        # sheets are for looking at one tier's materials against each other.
        flat = [m for t in tiers for m in t["materials"]]
        drawn = sum(1 for m in flat if m.get("sprites"))
        img, _ = build_sheet(None, flat, title="Knaves' Needs \u2014 full material set",
                             subtitle="%d materials across %d tiers  \u00b7  %d weapon "
                                      "types  \u00b7  %d sprites drawn"
                                      % (len(flat), len(tiers), len(WEAPONS),
                                         drawn * len(WEAPONS)))
        path = os.path.join(OUT_DIR, "all_tiers.png")
        save_png(img, path)
        print("%-9s %2d materials  ->  %s  (%dx%d)"
              % ("overview", len(flat), path, img.width, img.height))

    if all_missing:
        print("\nmissing sprites (%d):" % len(all_missing))
        for entry in all_missing:
            print("  %s" % entry)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
