"""Surface treatments: per-tier effects applied over a rendered sprite.

A palette says what a material is *made of*. A treatment says what its surface *does* --
whether it glitters, pulses, corrodes, refracts or glows. Two tiers can share a ramp and
still read as completely different substances, which is the whole point: colour alone runs
out of distinctions long before twelve materials do.

Each treatment receives a `Surface`, which is the rendered pixels plus, for every pixel,
the family and ramp position it was shaded from. That is what makes these effects
structural rather than cosmetic -- `pulse` can brighten "the lit two thirds of the blade"
because position already encodes how lit a texel is, and `translucent` can spare the grip
because family already distinguishes it. Matching on output colour instead would break the
moment two tiers shared a shade.

Treatments are pure: they take a pixel list and return a new one, never mutating the
Surface. Animated ones use `frame`/`frames` to phase themselves and must be periodic, since
Minecraft loops the strip.

Determinism matters more than randomness quality here. `_rand` is a small FNV-style hash of
its arguments, so a speck sits in the same place on every run, on every machine, and in
every tier that shares a seed -- art that shifts under a regenerate is not art anyone can
hand-fix afterwards.
"""

import colorsys
import math

# --- deterministic noise ------------------------------------------------------------

def _hash(*values):
    h = 2166136261
    for value in values:
        h = ((h ^ (int(value) & 0xFFFFFFFF)) * 16777619) & 0xFFFFFFFF
    # The murmur3 finaliser is not optional here. FNV alone avalanches poorly on the tiny,
    # highly correlated keys this gets fed -- pixel coordinates 0..63 -- and leaves adjacent
    # texels differing in the fourth decimal. Without it `_rand` returned 0.33..0.94 instead
    # of 0..1, so every treatment that thresholds against a density below 0.33 matched
    # nothing at all and silently did nothing.
    h ^= h >> 16
    h = (h * 0x85EBCA6B) & 0xFFFFFFFF
    h ^= h >> 13
    h = (h * 0xC2B2AE35) & 0xFFFFFFFF
    h ^= h >> 16
    return h & 0xFFFFFFFF


def _rand(*values):
    """A stable 0..1 from any integer key."""
    return _hash(*values) / 0xFFFFFFFF


# --- colour helpers -----------------------------------------------------------------

def _hex(value):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _clamp(value):
    return 0 if value < 0 else 255 if value > 255 else int(round(value))


def _scale(rgb, factor):
    return tuple(_clamp(c * factor) for c in rgb[:3])


def _mix(a, b, t):
    return tuple(_clamp(x + (y - x) * t) for x, y in zip(a[:3], b[:3]))


def _shift_hue(rgb, degrees, saturate=1.0):
    r, g, b = [c / 255 for c in rgb[:3]]
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    h = (h + degrees / 360.0) % 1.0
    s = min(1.0, s * saturate)
    return tuple(_clamp(c * 255) for c in colorsys.hls_to_rgb(h, l, s))


# --- the surface a treatment sees ----------------------------------------------------

class Surface:
    """Rendered pixels plus the slot metadata each one came from.

    `family[i]` and `position[i]` are None for fully transparent pixels, which are the
    canvas rather than the item. `palette` is carried so a treatment can re-shade from a
    modified position instead of only tinting the colour it was handed -- `facet` needs
    that, because quantising a colour and quantising the ramp position it sampled give
    visibly different results on a two-tone material.
    """

    __slots__ = ("size", "pixels", "family", "position", "palette")

    def __init__(self, size, pixels, family, position, palette):
        self.size = size
        self.pixels = pixels
        self.family = family
        self.position = position
        self.palette = palette

    @property
    def width(self):
        return self.size[0]

    def xy(self, i):
        return i % self.size[0], i // self.size[0]

    def is_material(self, i):
        return self.family[i] == "material" and self.pixels[i][3] > 0

    def neighbours(self, i):
        """Indices orthogonally adjacent to i, staying inside the canvas."""
        w, h = self.size
        x, y = i % w, i // w
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h:
                yield ny * w + nx


# --- treatments ----------------------------------------------------------------------
#
# Signature: fn(surface, frame, frames, **params) -> new pixel list.

