"""Preview GIF generation.

Renders one looping GIF per material tier: each weapon in the tier spins toward the
camera, and at the moment the spin is edge-on — when the weapon is a sliver and nothing
is legible — the next weapon takes its place. The swap is invisible, so the tier reads as
a single object rotating through its whole weapon set.

Two renderers are available:

- "3d" (default) rasterises the actual item models via render3d, so weapons have real
  thickness, real silhouette edges, and — for hand-built models like greathammer — real
  geometry. Needs numpy.
- "2d" squashes the sprite horizontally to fake the rotation. No numpy, and the fallback
  if render3d is unavailable.

Pillow is required either way. Both are imported lazily by main.py so JSON and texture
generation still work without them.
"""

import math
import os

from PIL import Image

# --- animation tuning -------------------------------------------------------------
# Frames per half turn. Each weapon owns one half turn: it unfolds from edge-on, passes
# through face-on, and folds back to edge-on before handing off to the next. This is the
# knob for spin speed — more frames spreads the same half turn over more time. Keep it
# even so the held frame lands exactly face-on. Hold length is independent of it.
SPIN_FRAMES = 24
# Extra frames held face-on, so each weapon is actually readable before it spins away.
# Hold duration is HOLD_FRAMES * FRAME_MS, unaffected by spin speed.
HOLD_FRAMES = 10
FRAME_MS = 40
# How much the spin eases in and out of the held frame. 0 is constant speed; 1 fully
# stalls at face-on. Only redistributes the angles across the existing frames, so it
# changes the feel of the spin without changing its duration.
EASING = 0.55

CANVAS = 192

# Camera tilt in degrees, looking slightly down at the weapon. Off the equator the top
# faces stay visible through the whole turn, which is what stops the spin reading as a
# flat shape rotating in place. 3D renderer only.
TILT = 12.0

# TODO: idle float. A slow vertical drift across the loop, as a per-frame offset applied
# after the spin. Cheap to add, but it has to be shared by every weapon in the tier and
# continuous across the handoff, otherwise the swap gains a visible jump in height.

# Output formats, written from a single render pass. WebP is the better file by every
# measure — smaller, full alpha, no 256-colour ceiling — but GIF is kept alongside it as
# the fallback for anywhere WebP is not supported.
FORMATS = ("gif", "webp")

# Palette index reserved for transparency. quantize() is capped at 255 colours so this
# one stays free.
TRANSPARENT_INDEX = 255

# WebP encoder settings. quality drives the compression effort when lossless, and method
# 6 is the slowest and smallest of the presets.
WEBP_QUALITY = 90
WEBP_METHOD = 6

# --- 2D fallback tuning -----------------------------------------------------------
# Only used by the sprite-squash renderer. The 3D path lights the model instead.
SCALE_2D = 4
BASE_SPRITE = 48
MIN_BRIGHTNESS = 0.55

# Hand-built model templates. Only greathammer currently has real geometry; every other
# weapon is minecraft:item/generated and is extruded from its sprite, so these paths being
# absent costs detail on exactly one weapon rather than breaking the render.
#
# TODO: these reach into a sibling checkout of the knavesneeds mod by absolute path, so
# they only resolve on one machine. Templates and their extra textures should move into
# this project the way sprites did — probably common/models/ and common/sprites/overlays/
# — once there is a story for keeping them in step with the Blockbench sources they are
# authored from. Until then, override with KNAVESNEEDS_TEMPLATES.
MOD_REPO = "C:/Program Files/GitHub/knavesneeds"
TEMPLATES_DIR = os.environ.get(
    "KNAVESNEEDS_TEMPLATES",
    f"{MOD_REPO}/common/src/main/resources/assets/knavesneeds/models/item/templates",
)
# Extra textures some templates reference beyond the tier sprite, keyed by the slot name
# used in the model's faces.
EXTRA_TEXTURES = {
    "layer": f"{MOD_REPO}/fabric/src/main/resources/assets/knavesneeds/textures/item/greathammer_layer.png",
}


def _ease(t):
    """Redistribute progress through the half turn without changing its duration.

    A constant-speed spin hits the held frame at full tilt and stops dead, and that
    velocity jump is what reads as jarring. Shaping progress with a cubic about the
    midpoint slows the weapon as it settles face-on and accelerates it away again, so the
    hold is eased into rather than slammed into.

    Blended against linear rather than used neat: a pure cubic stalls completely at
    face-on, which bunches frames there and stretches the hold well past HOLD_FRAMES.
    The blend keeps a floor under the speed so the hold stays the length it is set to.
    """
    shaped = 0.5 + 0.5 * (2 * t - 1) ** 3
    return (1 - EASING) * t + EASING * shaped


def hold_ms(step, face):
    """Duration for one frame of a weapon's turn.

    The face-on frame carries the whole hold as a single long frame rather than being
    repeated. Repeating it and leaning on the GIF encoder to merge duplicates worked, but
    that is a GIF-specific optimisation the WebP encoder does not share — it would have
    written every duplicate out. Stating the duration outright gives both formats the same
    frame list and the same playback.
    """
    return HOLD_FRAMES * FRAME_MS if step == face else FRAME_MS


def spin_angles():
    """Angles for one weapon's half turn, plus the index that should be held.

    Runs -90 to +90 so the held frame is face-on, showing the weapon exactly as the game
    draws it in an inventory slot. Both ends are edge-on, which is what lets the next
    weapon take over unnoticed — and easing sweeps through those ends fastest, so the
    handoff spends less time on the sliver where the swap could be spotted.
    """
    face = SPIN_FRAMES // 2
    angles = [-90 + 180 * _ease(step / SPIN_FRAMES) for step in range(SPIN_FRAMES)]
    return angles, face


