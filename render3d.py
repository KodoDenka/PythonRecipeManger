"""Software renderer for Minecraft item models.

Rasterises the same models the generator exports, so preview GIFs show the geometry the
game actually draws rather than a flat sprite pretending to rotate.

Two kinds of model reach this module:

- `minecraft:item/generated` templates (14 of the 15 weapons), which have no geometry of
  their own. The game builds their mesh by extruding the sprite into a 1px-thick slab and
  walling in the silhouette, and `extrude_sprite()` reproduces that.
- Hand-built Blockbench templates with an `elements` list (currently only greathammer).
  `elements_to_quads()` reads those cuboids directly, including per-element rotation.

Model space follows the Minecraft convention throughout: 0..16 on each axis, y up, +z
toward the viewer, and face UVs in a 0..16 texture space with v increasing downward.
"""

import json
import math
import os

import numpy as np
from PIL import Image

MODEL_SIZE = 16.0
CENTER = np.array([MODEL_SIZE / 2, MODEL_SIZE / 2, MODEL_SIZE / 2])

# Sprite slab depth used by item/generated, in model units.
SLAB_FRONT = 8.5
SLAB_BACK = 7.5

# Direction the key light comes from. Slightly above and to the left of the camera, which
# keeps the front face bright while giving the extruded edges definition as they turn.
LIGHT = np.array([-0.35, 0.75, 0.56])
LIGHT = LIGHT / np.linalg.norm(LIGHT)
AMBIENT = 0.42
DIFFUSE = 0.58

# Specular sweep. A highlight band travels across the weapon's own horizontal axis as it
# turns, so metal catches the light instead of reading as flat-shaded.
#
# Strength follows sin(2*spin)^2, which is deliberately zero both edge-on and face-on and
# peaks at the quarter turns. Face-on has to be zero because that is the frame the GIF
# holds for HOLD_FRAMES: a highlight that peaked there would freeze mid-blade for the
# whole hold and read as a smudge rather than a gleam. So the weapon flashes once on the
# way in and once on the way out, and settles clean.
SPEC_STRENGTH = 0.55
# Gaussian half-width of the band, in the model's 0..16 texture space. Wide enough to
# still read once a GIF is scaled down on a page; much wider and the whole weapon just
# brightens instead of a band travelling across it.
SPEC_WIDTH = 1.8
# Quantise the highlight into this many steps. A smooth gradient spends the GIF's 255
# colours on near-identical shades and compresses badly, so banding the falloff keeps
# files small — and reads as more at home against pixel art than a soft airbrush would.
# 0 disables quantisation.
SPEC_STEPS = 4

# Corner order for each box face, viewed from outside: top-left, top-right, bottom-right,
# bottom-left. UV corners (u1,v1), (u2,v1), (u2,v2), (u1,v2) map onto them in that order.
def _box_face(x1, y1, z1, x2, y2, z2, face):
    if face == "north":
        return [(x2, y2, z1), (x1, y2, z1), (x1, y1, z1), (x2, y1, z1)]
    if face == "south":
        return [(x1, y2, z2), (x2, y2, z2), (x2, y1, z2), (x1, y1, z2)]
    if face == "west":
        return [(x1, y2, z1), (x1, y2, z2), (x1, y1, z2), (x1, y1, z1)]
    if face == "east":
        return [(x2, y2, z2), (x2, y2, z1), (x2, y1, z1), (x2, y1, z2)]
    if face == "up":
        return [(x1, y2, z1), (x2, y2, z1), (x2, y2, z2), (x1, y2, z2)]
    if face == "down":
        return [(x1, y1, z2), (x2, y1, z2), (x2, y1, z1), (x1, y1, z1)]
    raise ValueError(f"unknown face {face}")


def _uv_corners(uv):
    u1, v1, u2, v2 = uv
    return [(u1, v1), (u2, v1), (u2, v2), (u1, v2)]


