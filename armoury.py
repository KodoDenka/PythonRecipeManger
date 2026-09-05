"""The fifteen weapons, described as geometry.

`forge.py` is the drawing layer — curves, discs, polygons, tone bands. This is the part that
says what a halberd actually is. Kept apart because the two change for different reasons:
tuning how a bevel reads is a rendering decision, while deciding that a scythe's blade sweeps
back over the haft is a design one.

Every weapon is laid out on the same bottom-left to top-right diagonal the existing art uses,
so a generated sprite sits in an inventory slot the way the hand-drawn ones do.

A `Style` scales the parts rather than replacing them, which is what lets one tier's whole
fifteen-weapon set read as a family: a material with a heavy blade has a heavy blade on all
fifteen, and the weapons still differ from each other exactly as much as they did.
"""

import math
import os
from dataclasses import dataclass

from forge import (CANVAS, DESIGN, BLADE_BANDS, FLAT_BANDS, HAFT_BANDS, Canvas,
                   bezier, outline)


@dataclass(frozen=True)
class Style:
    """A tier's weapon language: proportions, hilt furniture and edge treatment.

    Scales parts rather than replacing them, so one tier's fifteen weapons read as a family
    while still differing from each other exactly as much as they did. The furniture names
    are the part that carries tier identity — a material whose weapons all wear ring hilts
    and spiked pommels is recognisable across the whole set, in a way a colour swap alone
    never manages.
    """
    blade: float = 1.0      # blade and head mass
    guard: float = 1.0      # guards, tsuba, wings, knuckle bows
    pommel: float = 1.0     # butt fittings
    curve: float = 1.0      # how hard curved parts bend
    haft: float = 1.0       # shaft thickness
    guard_style: str = "cross"
    pommel_style: str = "disc"
    grip_style: str = "wrapped"
    edge: str = "smooth"


NEUTRAL = Style()

# Canvas per weapon type, matching what the existing art ships at. Not a free choice: a 16px
# chakram rendered at 32 is not bigger, only finer than every other item beside it, and the
# set stops reading as one density.
SIZES = {"sai": 16, "cutlass": 16, "chakram": 16, "halberd": 48}
DEFAULT_SIZE = 32

# Hand-built models, for weapons whose sprite is a UV atlas rather than a picture. Same
# absolute path the preview renderer uses, and overridable the same way.
TEMPLATES_DIR = os.environ.get(
    "KNAVESNEEDS_TEMPLATES",
    "C:/Program Files/GitHub/knavesneeds/common/src/main/resources/assets/knavesneeds"
    "/models/item/templates",
)


def size_for(weapon):
    return SIZES.get(weapon, DEFAULT_SIZE)

AXIS_A, AXIS_B = (6.0, 26.0), (27.0, 5.0)


def _lerp(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def seg(a, b, samples=96):
    """A straight stroke."""
    return bezier(a, _lerp(a, b, 0.5), b, samples)


def bow(a, b, amount, samples=128):
    """A stroke bent `amount` texels perpendicular to its chord.

    This is the whole curvature vocabulary. A katana, a cutlass, a warglaive's crescent and a
    scythe's sweep differ only in how hard they bend and how their width is distributed along
    the bend, which is why fifteen weapons do not need fifteen drawing routines.
    """
    mid = _lerp(a, b, 0.5)
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy) or 1.0
    return bezier(a, (mid[0] - dy / length * amount, mid[1] + dx / length * amount), b,
                  samples)


def _axis(t0, t1):
    return _lerp(AXIS_A, AXIS_B, t0), _lerp(AXIS_A, AXIS_B, t1)


def _perp():
    dx, dy = AXIS_B[0] - AXIS_A[0], AXIS_B[1] - AXIS_A[1]
    length = math.hypot(dx, dy)
    return (-dy / length, dx / length)


# --- hilt furniture -----------------------------------------------------------------
#
# Guards, pommels and grips are a separate vocabulary from blades, picked per tier rather
# than per weapon. A blade says what the weapon is; the furniture says whose it is.

def _grip(c, a, b, st, width=0.95):
    """A held section, in the handle family so it reads off the palette's grip ramp."""
    c.stroke(seg(a, b), ((0.0, width * st.haft), (1.0, width * st.haft)),
             HAFT_BANDS, "handle")
    GRIPS.get(st.grip_style, grip_plain)(c, a, b, st)


