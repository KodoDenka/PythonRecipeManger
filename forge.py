"""Parametric weapon silhouettes: original geometry, shaded from its own form.

`spritegen.py` recolours blanks extracted from the existing mod art. That is the right tool
for reference and the wrong one for shipping — the silhouettes in `common/blanks/` are other
people's drawings with the colour lifted out, so a set built from them is a recolour rather
than a mod's own art. This module draws the shapes instead.

A weapon here is a handful of primitives placed along a curve. That choice is what makes
fifteen weapon types tractable: a katana's curved single edge, a scythe's sweep, a spear's
straight haft and a warglaive's crescent are all one `Stroke` with different control points
and width profiles, not four separate drawing routines.

Shading comes from the geometry rather than from a source sprite. Every primitive knows the
signed across-distance of each texel it covers, so the tone bands can be applied relative to
the form: the lit side of a blade is the side facing the light, whichever way the blade
happens to curve. Bands are hard steps, not a gradient — a 3px blade has room for three
tones, and interpolating between them produces mud rather than metal. That was the first
thing the prototype got wrong.

Output is a `spritegen` blank: a PNG keyed by slot colour plus the slot table that says what
each of those greys means. So everything downstream — palettes, two-tone accents, surface
treatments, animation, previews — works on these without changes.
"""

import math

# Canvas for every generated weapon. The existing blanks are a mix of 16 and 32; uniform 32
# is the finer of the two, and since Minecraft maps every item texture onto the same quad,
# more texels buys detail rather than size.
CANVAS = 32

# Light direction in canvas space, x right and y down. Upper-left, matching the existing art
# and vanilla's own items -- a set lit from a different corner than the vanilla tools it sits
# beside in the inventory reads as broken rather than as stylised.
LIGHT = (-0.72, -0.69)

# Tone bands across a blade, as (upper bound on the normalised across-coordinate, position).
# Four tones: a bright catch on the lit edge, two body tones, and a dark contour on the
# shadow edge. The contour is what the prototype was missing -- without it a blade has no
# termination and reads as a glow rather than as an object.
# Three bands, not four. A blade is 3 texels wide at this canvas, so its pixel centres
# sample u at roughly -0.67, 0 and +0.67 -- a fourth band above 0.62 is simply unreachable,
# which is why the first pass came out uniformly bright with no shadow side at all.
BLADE_BANDS = ((-0.34, 1.00), (0.34, 0.62), (1.01, 0.30))

# Hafts are round in section, so they get a tighter, darker set: a wooden shaft that carries
# the same contrast as a blade competes with it for attention.
# Hafts sit higher on their ramp than blades do on theirs. The handle ramp is already the
# darkest thing in a palette, so sampling its bottom end as well stacks two darkenings and
# the grip disappears -- which is exactly what happened when the forged blanks first
# replaced the extracted ones.
HAFT_BANDS = ((-0.34, 0.95), (0.34, 0.68), (1.01, 0.40))

# Flat faces -- hammer heads, axe cheeks, guards. Less across-variation because the surface
# genuinely is flat; the shape reads from its outline instead.
FLAT_BANDS = ((-0.45, 0.82), (0.30, 0.58), (1.01, 0.36))


def band(u, bands):
    """Tone position for a normalised across-coordinate in [-1, 1]."""
    for edge, position in bands:
        if u < edge:
            return position
    return bands[-1][1]


def profile(t, stops):
    """Linear interpolation over (fraction, value) control points, clamped at both ends."""
    if t <= stops[0][0]:
        return stops[0][1]
    for i in range(len(stops) - 1):
        (t0, v0), (t1, v1) = stops[i], stops[i + 1]
        if t0 <= t <= t1:
            k = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
            return v0 + (v1 - v0) * k
    return stops[-1][1]


def bezier(p0, p1, p2, samples=160):
    """Quadratic bezier as a point list with tangents, sampled densely enough to measure.

    Distance to a curve is found by brute force against these samples rather than solved
    analytically. At canvas resolution the error is far below a texel, and it means a stroke
    can be any curve without needing a closed form for each one.
    """
    out = []
    for i in range(samples + 1):
        t = i / samples
        m = 1 - t
        x = m * m * p0[0] + 2 * m * t * p1[0] + t * t * p2[0]
        y = m * m * p0[1] + 2 * m * t * p1[1] + t * t * p2[1]
        dx = 2 * m * (p1[0] - p0[0]) + 2 * t * (p2[0] - p1[0])
        dy = 2 * m * (p1[1] - p0[1]) + 2 * t * (p2[1] - p1[1])
        length = math.hypot(dx, dy) or 1.0
        out.append((x, y, dx / length, dy / length))
    return out