def noise(surface, frame, frames, colours=("#5b1386", "#9435bb", "#d86df2"),
          density=0.16, seed=0, drift=(1, 1), above=0.0, mode="drift"):
    """Scatter specks of `colours` across the material, moving between frames.

    Reads as a dark nebula: a body dark enough to be a hole in the frame, with light
    caught in it. `mode="drift"` slides one fixed field across the sprite, so specks
    travel and the eye tracks them; `mode="twinkle"` reseeds per frame, so they blink in
    place. Drift suits a substance you are looking *into*, twinkle a surface that is
    discharging.

    The field is sampled modulo 64 rather than by absolute position so it tiles smoothly
    past the edge of a 16px sprite instead of running out of pattern.
    """
    out = list(surface.pixels)
    ramp = [_hex(c) for c in colours]
    if mode == "twinkle":
        ox = oy = 0
        salt = frame * 7919
    else:
        ox, oy = frame * drift[0], frame * drift[1]
        salt = 0
    for i, pixel in enumerate(out):
        if not surface.is_material(i) or surface.position[i] < above:
            continue
        x, y = surface.xy(i)
        key = ((x + ox) % 64, (y + oy) % 64)
        if _rand(seed, salt, key[0], key[1]) > density:
            continue
        # squared so the brightest speck colour stays rare and the field reads as depth
        t = _rand(seed + 1, salt, key[0], key[1]) ** 2
        out[i] = ramp[min(len(ramp) - 1, int(t * len(ramp)))] + (pixel[3],)
    return out


def translucent(surface, frame, frames, alpha=150, above=None, above_alpha=225,
                lift=1.0):
    """Thin the material to `alpha`, leaving the grip solid.

    An item you can see through needs something opaque to hold, or it stops reading as a
    weapon and starts reading as a rendering fault -- so family, not position, decides
    what survives. `above`/`above_alpha` keep the lit core denser than the body, which is
    what makes it look like glass with something suspended in it rather than a decal.

    `lift` brightens as it thins, because alpha composites toward whatever is behind the
    item and an inventory slot is dark: at alpha 150 an unlifted blade loses roughly half
    its apparent value.
    """
    out = list(surface.pixels)
    for i, pixel in enumerate(out):
        if not surface.is_material(i):
            continue
        a = above_alpha if (above is not None and surface.position[i] >= above) else alpha
        rgb = _scale(pixel, lift) if lift != 1.0 else pixel[:3]
        out[i] = tuple(rgb) + (min(pixel[3], a),)
    return out


def pulse(surface, frame, frames, above=0.55, amount=0.35, floor=0.85, cycles=1):
    """Swell the brightness of the lit region and let it fall back, on a loop.

    Position-gated so the body stays put and only the core moves -- a whole-sprite
    brightness ramp reads as the light changing, while a core-only one reads as the
    material doing something. `floor` keeps the trough above the static render so the
    pulse never dips into looking broken.

    Weighted by how far past `above` each pixel sits, so the swell has a soft interior
    edge instead of a hard ring where the gate cuts in.
    """
    phase = 0.5 - 0.5 * math.cos(2 * math.pi * cycles * frame / max(1, frames))
    out = list(surface.pixels)
    for i, pixel in enumerate(out):
        if not surface.is_material(i):
            continue
        p = surface.position[i]
        if p < above:
            continue
        weight = min(1.0, (p - above) / max(1e-6, 1.0 - above))
        factor = floor + (1 - floor) * 1.0 + amount * phase * weight
        out[i] = _scale(pixel, factor) + (pixel[3],)
    return out