def grip_plain(c, a, b, st):
    return


def grip_wrapped(c, a, b, st, period=3):
    """Darken every few texels along the grip: cord or leather binding.

    The single largest improvement available to a handle at this resolution. A plain rod of
    three tones reads as a dowel however well it is shaded, because a real grip's texture is
    banding across it rather than shading along it.
    """
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy) or 1.0
    ux, uy = dx / length, dy / length
    for (x, y), (family, position) in list(c.cells.items()):
        if family != "handle":
            continue
        along = (x + 0.5 - a[0]) * ux + (y + 0.5 - a[1]) * uy
        if not (-0.5 <= along <= length + 0.5):
            continue
        if int(along) % period == 0:
            c.put(x, y, family, position * 0.72)


def grip_ridged(c, a, b, st):
    """Coarser banding with a lit crest, for a moulded rather than wrapped grip."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy) or 1.0
    ux, uy = dx / length, dy / length
    for (x, y), (family, position) in list(c.cells.items()):
        if family != "handle":
            continue
        along = (x + 0.5 - a[0]) * ux + (y + 0.5 - a[1]) * uy
        if not (-0.5 <= along <= length + 0.5):
            continue
        phase = int(along) % 4
        if phase == 0:
            c.put(x, y, family, min(1.0, position * 1.30))
        elif phase == 2:
            c.put(x, y, family, position * 0.68)


GRIPS = {"plain": grip_plain, "wrapped": grip_wrapped, "ridged": grip_ridged}


def guard_none(c, at, st, span=1.0):
    return


def guard_cross(c, at, st, span=1.0):
    c.bar(at, _perp(), 5.4 * span * st.guard, 1.3, sweep=1.0)


def guard_swept(c, at, st, span=1.0):
    """Arms curving toward the blade, drawn as strokes so the tips stay a texel wide."""
    px, py = _perp()
    reach = 5.4 * span * st.guard
    for side in (-1, 1):
        tip = (at[0] + px * reach * side + (AXIS_B[0] - AXIS_A[0]) / 20 * 2.6,
               at[1] + py * reach * side + (AXIS_B[1] - AXIS_A[1]) / 20 * 2.6)
        c.stroke(bow(at, tip, 1.8 * side), ((0.0, 1.30), (1.0, 0.70)), FLAT_BANDS)


def guard_ring(c, at, st, span=1.0):
    outer = 3.8 * span * st.guard
    c.disc(at, outer, inner=outer - 1.6)
    c.bar(at, _perp(), 3.0 * span * st.guard, 1.0)


def guard_tsuba(c, at, st, span=1.0):
    c.disc(at, 2.6 * span * st.guard)


def guard_winged(c, at, st, span=1.0):
    """A bar whose tips turn up toward the tip: spear wings, ceremonial crossguards."""
    px, py = _perp()
    reach = 4.8 * span * st.guard
    c.bar(at, _perp(), reach, 1.2, sweep=0.4)
    for side in (-1, 1):
        base = (at[0] + px * reach * side, at[1] + py * reach * side)
        tip = (base[0] + (AXIS_B[0] - AXIS_A[0]) / 21 * 3.0,
               base[1] + (AXIS_B[1] - AXIS_A[1]) / 21 * 3.0)
        c.stroke(seg(base, tip), ((0.0, 0.95), (1.0, 0.0)), FLAT_BANDS)


GUARDS = {"none": guard_none, "cross": guard_cross, "swept": guard_swept,
          "ring": guard_ring, "tsuba": guard_tsuba, "winged": guard_winged}


def pommel_none(c, at, st, scale=1.0):
    return


def pommel_disc(c, at, st, scale=1.0):
    c.disc(at, 1.4 * scale * st.pommel)


def pommel_faceted(c, at, st, scale=1.0):
    r = 1.7 * scale * st.pommel
    px, py = _perp()
    dx, dy = (AXIS_B[0] - AXIS_A[0]) / 30, (AXIS_B[1] - AXIS_A[1]) / 30
    c.polygon([(at[0] + px * r, at[1] + py * r),
               (at[0] - dx * r * 1.1, at[1] - dy * r * 1.1),
               (at[0] - px * r, at[1] - py * r),
               (at[0] + dx * r * 1.1, at[1] + dy * r * 1.1)])


def pommel_spike(c, at, st, scale=1.0):
    dx, dy = AXIS_A[0] - AXIS_B[0], AXIS_A[1] - AXIS_B[1]
    length = math.hypot(dx, dy)
    end = (at[0] + dx / length * 3.2 * scale * st.pommel,
           at[1] + dy / length * 3.2 * scale * st.pommel)
    c.stroke(seg(at, end), ((0.0, 1.15 * scale), (1.0, 0.0)))


def pommel_ring(c, at, st, scale=1.0):
    r = 2.0 * scale * st.pommel
    c.disc(at, r, inner=r - 1.2)


POMMELS = {"none": pommel_none, "disc": pommel_disc, "faceted": pommel_faceted,
           "spike": pommel_spike, "ring": pommel_ring}


def fit_guard(c, at, st, span=1.0):
    GUARDS.get(st.guard_style, guard_cross)(c, at, st, span)


def fit_pommel(c, at, st, scale=1.0):
    POMMELS.get(st.pommel_style, pommel_disc)(c, at, st, scale)


def _edge(st):
    import forge
    maker = forge.EDGES.get(st.edge, forge.smooth)
    return maker()


def _haft(c, st, top=0.70, width=0.95):
    a, end = _axis(0.0, top)
    _grip(c, a, end, st, width)
    return end


# --- swords -------------------------------------------------------------------------

def longsword(c, st):
    a, g = _axis(0.0, 0.30)
    _, tip = _axis(0.30, 1.0)
    _grip(c, a, g, st)
    c.stroke(seg(g, tip), ((0.0, 1.15 * st.blade), (0.12, 1.70 * st.blade),
                           (0.86, 1.45 * st.blade), (1.0, 0.0)), edge=_edge(st))
    fit_guard(c, g, st)
    fit_pommel(c, a, st)
    return c


def claymore(c, st):
    a, g = _axis(0.0, 0.26)
    _, tip = _axis(0.26, 1.0)
    _grip(c, a, g, st, 1.0)
    c.stroke(seg(g, tip), ((0.0, 1.60 * st.blade), (0.15, 2.45 * st.blade),
                           (0.84, 2.00 * st.blade), (1.0, 0.0)), edge=_edge(st))
    fit_guard(c, g, st, 1.25)
    fit_pommel(c, a, st, 1.1)
    return c


def katana(c, st):
    a, g = _axis(0.0, 0.32)
    _, tip = _axis(0.32, 1.0)
    _grip(c, a, g, st)
    # single-edged and gently bowed, so the bright band lands on the outer curve where the
    # cutting edge is and the spine keeps the dark contour
    c.stroke(bow(g, tip, -1.6 * st.curve),
             ((0.0, 1.40 * st.blade), (0.90, 1.25 * st.blade), (1.0, 0.0)),
             edge=_edge(st))
    fit_guard(c, g, st, 0.62)
    return c


def cutlass(c, st):
    """Also 16px, and also authored heavier for it."""
    a, g = _axis(0.0, 0.30)
    _, tip = _axis(0.30, 0.94)
    _grip(c, a, g, st, 1.7)
    c.stroke(bow(g, tip, -3.0 * st.curve),
             ((0.0, 1.90 * st.blade), (0.45, 3.10 * st.blade),
              (0.88, 2.20 * st.blade), (1.0, 0.0)), edge=_edge(st))
    # the knuckle bow belongs to the weapon rather than the tier -- a cutlass without one
    # stops being a cutlass -- so it is drawn here and the tier's guard sits inside it
    c.stroke(bow(g, a, 3.6), ((0.0, 1.25), (1.0, 1.25)), FLAT_BANDS)
    fit_guard(c, g, st, 0.75)
    fit_pommel(c, a, st, 1.5)
    return c


def rapier(c, st):
    a, g = _axis(0.0, 0.26)
    _, tip = _axis(0.26, 1.0)
    _grip(c, a, g, st, 0.85)
    c.stroke(seg(g, tip), ((0.0, 1.05 * st.blade), (0.90, 0.85 * st.blade), (1.0, 0.0)))
    fit_guard(c, g, st, 0.85)
    fit_pommel(c, a, st, 0.85)
    return c


def twinblade(c, st):
    a, b = _axis(0.0, 1.0)
    lo, hi = _axis(0.38, 0.62)
    _grip(c, lo, hi, st, 1.0)
    for start, end in ((hi, b), (lo, a)):
        c.stroke(seg(start, end), ((0.0, 1.05 * st.blade), (0.18, 1.40 * st.blade),
                                   (0.85, 1.20 * st.blade), (1.0, 0.0)), edge=_edge(st))
    for point in (lo, hi):
        fit_guard(c, point, st, 0.60)
    return c


def sai(c, st):
    """Ships at 16px, so every feature is authored roughly twice as heavy.

    A design unit buys half as many texels here as it does on a 32px weapon. The prongs at
    the 32px proportions came out under a texel wide and simply disappeared.
    """
    a, g = _axis(0.06, 0.40)
    _, tip = _axis(0.40, 0.96)
    _grip(c, a, g, st, 1.8)
    c.stroke(seg(g, tip), ((0.0, 1.75 * st.blade), (0.85, 1.45 * st.blade), (1.0, 0.0)))
    px, py = _perp()
    for side in (-1, 1):
        base = (g[0] + px * 2.6 * side, g[1] + py * 2.6 * side)
        end = (base[0] + (tip[0] - g[0]) * 0.55 + px * 2.2 * side,
               base[1] + (tip[1] - g[1]) * 0.55 + py * 2.2 * side)
        c.stroke(seg(base, end), ((0.0, 1.60 * st.blade), (0.8, 1.30 * st.blade),
                                  (1.0, 0.0)))
    fit_guard(c, g, st, 0.85)
    fit_pommel(c, a, st, 1.30)
    return c


def warglaive(c, st):
    """A crescent held at its waist rather than at one end."""
    a, b = _axis(0.02, 0.98)
    c.stroke(bow(a, b, 6.2 * st.curve, 160),
             ((0.0, 0.0), (0.16, 1.50 * st.blade), (0.50, 2.30 * st.blade),
              (0.84, 1.50 * st.blade), (1.0, 0.0)), edge=_edge(st))
    lo, hi = _axis(0.42, 0.58)
    _grip(c, lo, hi, st, 0.9)
    return c


# --- polearms -----------------------------------------------------------------------

def spear(c, st):
    end = _haft(c, st, 0.72)
    _, tip = _axis(0.72, 1.0)
    c.stroke(seg(end, tip), ((0.0, 1.00), (0.26, 2.45 * st.blade),
                             (0.70, 1.70 * st.blade), (1.0, 0.0)), edge=_edge(st))
    fit_guard(c, end, st, 0.52)
    return c


def glaive(c, st):
    end = _haft(c, st, 0.60)
    _, tip = _axis(0.60, 1.0)
    c.stroke(bow(end, tip, -3.0 * st.curve),
             ((0.0, 1.10 * st.blade), (0.45, 2.50 * st.blade),
              (0.90, 1.50 * st.blade), (1.0, 0.0)), edge=_edge(st))
    fit_guard(c, end, st, 0.45)
    return c


def halberd(c, st):
    end = _haft(c, st, 0.66)
    _, tip = _axis(0.66, 1.0)
    c.stroke(seg(end, tip), ((0.0, 0.90), (0.40, 1.25 * st.blade), (1.0, 0.0)))
    px, py = _perp()
    root = _lerp(end, tip, 0.06)
    # axe cheek one side, counterweight spike the other
    c.polygon([root,
               (root[0] + px * 5.4 * st.blade, root[1] + py * 5.4 * st.blade),
               (root[0] + px * 4.2 * st.blade + (tip[0] - end[0]) * 0.52,
                root[1] + py * 4.2 * st.blade + (tip[1] - end[1]) * 0.52),
               _lerp(end, tip, 0.58)])
    c.stroke(seg(root, (root[0] - px * 4.6, root[1] - py * 4.6)),
             ((0.0, 1.25), (0.55, 0.95), (1.0, 0.0)))
    return c


def scythe(c, st):
    """Haft to the upper right, blade sweeping back across the top to the left.

    The blade has to leave the shaft, not hug it. A scythe reads by the gap between the
    curve and the haft; a blade that merely bends away from the top of a pole is a bent
    sword, which is what the first version drew. The toe reaches nearly to the far edge of
    the canvas, the way the hand-drawn silhouette does.
    """
    end = _haft(c, st, 0.78, 1.0)
    heel = (end[0] + 1.2, end[1] - 1.2)
    toe = (4.5, 6.0)
    c.stroke(bow(heel, toe, 3.6 * st.curve, 180),
             ((0.0, 2.20 * st.blade), (0.45, 1.60 * st.blade), (1.0, 0.0)),
             edge=_edge(st))
    return c


# --- hafted -------------------------------------------------------------------------

def greataxe(c, st):
    _haft(c, st, 0.86, 1.0)
    px, py = _perp()
    root = _lerp(AXIS_A, AXIS_B, 0.56)
    top = _lerp(AXIS_A, AXIS_B, 0.88)
    c.polygon([(root[0] + px * 0.6, root[1] + py * 0.6),
               (root[0] + px * 7.2 * st.blade, root[1] + py * 7.2 * st.blade),
               (top[0] + px * 6.4 * st.blade, top[1] + py * 6.4 * st.blade),
               (top[0] + px * 0.6, top[1] + py * 0.6)])
    c.bar(_lerp(root, top, 0.5), _perp(), 1.4, 3.4, FLAT_BANDS, shade=-0.10)
    return c


def greathammer(c, st):
    """Not a silhouette. The greathammer is a real 3D model and its sprite is a UV atlas.

    Drawn from the template's own element faces rather than as a picture of a hammer:
    painting a hammer shape here would map nonsense onto the model's 37 elements in game.
    Raises when the template is unavailable so `write_forged` can leave the weapon on its
    extracted blank, rather than emit something that looks plausible in a contact sheet and
    is wrong in the world.
    """
    import forge

    model = forge.load_template(TEMPLATES_DIR, "greathammer")
    if model is None:
        raise FileNotFoundError("greathammer template")
    c.cells.update(forge.uv_atlas(model, c.size))
    return c


# A ring's tone has to stay high all the way round. `disc` shades by facing, which on a
# 2-texel-thick 16px ring sends most of the lower half to the darkest band and breaks the
# circle -- so the ring gets a compressed set that never bottoms out.
RING_BANDS = ((-0.45, 1.00), (0.30, 0.78), (1.01, 0.54))


def chakram(c, st):
    """A bare ring at 16px, with no grip -- the hand-drawn one has none either."""
    centre = (DESIGN / 2.0, DESIGN / 2.0)
    outer = 13.2 * min(1.10, st.blade)
    c.disc(centre, outer, inner=outer - 4.6 * st.blade, bands=RING_BANDS)
    return c


WEAPONS = {
    "longsword": longsword, "twinblade": twinblade, "rapier": rapier, "katana": katana,
    "sai": sai, "spear": spear, "glaive": glaive, "warglaive": warglaive,
    "cutlass": cutlass, "claymore": claymore, "greathammer": greathammer,
    "greataxe": greataxe, "chakram": chakram, "scythe": scythe, "halberd": halberd,
}


# Weapons whose sprite is a UV atlas: no silhouette, so no shadow contour either.
ATLAS_WEAPONS = {"greathammer"}


def draw(weapon, style=NEUTRAL, size=None):
    """Build one weapon's cells: {(x, y): (family, ramp position)}."""
    canvas = Canvas(size or size_for(weapon))
    WEAPONS[weapon](canvas, style)
    if weapon in ATLAS_WEAPONS:
        return canvas
    # the contour goes on last, over every part, so a head sitting across a haft still gets
    # a termination where it overhangs
    return outline(canvas)