# --- 2D sprite-squash renderer ----------------------------------------------------

def _shade(sprite, factor):
    r, g, b, a = sprite.split()
    lut = [min(255, int(i * factor)) for i in range(256)]
    return Image.merge("RGBA", (r.point(lut), g.point(lut), b.point(lut), a))


def _squash_frame(sprite, angle):
    turn = abs(math.cos(math.radians(angle)))
    scaled = sprite.resize((sprite.width * SCALE_2D, sprite.height * SCALE_2D), Image.NEAREST)
    scaled = _shade(scaled, MIN_BRIGHTNESS + (1 - MIN_BRIGHTNESS) * turn)

    # Clamp to 1px: a zero-width frame blinks out and reads as a dropped frame rather than
    # as an object turning through its own plane.
    width = max(1, round(scaled.width * turn))
    squashed = scaled.resize((width, scaled.height), Image.NEAREST)

    canvas = BASE_SPRITE * SCALE_2D
    frame = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    frame.paste(squashed, ((canvas - width) // 2, (canvas - squashed.height) // 2))
    return frame


def build_frames_2d(weapons):
    frames = []
    angles, face = spin_angles()
    for _, path in weapons:
        with Image.open(path) as handle:
            sprite = handle.convert("RGBA")
        for step, angle in enumerate(angles):
            frame = _squash_frame(sprite, angle)
            frames.append((frame, hold_ms(step, face)))
    return frames


# --- 3D model renderer ------------------------------------------------------------

def build_frames_3d(weapons):
    """Rasterise each weapon's real item model through the spin."""
    import numpy as np

    import render3d

    extras = {}
    for slot, path in EXTRA_TEXTURES.items():
        if os.path.isfile(path):
            with Image.open(path) as handle:
                extras[slot] = np.array(handle.convert("RGBA"))

    meshes = []
    for weapon, path in weapons:
        with Image.open(path) as handle:
            sprite = handle.convert("RGBA")
        quads, model = render3d.build_quads(weapon, sprite, TEMPLATES_DIR)
        quads = render3d.apply_display(quads, model, "gui")
        textures = dict(extras)
        textures["layer0"] = np.array(sprite)
        meshes.append((quads, textures))

    # One scale for the whole tier, so weapons stay honestly sized against each other and
    # nothing clips at any point in the spin.
    scale = render3d.fit_scale([quads for quads, _ in meshes], CANVAS, TILT)

    frames = []
    angles, face = spin_angles()
    for quads, textures in meshes:
        for step, angle in enumerate(angles):
            frame = render3d.to_image(
                render3d.render(quads, textures, angle, CANVAS, scale, TILT)
            )
            frames.append((frame, hold_ms(step, face)))
    return frames


# --- GIF assembly -----------------------------------------------------------------

def _to_gif_frame(frame):
    """Convert an RGBA frame to a palettised frame with a transparent index."""
    opaque = frame.getchannel("A").point(lambda a: 255 if a > 128 else 0)
    palettised = frame.convert("RGB").quantize(colors=TRANSPARENT_INDEX, method=Image.MEDIANCUT)
    palettised.paste(TRANSPARENT_INDEX, mask=opaque.point(lambda a: 255 - a))
    return palettised


def renderer_available(mode):
    if mode != "3d":
        return True
    try:
        import numpy  # noqa: F401

        import render3d  # noqa: F401
    except ImportError:
        return False
    return True


def _save_gif(frames, durations, dest):
    palettised = [_to_gif_frame(frame) for frame in frames]
    palettised[0].save(
        dest,
        save_all=True,
        append_images=palettised[1:],
        duration=durations,
        loop=0,
        # Each frame must clear the last: the weapon changes shape constantly and without
        # this the wide frames leave fringes behind the narrow ones.
        disposal=2,
        transparency=TRANSPARENT_INDEX,
    )


def _save_webp(frames, durations, dest):
    """Write the same animation as WebP.

    Lossless, because the source is pixel art and lossy WebP smears exactly the hard texel
    edges the render works to keep crisp. Encoded from the RGBA frames rather than the
    palettised ones so nothing is quantised on the way in.

    In practice the output is pixel-identical to the GIF — the busiest frame uses 228
    colours against GIF's ceiling of 255, and the render produces no partial alpha — so
    this is purely a size win, roughly half the bytes. The headroom only starts to matter
    if the art gains soft edges or SPEC_STEPS is raised enough to push past 255 colours,
    at which point the GIF becomes the lossy one.
    """
    frames[0].save(
        dest,
        format="WEBP",
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        lossless=True,
        quality=WEBP_QUALITY,
        method=WEBP_METHOD,
        minimize_size=True,
    )


SAVERS = {"gif": _save_gif, "webp": _save_webp}


def create_preview(weapons, dest_stem, mode="3d", formats=FORMATS):
    """Render one tier's spin loop and write it in each requested format.

    `weapons` is an ordered list of (weapon_name, sprite_path); `dest_stem` is the output
    path without an extension. The frames are rendered once and encoded per format, since
    rasterising is far more expensive than encoding. Returns the frame count.
    """
    if not weapons:
        return 0

    builder = build_frames_3d if mode == "3d" else build_frames_2d
    built = builder(weapons)
    frames = [frame for frame, _ in built]
    durations = [duration for _, duration in built]

    os.makedirs(os.path.dirname(dest_stem), exist_ok=True)
    for fmt in formats:
        SAVERS[fmt](frames, durations, f"{dest_stem}.{fmt}")
    return len(frames)