def _rotate(points, axis, angle_deg, origin):
    """Rotate points about a single axis through origin, as model elements specify."""
    if not angle_deg:
        return points
    rad = math.radians(angle_deg)
    cos, sin = math.cos(rad), math.sin(rad)
    shifted = points - origin
    out = shifted.copy()
    if axis == "x":
        out[:, 1] = shifted[:, 1] * cos - shifted[:, 2] * sin
        out[:, 2] = shifted[:, 1] * sin + shifted[:, 2] * cos
    elif axis == "y":
        out[:, 0] = shifted[:, 0] * cos + shifted[:, 2] * sin
        out[:, 2] = -shifted[:, 0] * sin + shifted[:, 2] * cos
    elif axis == "z":
        out[:, 0] = shifted[:, 0] * cos - shifted[:, 1] * sin
        out[:, 1] = shifted[:, 0] * sin + shifted[:, 1] * cos
    return out + origin


def elements_to_quads(elements):
    """Convert a model's `elements` list into textured quads."""
    quads = []
    for element in elements:
        x1, y1, z1 = element["from"]
        x2, y2, z2 = element["to"]
        rotation = element.get("rotation") or {}
        axis = rotation.get("axis")
        angle = rotation.get("angle", 0)
        origin = np.array(rotation.get("origin", [8, 8, 8]), dtype=float)

        for face, spec in element.get("faces", {}).items():
            corners = np.array(_box_face(x1, y1, z1, x2, y2, z2, face), dtype=float)
            if angle:
                corners = _rotate(corners, axis, angle, origin)
            quads.append({
                "verts": corners,
                "uvs": np.array(_uv_corners(spec["uv"]), dtype=float),
                "texture": spec.get("texture", "#layer0").lstrip("#"),
            })
    return quads


def extrude_sprite(alpha, width, height):
    """Build the mesh Minecraft generates for an item/generated model.

    A front and back face carry the sprite, and every texel on the silhouette boundary
    gets a wall quad so the item has a real edge when it turns side-on.
    """
    quads = []
    # Front and back span the whole sprite; transparent texels are dropped at sample time.
    quads.append({
        "verts": np.array(_box_face(0, 0, SLAB_FRONT, MODEL_SIZE, MODEL_SIZE, SLAB_FRONT, "south"), dtype=float),
        "uvs": np.array(_uv_corners([0, 0, MODEL_SIZE, MODEL_SIZE]), dtype=float),
        "texture": "layer0",
    })
    quads.append({
        "verts": np.array(_box_face(0, 0, SLAB_BACK, MODEL_SIZE, MODEL_SIZE, SLAB_BACK, "north"), dtype=float),
        "uvs": np.array(_uv_corners([MODEL_SIZE, 0, 0, MODEL_SIZE]), dtype=float),
        "texture": "layer0",
    })

    step = MODEL_SIZE / width
    ustep = MODEL_SIZE / width
    vstep = MODEL_SIZE / height

    for row in range(height):
        for col in range(width):
            if not alpha[row, col]:
                continue
            # Model x grows with the column; model y grows upward while rows count down.
            x1, x2 = col * step, (col + 1) * step
            y1, y2 = MODEL_SIZE - (row + 1) * step, MODEL_SIZE - row * step
            u1, u2 = col * ustep, (col + 1) * ustep
            v1, v2 = row * vstep, (row + 1) * vstep
            uv = [u1, v1, u2, v2]

            neighbours = (
                ("west", col == 0 or not alpha[row, col - 1]),
                ("east", col == width - 1 or not alpha[row, col + 1]),
                ("up", row == 0 or not alpha[row - 1, col]),
                ("down", row == height - 1 or not alpha[row + 1, col]),
            )
            for face, exposed in neighbours:
                if not exposed:
                    continue
                quads.append({
                    "verts": np.array(_box_face(x1, y1, SLAB_BACK, x2, y2, SLAB_FRONT, face), dtype=float),
                    "uvs": np.array(_uv_corners(uv), dtype=float),
                    "texture": "layer0",
                })
    return quads


def _sample(texture, u, v):
    """Nearest-neighbour texture lookup. u/v arrive in 0..16 model texture space."""
    height, width = texture.shape[:2]
    tx = np.clip((u / MODEL_SIZE * width).astype(np.int32), 0, width - 1)
    ty = np.clip((v / MODEL_SIZE * height).astype(np.int32), 0, height - 1)
    return texture[ty, tx]