# --- per-tier weapon languages ------------------------------------------------------
#
# One Style per arpg_core material. These are what make a tier recognisable by shape: a
# player who has seen one Cryalt weapon knows the next one by its faceted pommel and
# chipped edge before the colour registers.

STYLES = {
    # void-forged: swept arms, cut-gem pommel, nothing serrated -- it predates wear
    "nebulium":   Style(blade=1.00, guard=1.05, pommel=1.10, curve=1.00,
                        guard_style="swept", pommel_style="faceted",
                        grip_style="wrapped", edge="smooth"),
    # grown rather than forged: no crossguard, a spur for a pommel, a jaw for an edge
    "erythryl":   Style(blade=1.10, guard=0.85, pommel=1.15, curve=1.10,
                        guard_style="winged", pommel_style="spike",
                        grip_style="wrapped", edge="toothed"),
    # glass: rings rather than bars, and an edge that chips instead of wearing
    "faeglas":    Style(blade=0.95, guard=1.00, pommel=0.95, curve=1.15,
                        guard_style="ring", pommel_style="ring",
                        grip_style="plain", edge="chipped"),
    "cryalt":     Style(blade=1.05, guard=1.00, pommel=1.05, curve=0.90,
                        guard_style="cross", pommel_style="faceted",
                        grip_style="ridged", edge="chipped"),
    # forge-made and used: heavy, winged, saw-toothed
    "hesperynt":  Style(blade=1.12, guard=1.10, pommel=1.00, curve=1.00, haft=1.10,
                        guard_style="winged", pommel_style="disc",
                        grip_style="wrapped", edge="serrated"),
    "rhodynth":   Style(blade=0.92, guard=0.95, pommel=0.95, curve=1.20,
                        guard_style="swept", pommel_style="disc",
                        grip_style="wrapped", edge="smooth"),
    # corroded: stripped of furniture entirely, and eaten along the edge
    "viriwyn":    Style(blade=1.05, guard=1.00, pommel=1.00, curve=1.00,
                        guard_style="none", pommel_style="none",
                        grip_style="plain", edge="serrated"),
    "phthalium":  Style(blade=1.00, guard=1.00, pommel=1.00, curve=0.95,
                        guard_style="tsuba", pommel_style="disc",
                        grip_style="ridged", edge="smooth"),
    "glykios":    Style(blade=0.95, guard=1.00, pommel=1.00, curve=1.05,
                        guard_style="ring", pommel_style="disc",
                        grip_style="wrapped", edge="smooth"),
    "wyrdbright": Style(blade=1.00, guard=1.05, pommel=1.05, curve=1.00,
                        guard_style="cross", pommel_style="ring",
                        grip_style="wrapped", edge="smooth"),
    "auridine":   Style(blade=1.05, guard=1.15, pommel=1.10, curve=0.95,
                        guard_style="winged", pommel_style="faceted",
                        grip_style="ridged", edge="smooth"),
    "celadium":   Style(blade=1.00, guard=0.95, pommel=1.00, curve=1.20,
                        guard_style="swept", pommel_style="none",
                        grip_style="wrapped", edge="toothed"),
}