def flicker(surface, frame, frames, above=0.62, amount=0.30, seed=0, coherence=3):
    """Per-texel brightness jitter over the lit region: embers, not a pulse.

    `coherence` buckets neighbouring texels onto a shared random value so patches flicker
    together. At 1 every texel is independent and the result is television static; at 3 or
    4 it reads as heat moving through channels.
    """
    out = list(surface.pixels)
    for i, pixel in enumerate(out):
        if not surface.is_material(i) or surface.position[i] < above:
            continue
        x, y = surface.xy(i)
        cell = (x // coherence, y // coherence)
        r = _rand(seed, cell[0], cell[1], frame)
        out[i] = _scale(pixel, 1.0 + amount * (r - 0.5) * 2) + (pixel[3],)
    return out


def facet(surface, frame, frames, steps=4, bias=0.0):
    """Quantise ramp position before re-shading: hard planes instead of a smooth roll.

    Cut gemstone has flats meeting at edges, not a gradient. Quantising the *position*
    rather than the rendered colour matters on a two-tone palette -- colour quantisation
    would band the body and accent separately and leave the split visible as a seam,
    while position quantisation moves the split onto a facet boundary where it belongs.
    """
    out = list(surface.pixels)
    for i, pixel in enumerate(out):
        if not surface.is_material(i):
            continue
        p = min(1.0, max(0.0, surface.position[i] + bias))
        stepped = round(p * (steps - 1)) / (steps - 1)
        out[i] = tuple(surface.palette.shade(stepped)) + (pixel[3],)
    return out


def iridescent(surface, frame, frames, spread=34, axis="position", saturate=1.12,
               cycles=1):
    """Rotate hue across the sprite so the material shows more than one colour at once.

    Pearl and oil-film do not have a colour, they have a range, and a single ramp cannot
    say that. `axis="position"` shifts by how lit a texel is, which follows the form;
    `axis="y"` shifts down the sprite regardless of form, which reads as a sheen laid over
    it. Animating `cycles` rolls the band along the blade.
    """
    out = list(surface.pixels)
    w, h = surface.size
    roll = frame / max(1, frames) * cycles
    for i, pixel in enumerate(out):
        if not surface.is_material(i):
            continue
        if axis == "y":
            t = surface.xy(i)[1] / max(1, h - 1)
        else:
            t = surface.position[i]
        degrees = spread * math.sin(2 * math.pi * (t + roll))
        out[i] = _shift_hue(pixel, degrees, saturate) + (pixel[3],)
    return out


def pit(surface, frame, frames, density=0.22, darken=0.62, seed=0, below=0.9):
    """Punch static dark specks into the surface: corrosion, porosity, slag.

    Static on purpose. Corrosion is damage the material already has, and animating it
    would say the item is actively dissolving in the player's hand. `below` spares the
    brightest texels so the cutting edge stays clean and the weapon still reads as sharp.
    """
    out = list(surface.pixels)
    for i, pixel in enumerate(out):
        if not surface.is_material(i) or surface.position[i] > below:
            continue
        x, y = surface.xy(i)
        if _rand(seed, x, y) > density:
            continue
        out[i] = _scale(pixel, darken) + (pixel[3],)
    return out


def sparkle(surface, frame, frames, density=0.10, colour="#ffffff", seed=0, above=0.5,
            twinkle=0):
    """Single bright texels scattered through the lit region: crushed starlight.

    Distinct from `noise` in that it adds points of light to a light body rather than
    revealing light inside a dark one, so it stays sparse and never recolours the
    material. `twinkle` sets how many frames a given speck stays lit; 0 is static.
    """
    out = list(surface.pixels)
    rgb = _hex(colour)
    for i, pixel in enumerate(out):
        if not surface.is_material(i) or surface.position[i] < above:
            continue
        x, y = surface.xy(i)
        if _rand(seed, x, y) > density:
            continue
        if twinkle:
            # each speck gets its own offset so they do not all blink in unison
            offset = int(_rand(seed + 3, x, y) * frames)
            if ((frame + offset) // max(1, twinkle)) % 2:
                continue
        out[i] = _mix(pixel, rgb, 0.85) + (pixel[3],)
    return out


def bloom(surface, frame, frames, colour=None, alpha=90, above=0.72, falloff=0.45):
    """Bleed light from the brightest texels into the transparent canvas around them.

    A halo is how a 16px sprite says "emissive" -- there is no room for a gradient inside
    the silhouette, so the glow has to live outside it. Only spreads into empty pixels, so
    the item's own shape is untouched, and it is capped at the canvas edge: on a sprite
    that already fills its frame there is nowhere to bloom and the treatment is a no-op
    rather than a clipped rectangle.
    """
    w, h = surface.size
    out = list(surface.pixels)
    sources = [i for i in range(len(out)) if surface.is_material(i)
               and surface.position[i] >= above]
    if not sources:
        return out
    glow = _hex(colour) if colour else None
    ring, seen = sources, set(sources)
    strength = 1.0
    while ring and strength > 0.08:
        strength *= falloff
        nxt = []
        for i in ring:
            for j in surface.neighbours(i):
                if j in seen or surface.pixels[j][3] != 0:
                    continue
                seen.add(j)
                nxt.append(j)
                src = glow or surface.pixels[i][:3]
                a = _clamp(alpha * strength)
                if a > out[j][3]:
                    out[j] = tuple(src) + (a,)
        ring = nxt
    return out


def etch(surface, frame, frames, period=4, darken=0.68, above=0.35, axis="cross",
         offset=0, relative=True):
    """Cut regular dark lines across the material: machined segments, inlay channels.

    The blanks carry no UV or part information, so the only geometry available is the
    pixel grid. Weapon sprites in this set are drawn on the diagonal, which is what makes
    this work: lines of constant `x + y` run square across a blade laid bottom-left to
    top-right, so `axis="cross"` produces rungs along the blade rather than a hatch over
    it. `axis="along"` uses `x - y` for the perpendicular case.
    """
    if relative:
        # a fixed pixel period puts twice as many rungs on a 64px greathammer blank as on a
        # 32px sword, so the same setting reads as inlay on one and as a screen door on the
        # other. Scaling by canvas keeps the count per weapon roughly constant.
        period = max(2, round(period * max(surface.size) / 32))
    out = list(surface.pixels)
    for i, pixel in enumerate(out):
        if not surface.is_material(i) or surface.position[i] < above:
            continue
        x, y = surface.xy(i)
        value = (x + y) if axis == "cross" else (x - y)
        if (value + offset) % period:
            continue
        out[i] = _scale(pixel, darken) + (pixel[3],)
    return out


def rimlight(surface, frame, frames, amount=1.35, alpha_edge=True, above=0.25,
             sides=("up", "left")):
    """Brighten the material texels that sit on a silhouette edge.

    Polished stone and finished metal catch a hard line where the surface turns away;
    without it a smooth ramp reads as plastic. Restricted to two sides so the light has a
    direction -- lighting every edge produces an outline, which reads as a sticker.
    """
    w, h = surface.size
    deltas = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
    out = list(surface.pixels)
    for i, pixel in enumerate(out):
        if not surface.is_material(i) or surface.position[i] < above:
            continue
        x, y = surface.xy(i)
        exposed = False
        for side in sides:
            dx, dy = deltas[side]
            nx, ny = x + dx, y + dy
            if not (0 <= nx < w and 0 <= ny < h) or surface.pixels[ny * w + nx][3] == 0:
                exposed = True
                break
        if exposed:
            out[i] = _scale(pixel, amount) + (pixel[3],)
    return out


def outline(surface, frame, frames, colour="#0b0b10", alpha=255, corners=True):
    """Lay a dark border in the empty pixels touching the item.

    Lifts a sprite off busy inventory backgrounds. Costs a pixel of apparent size on every
    side, which is why it is opt-in per tier rather than applied to everything -- on the
    already-large weapons it pushes them to the edge of the frame.
    """
    w, h = surface.size
    out = list(surface.pixels)
    rgb = _hex(colour)
    for i in range(len(out)):
        if surface.pixels[i][3] == 0:
            continue
        x, y = surface.xy(i)
        span = (-1, 0, 1) if corners else None
        cells = ([(x + dx, y + dy) for dx in span for dy in span if dx or dy]
                 if corners else
                 [(x, y - 1), (x, y + 1), (x - 1, y), (x + 1, y)])
        for nx, ny in cells:
            if not (0 <= nx < w and 0 <= ny < h):
                continue
            j = ny * w + nx
            if surface.pixels[j][3] == 0 and out[j][3] == 0:
                out[j] = rgb + (alpha,)
    return out


REGISTRY = {
    "noise": noise,
    "translucent": translucent,
    "pulse": pulse,
    "flicker": flicker,
    "facet": facet,
    "iridescent": iridescent,
    "pit": pit,
    "sparkle": sparkle,
    "bloom": bloom,
    "etch": etch,
    "rimlight": rimlight,
    "outline": outline,
}


def apply(surface, spec, frame, frames):
    """Run one treatment spec (`{"type": name, ...params}`) over a surface.

    Returns the new pixel list; the caller rebuilds the Surface so the next treatment in
    the chain sees the previous one's output. Order is therefore significant and declared
    by the tier: `bloom` after `pulse` blooms the swollen core, before it blooms the
    static one.
    """
    params = {k: v for k, v in spec.items() if k != "type"}
    try:
        fn = REGISTRY[spec["type"]]
    except KeyError:
        raise KeyError(f"unknown treatment {spec.get('type')!r}; "
                       f"have {', '.join(sorted(REGISTRY))}")
    # lists survive the JSON round trip but several params want tuples
    for key in ("drift", "sides", "colours"):
        if key in params and isinstance(params[key], list):
            params[key] = tuple(params[key])
    return fn(surface, frame, frames, **params)