class Canvas:
    """Cells being accumulated into one weapon.

    Later primitives overwrite earlier ones, so a weapon is declared back to front: haft
    first, then the head that sits over it, then the fittings that sit over that. Painting
    order is the only depth information a flat sprite has.
    """

    def __init__(self, size=CANVAS):
        self.size = size
        self.cells = {}

    def put(self, x, y, family, position):
        if 0 <= x < self.size and 0 <= y < self.size:
            self.cells[(x, y)] = (family, min(1.0, max(0.0, position)))

    def stroke(self, curve, widths, bands=BLADE_BANDS, family="material", flip=False,
               shade=0.0, edge=None):
        """Paint a curve of varying half-width.

        `widths` is a profile over the curve's own length, so a blade can swell past the
        guard and taper to a point without being cut into segments. The across-coordinate is
        signed by which side of the tangent a texel falls on, then oriented so that negative
        is always the lit side — that is what lets one band table serve a blade curving
        either way.
        """
        widest = max(w for _, w in widths)
        x0 = max(0, int(min(c[0] for c in curve) - widest - 1))
        x1 = min(self.size, int(max(c[0] for c in curve) + widest + 2))
        y0 = max(0, int(min(c[1] for c in curve) - widest - 1))
        y1 = min(self.size, int(max(c[1] for c in curve) + widest + 2))
        for y in range(y0, y1):
            for x in range(x0, x1):
                px, py = x + 0.5, y + 0.5
                best = None
                for cx, cy, tx, ty in curve:
                    d2 = (px - cx) ** 2 + (py - cy) ** 2
                    if best is None or d2 < best[0]:
                        best = (d2, cx, cy, tx, ty)
                d2, cx, cy, tx, ty = best
                # where along the curve the nearest point sits, for the width profile
                t = self._along(curve, cx, cy)
                half = profile(t, widths)
                if half <= 0 or d2 > half * half:
                    continue

                cross = tx * (py - cy) - ty * (px - cx)
                signed = math.copysign(math.sqrt(d2), cross)
                if flip:
                    signed = -signed
                # An edge treatment perturbs the cutting side only. Modulating the whole
                # width would make the blade pulse in thickness -- a wavy weapon rather than
                # a serrated one -- and the spine is not where teeth belong.
                lit = half * (edge(t) if edge else 1.0)
                if signed < 0:
                    if -signed > lit:
                        continue
                    u = signed / max(lit, 1e-6)
                else:
                    u = signed / half
                self.put(x, y, family, band(u, bands) + shade)

    @staticmethod
    def _along(curve, cx, cy):
        """Fraction along the curve of one of its own sample points."""
        for i, (x, y, _, _) in enumerate(curve):
            if x == cx and y == cy:
                return i / (len(curve) - 1)
        return 0.0

    def disc(self, centre, radius, bands=FLAT_BANDS, family="material", shade=0.0,
             inner=0.0):
        """A filled circle, or an annulus when `inner` is set. Pommels, tsuba, chakram."""
        for y in range(self.size):
            for x in range(self.size):
                px, py = x + 0.5, y + 0.5
                d = math.hypot(px - centre[0], py - centre[1])
                if d > radius or d < inner:
                    continue
                # shade by facing: the side of the circle turned toward the light is lit,
                # which is what makes a ring read as round rather than as a printed O
                nx, ny = (px - centre[0]) / (d or 1), (py - centre[1]) / (d or 1)
                u = -(nx * LIGHT[0] + ny * LIGHT[1])
                self.put(x, y, family, band(u, bands) + shade)

    def polygon(self, points, bands=FLAT_BANDS, family="material", shade=0.0):
        """A filled convex polygon, shaded by distance from its lit edge.

        Axe and hammer heads are flats, and a flat wants its tone driven by how close a texel
        is to the edge facing the light rather than by any curve — so this measures against
        the polygon's own extent along the light direction instead of reusing `stroke`.
        """
        span = [p[0] * LIGHT[0] + p[1] * LIGHT[1] for p in points]
        lo, hi = min(span), max(span)
        for y in range(self.size):
            for x in range(self.size):
                px, py = x + 0.5, y + 0.5
                if not self._inside(points, px, py):
                    continue
                t = ((px * LIGHT[0] + py * LIGHT[1]) - lo) / max(1e-6, hi - lo)
                self.put(x, y, family, band(1 - 2 * t, bands) + shade)

    @staticmethod
    def _inside(points, px, py):
        sign = 0
        for i, a in enumerate(points):
            b = points[(i + 1) % len(points)]
            cross = (b[0] - a[0]) * (py - a[1]) - (b[1] - a[1]) * (px - a[0])
            if cross:
                if sign and (cross > 0) != (sign > 0):
                    return False
                sign = cross
        return True

    def bar(self, centre, direction, half_length, half_thick, bands=FLAT_BANDS,
            family="material", sweep=0.0, shade=0.0):
        """A crossbar: guards, hammer shoulders, spear wings.

        `sweep` bends the arms toward the tip as they get further from the axis, which is the
        difference between a crossguard and a plus sign.
        """
        dx, dy = direction
        length = math.hypot(dx, dy) or 1.0
        dx, dy = dx / length, dy / length
        px_, py_ = -dy, dx
        for y in range(self.size):
            for x in range(self.size):
                gx, gy = x + 0.5 - centre[0], y + 0.5 - centre[1]
                across = gx * dx + gy * dy
                along = gx * px_ + gy * py_
                if abs(across) > half_length:
                    continue
                bend = sweep * (abs(across) / half_length) ** 2
                if abs(along - bend) > half_thick:
                    continue
                self.put(x, y, family, band(along - bend, bands) + shade)