def variant_name(tier):
    """Blank variant a tier's forged silhouettes are filed under."""
    return f"arpg_{tier}"


def write_forged(blanks_dir="common/blanks", index_path="common/blanks/forged.json",
                 styles=None):
    """Draw every style's fifteen weapons and write them as spritegen blanks.

    Lands in `forged.json` rather than `blanks.json` because `extract` rewrites the latter
    from the sprite tree, and a drawn blank has no sprite to be re-derived from.
    """
    import json
    import os

    import forge

    styles = styles or STYLES
    index = {"weapons": {}}
    written, skipped = 0, set()
    for tier, style in styles.items():
        variant = variant_name(tier)
        for weapon in WEAPONS:
            size = size_for(weapon)
            try:
                cells = draw(weapon, style, size).cells
            except FileNotFoundError:
                skipped.add(weapon)
                continue
            image, slots = forge.to_blank(cells, size)
            folder = os.path.join(blanks_dir, weapon)
            os.makedirs(folder, exist_ok=True)
            image.save(os.path.join(folder, f"{variant}.png"))
            index["weapons"].setdefault(weapon, {})[variant] = {
                "size": [image.width, image.height],
                # no sources: nothing was extracted, so `verify` has no ground truth to
                # compare these against and correctly skips them
                "sources": [],
                "slots": slots,
            }
            written += 1
    with open(index_path, "w", encoding="utf-8") as handle:
        json.dump(index, handle, indent=1)
    if skipped:
        print(f"  no template, left on the extracted blank: {', '.join(sorted(skipped))}")
    return written


if __name__ == "__main__":
    print(f"wrote {write_forged()} forged blanks")