def render(quads, textures, spin_deg, canvas, scale, tilt_deg=0.0):
    """Rasterise quads at a given spin angle into an RGBA array.

    Orthographic projection, matching how Minecraft draws items in the GUI. Depth is
    resolved with a z-buffer and transparent texels are discarded rather than depth-tested,
    so the sprite silhouette stays clean.
    """
    colour = np.zeros((canvas, canvas, 4), dtype=np.float32)
    depth = np.full((canvas, canvas), -np.inf, dtype=np.float32)

    # Band travels the weapon's own horizontal axis rather than the screen's, so it tracks
    # the blade instead of drifting off it as the shape foreshortens.
    spin_rad = math.radians(spin_deg)
    spec_strength = SPEC_STRENGTH * math.sin(2 * spin_rad) ** 2
    spec_centre = MODEL_SIZE * (0.5 + spin_deg / 180.0)

    for quad in quads:
        texture = textures.get(quad["texture"])
        if texture is None:
            continue

        verts = _rotate(quad["verts"], "y", spin_deg, CENTER)
        if tilt_deg:
            verts = _rotate(verts, "x", tilt_deg, CENTER)

        # Face normal after rotation, flipped toward the camera so both sides of the thin
        # slab shade sensibly rather than the back going black.
        edge1 = verts[1] - verts[0]
        edge2 = verts[3] - verts[0]
        normal = np.cross(edge1, edge2)
        norm = np.linalg.norm(normal)
        if norm < 1e-9:
            continue
        normal = normal / norm
        if normal[2] < 0:
            normal = -normal
        shade = AMBIENT + DIFFUSE * max(0.0, float(np.dot(normal, LIGHT)))
        # Surfaces angled away from the camera catch less of the sweep.
        spec = spec_strength * float(normal[2])

        screen = np.empty((4, 2), dtype=np.float32)
        screen[:, 0] = (verts[:, 0] - CENTER[0]) * scale + canvas / 2
        screen[:, 1] = canvas / 2 - (verts[:, 1] - CENTER[1]) * scale
        zs = verts[:, 2]

        for tri in ((0, 1, 2), (0, 2, 3)):
            _raster_tri(colour, depth, screen[list(tri)], zs[list(tri)],
                        quad["uvs"][list(tri)], texture, shade, canvas,
                        spec, spec_centre)

    out = np.clip(colour, 0, 255).astype(np.uint8)
    return out


def _raster_tri(colour, depth, pts, zs, uvs, texture, shade, canvas, spec=0.0, spec_centre=0.0):
    min_x = max(int(np.floor(pts[:, 0].min())), 0)
    max_x = min(int(np.ceil(pts[:, 0].max())), canvas - 1)
    min_y = max(int(np.floor(pts[:, 1].min())), 0)
    max_y = min(int(np.ceil(pts[:, 1].max())), canvas - 1)
    if min_x > max_x or min_y > max_y:
        return

    x0, y0 = pts[0]
    x1, y1 = pts[1]
    x2, y2 = pts[2]
    area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
    if abs(area) < 1e-9:
        return

    ys, xs = np.mgrid[min_y:max_y + 1, min_x:max_x + 1]
    px = xs + 0.5
    py = ys + 0.5

    w0 = ((x1 - px) * (y2 - py) - (x2 - px) * (y1 - py)) / area
    w1 = ((x2 - px) * (y0 - py) - (x0 - px) * (y2 - py)) / area
    w2 = 1.0 - w0 - w1

    inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
    if not inside.any():
        return

    z = w0 * zs[0] + w1 * zs[1] + w2 * zs[2]
    # Orthographic, so larger z is nearer the camera.
    closer = inside & (z > depth[min_y:max_y + 1, min_x:max_x + 1])
    if not closer.any():
        return

    u = w0 * uvs[0, 0] + w1 * uvs[1, 0] + w2 * uvs[2, 0]
    v = w0 * uvs[0, 1] + w1 * uvs[1, 1] + w2 * uvs[2, 1]
    texel = _sample(texture, u[closer], v[closer])

    opaque = texel[:, 3] > 128
    if not opaque.any():
        return

    idx = np.nonzero(closer)
    rows = idx[0][opaque] + min_y
    cols = idx[1][opaque] + min_x
    lit = texel[opaque].astype(np.float32)
    lit[:, :3] *= shade

    if spec > 0.0:
        # Blend toward white rather than adding, so the gleam brightens the material
        # instead of clipping to a flat white blob on already-light textures.
        falloff = np.exp(-(((u[closer][opaque] - spec_centre) / SPEC_WIDTH) ** 2))
        gain = spec * falloff
        if SPEC_STEPS:
            gain = np.round(gain * SPEC_STEPS) / SPEC_STEPS
        lit[:, :3] += (255.0 - lit[:, :3]) * gain[:, None]

    colour[rows, cols] = lit
    depth[rows, cols] = z[closer][opaque]