def outline(canvas, position=0.20, floor=0.45, family=None):
    """Darken material texels on the shadow-side boundary, above `floor` only.

    A generated shape has clean edges but no weight; vanilla items read as solid partly
    because their lower-right boundary is much darker than their body. Applied to the two
    shadow-facing sides only — darkening every edge makes a sticker, not an object.

    `floor` is what stops it eating the blade. The band tables already put their darkest
    tone on the shadow side, so outlining that texel too took a 3-wide blade down to two
    visible texels against a dark inventory slot: the first pass looked thin for exactly
    this reason, not because the geometry was too narrow.
    """
    darkened = {}
    for (x, y), (fam, pos) in canvas.cells.items():
        if fam != "material" or (family and fam != family) or pos < floor:
            continue
        for dx, dy in ((1, 0), (0, 1)):
            if (x + dx, y + dy) not in canvas.cells:
                darkened[(x, y)] = (fam, min(pos, position))
                break
    canvas.cells.update(darkened)
    return canvas


# --- edge treatments ----------------------------------------------------------------
#
# Each returns a multiplier on the cutting-side half-width as a function of position along
# the blade. They cut inward rather than outward: a tooth that grows past the silhouette
# changes the weapon's reach and its fitted scale, while a notch cut into it does not.
#
# `run` is where along the blade the treatment starts, so the ricasso near the guard stays
# clean the way a real serrated blade's does.

def smooth():
    return None


def _teeth(count, depth, shape, run=0.18):
    def edge(t):
        if t < run:
            return 1.0
        k = ((t - run) / (1 - run) * count) % 1.0
        return 1.0 - depth * shape(k)
    return edge


def serrated(count=9, depth=0.30, run=0.18):
    """Saw teeth: a hard ramp that drops back sharply. Reads as a cutting tool."""
    return _teeth(count, depth, lambda k: k, run)


def toothed(count=5, depth=0.42, run=0.22):
    """Fewer, deeper, squarer bites. Reads as a beast's jaw rather than a saw."""
    return _teeth(count, depth, lambda k: 1.0 if k < 0.45 else 0.0, run)


def chipped(count=7, depth=0.34, run=0.12):
    """Irregular scallops, from a fixed pattern so the same blade chips the same way."""
    pattern = (0.0, 0.9, 0.2, 1.0, 0.35, 0.65, 0.1)
    return _teeth(count, depth,
                  lambda k, p=pattern: p[int(k * len(p)) % len(p)], run)


EDGES = {"smooth": smooth, "serrated": serrated, "toothed": toothed, "chipped": chipped}


# --- export to a spritegen blank ----------------------------------------------------

def to_blank(cells, size=CANVAS, steps=24):
    """Turn drawn cells into a blank PNG plus its slot table.

    A blank stores one grey per distinct (family, position) pair, and `spritegen.render()`
    looks each one up by exact colour. Positions are quantised to `steps` first: the
    geometry produces continuous values, and without quantising, a curve would mint a fresh
    slot for nearly every texel it covers, blowing past MAX_SLOTS and making the blank
    unreadable as a document of the drawing.

    Material greys are laid out from #101010 up and handle greys from #909000 across, so the
    two families stay visually separable if anyone opens the PNG.
    """
    from PIL import Image

    quantised = {}
    for xy, (family, position) in cells.items():
        quantised[xy] = (family, round(position * steps) / steps)

    keys, slots = {}, []
    for family, position in sorted(set(quantised.values()),
                                   key=lambda kv: (kv[0], kv[1])):
        index = len(keys)
        if family == "material":
            colour = (16 + index * 9, 16 + index * 9, 16 + index * 9)
        else:
            colour = (144, 144 - index * 5, 0)
        keys[(family, position)] = colour
        slots.append({"colour": "#%02x%02x%02x" % colour, "family": family,
                      "position": round(position, 4), "alpha": 255})

    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    pixels = image.load()
    for (x, y), key in quantised.items():
        pixels[x, y] = keys[key] + (255,)
    return image, slots