def apply_display(quads, model, kind="gui"):
    """Apply a model's display transform, the same one the game uses for that context.

    Hand-built models are authored at whatever size suits Blockbench — greathammer spans
    roughly 43 units against the standard 16 — and rely on this transform to sit correctly
    in an inventory slot. Without it they render wildly oversized.
    """
    display = ((model or {}).get("display") or {}).get(kind)
    if not display:
        return quads

    scale = np.array(display.get("scale", [1, 1, 1]), dtype=float)
    rotation = display.get("rotation", [0, 0, 0])
    translation = np.array(display.get("translation", [0, 0, 0]), dtype=float)

    out = []
    for quad in quads:
        verts = (quad["verts"] - CENTER) * scale
        # Models in this project only ever rotate about one axis here, but apply X, Y, Z in
        # order so multi-axis transforms behave predictably if one is added later.
        for axis, angle in zip("xyz", rotation):
            if angle:
                verts = _rotate(verts, axis, angle, np.zeros(3))
        out.append({**quad, "verts": verts + translation + CENTER})
    return out


def fit_scale(meshes, canvas, tilt_deg=0.0, margin=0.06):
    """One pixel scale shared by every weapon in a GIF.

    Sized so nothing clips at any point in the spin. Rotation about Y sweeps each vertex
    through a circle of radius hypot(x, z), which bounds the horizontal extent and is
    unaffected by the camera tilt since tilting about X leaves x alone. The tilt does
    reach the vertical extent though, mixing in depth as |y|cos(t) + radius*sin(t), so it
    has to be accounted for or tall weapons clip once the camera comes off the equator.

    Sharing a single scale across the whole tier keeps weapons honestly sized against each
    other instead of each being fitted to the frame.
    """
    tilt = math.radians(tilt_deg)
    cos_t, sin_t = abs(math.cos(tilt)), abs(math.sin(tilt))

    half_width = 0.0
    half_height = 0.0
    for quads in meshes:
        for quad in quads:
            offset = quad["verts"] - CENTER
            radius = np.hypot(offset[:, 0], offset[:, 2])
            half_width = max(half_width, float(radius.max()))
            reach = np.abs(offset[:, 1]) * cos_t + radius * sin_t
            half_height = max(half_height, float(reach.max()))
    extent = max(half_width, half_height, 1e-6)
    return (canvas / 2) * (1 - margin) / extent


def load_template(templates_dir, weapon):
    """Load a weapon's template model, or None if the template is unavailable."""
    if not templates_dir:
        return None
    path = os.path.join(templates_dir, f"{weapon}.json")
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def build_quads(weapon, sprite, templates_dir):
    """Pick the right mesh for a weapon: real elements if it has them, else extrusion.

    The model is returned either way, including for item/generated templates that carry no
    geometry, because they still define the display transform that sizes them in the GUI.
    """
    model = load_template(templates_dir, weapon)
    if model is not None and model.get("elements"):
        return elements_to_quads(model["elements"]), model
    alpha = np.array(sprite.getchannel("A")) > 128
    return extrude_sprite(alpha, sprite.width, sprite.height), model


def to_image(array):
    return Image.fromarray(array, mode="RGBA")
