"""Preview GIF generation.

Renders one looping GIF per material tier: each weapon in the tier spins toward the
camera, and at the moment the spin is edge-on — when the weapon is a sliver and nothing
is legible — the next weapon takes its place. The swap is invisible, so the tier reads as
a single object rotating through its whole weapon set.

`create_thumbnail()` reuses the same spin to build the mod's showcase image, swapping the
axis it cycles: one weapon across every material rather than one material across every
weapon, with the mod logo composited over it.

Two renderers are available:

- "3d" (default) rasterises the actual item models via render3d, so weapons have real
  thickness, real silhouette edges, and — for hand-built models like greathammer — real
  geometry. Needs numpy.
- "2d" squashes the sprite horizontally to fake the rotation. No numpy, and the fallback
  if render3d is unavailable.

Pillow is required either way. Both are imported lazily by main.py so JSON and texture
generation still work without them.
"""

import json
import math
import os

from PIL import Image, ImageChops

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

# Minecraft measures animation frametime in ticks; a tick is 50ms. Preview frames are
# FRAME_MS apart, so a texture's frame index has to be derived from elapsed milliseconds
# rather than from the spin step, or a 3-tick material and a 4-tick one would play at the
# same speed.
MC_TICK_MS = 50

# Camera tilt in degrees, looking slightly down at the weapon. Off the equator the top
# faces stay visible through the whole turn, which is what stops the spin reading as a
# flat shape rotating in place. 3D renderer only.
TILT = 12.0

# --- thumbnail tuning -------------------------------------------------------------
# The thumbnail cycles one weapon through every material in the mod — roughly twice as
# many entries as any tier has weapons — so it spins faster and holds shorter. Without
# that the loop would run past 40 seconds and nobody would watch it to the end.
THUMB_SPIN_FRAMES = 12
THUMB_HOLD_FRAMES = 3

# Square output, larger than the per-tier previews because the logo has to stay legible
# on top of the art. The weapon itself is still rendered at CANVAS and pasted in, so the
# extra size costs compositing rather than rasterising.
THUMB_CANVAS = 256

# Flat, opaque backdrop. Opaque for two reasons: the logo's drop shadow is partial alpha,
# which the GIF path binarises away against a transparent frame, and a thumbnail is going
# to be shown against an unknown page background anyway. Flat rather than a gradient
# because the backdrop is most of the frame and anything varying across it would be
# re-encoded on every one.
THUMB_BACKGROUND = (24, 22, 28, 255)

# Take every Nth frame when building the thumbnail GIF's shared palette. The loop holds
# each material for several frames, so a sample this coarse still sees every one of them.
PALETTE_SAMPLE = 4

# Integer scale for the logo, so it stays pixel-crisp. Placed bottom-centre, overlapping
# the low edge of the weapon — its outline and shadow are what keep it readable there.
LOGO_SCALE = 2
LOGO_MARGIN = 10

# Pixels the weapon is raised out of the square's centre. The logo claims the bottom of
# the frame, so a centred weapon leaves all the slack above it and the composition sits
# low; lifting it centres the weapon in what is actually left over.
THUMB_LIFT = 20

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


def hold_ms(step, face, hold_frames=HOLD_FRAMES):
    """Duration for one frame of a weapon's turn.

    The face-on frame carries the whole hold as a single long frame rather than being
    repeated. Repeating it and leaning on the GIF encoder to merge duplicates worked, but
    that is a GIF-specific optimisation the WebP encoder does not share — it would have
    written every duplicate out. Stating the duration outright gives both formats the same
    frame list and the same playback.
    """
    return hold_frames * FRAME_MS if step == face else FRAME_MS


def spin_angles(spin_frames=SPIN_FRAMES):
    """Angles for one weapon's half turn, plus the index that should be held.

    Runs -90 to +90 so the held frame is face-on, showing the weapon exactly as the game
    draws it in an inventory slot. Both ends are edge-on, which is what lets the next
    weapon take over unnoticed — and easing sweeps through those ends fastest, so the
    handoff spends less time on the sliver where the swap could be spotted.
    """
    face = spin_frames // 2
    angles = [-90 + 180 * _ease(step / spin_frames) for step in range(spin_frames)]
    return angles, face


# --- animated sprites -------------------------------------------------------------

def load_sprite(path):
    """A sprite's frames in playback order, and how long each is held.

    An animated texture ships as a vertical strip of square frames plus a sibling
    `.png.mcmeta` naming the frame time in ticks. Nothing downstream can cope with the
    strip itself — the 3D path would extrude a twelve-frames-tall slab and the 2D one
    would squash a 1:12 sliver — so the split has to happen before anything else looks at
    the image.

    Returns `(frames, frametime_ms)`, with `frametime_ms` None for a still sprite so
    callers can tell "one frame" from "animated but currently on frame one".
    """
    with Image.open(path) as handle:
        sheet = handle.convert("RGBA")

    # item textures are square, so a strip is unambiguous from its own dimensions. That is
    # the fallback rather than the rule: a strip whose .mcmeta went missing should still
    # preview as an animation instead of as one very tall weapon.
    count = sheet.height // sheet.width if sheet.width and sheet.height > sheet.width else 1
    if sheet.width and sheet.height % sheet.width:
        count = 1

    ticks, order = 1, None
    meta_path = path + ".mcmeta"
    if os.path.isfile(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as handle:
                animation = json.load(handle).get("animation", {})
        except (OSError, ValueError):
            animation = {}
        ticks = animation.get("frametime", 1) or 1
        # `frames` is a playback order over the strip, not the strip itself. Entries may be
        # bare indices or {"index": n, "time": t}; per-frame times are rare and ignored,
        # since the preview only needs the animation to read as moving at the right speed.
        listed = animation.get("frames")
        if listed:
            order = [f.get("index", 0) if isinstance(f, dict) else f for f in listed]

    if count <= 1:
        return [sheet], None

    height = sheet.height // count
    strip = [sheet.crop((0, i * height, sheet.width, (i + 1) * height)) for i in range(count)]
    if order:
        strip = [strip[i % count] for i in order]
    return strip, max(1, int(ticks)) * MC_TICK_MS


def _union_sprite(frames):
    """One sprite carrying the widest silhouette any frame reaches.

    The 3D path builds geometry from the sprite's alpha, once, and then reuses it for every
    frame of the spin. If a treatment adds texels that are clear in the frame the mesh was
    built from, those texels would have no surface to land on and would silently vanish.
    Taking the union means every frame has somewhere to draw; frames where a texel is clear
    just render clear.
    """
    if len(frames) == 1:
        return frames[0]
    union = frames[0].copy()
    alpha = union.getchannel("A")
    for frame in frames[1:]:
        alpha = ImageChops.lighter(alpha, frame.getchannel("A"))
    union.putalpha(alpha)
    return union


def weapon_timeline(angles, face, frame_count, frametime_ms,
                    hold_frames=HOLD_FRAMES, frame_ms=FRAME_MS):
    """`(angle, texture_index, duration_ms)` for one weapon's half turn.

    A still weapon carries the whole hold as a single long frame, which is what
    `hold_ms()` is for. An animated one cannot: freezing the texture for the length of the
    hold stops the material moving at exactly the moment the preview has stopped to show
    it off. So an animated weapon spends the hold as real frames instead — same total
    duration, texture still advancing.

    The index advances on elapsed milliseconds rather than on spin steps, so a 2-tick
    material visibly runs faster than a 4-tick one instead of both playing at spin speed.
    """
    animated = frame_count > 1 and frametime_ms
    elapsed, out = 0, []
    for step, angle in enumerate(angles):
        if animated and step == face:
            for _ in range(hold_frames):
                out.append((angle, (elapsed // frametime_ms) % frame_count, frame_ms))
                elapsed += frame_ms
            continue
        duration = hold_ms(step, face, hold_frames)
        index = (elapsed // frametime_ms) % frame_count if animated else 0
        out.append((angle, index, duration))
        elapsed += duration
    return out


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


def build_frames_2d(weapons, spin_frames=SPIN_FRAMES, hold_frames=HOLD_FRAMES):
    frames = []
    angles, face = spin_angles(spin_frames)
    for _, path in weapons:
        sprites, frametime = load_sprite(path)
        # the squash depends only on the angle, so an animated weapon still costs one
        # resize per emitted frame rather than one per texture frame per angle
        for angle, index, duration in weapon_timeline(angles, face, len(sprites),
                                                      frametime, hold_frames):
            frames.append((_squash_frame(sprites[index], angle), duration))
    return frames


# --- 3D model renderer ------------------------------------------------------------

def build_frames_3d(weapons, spin_frames=SPIN_FRAMES, hold_frames=HOLD_FRAMES):
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
        sprites, frametime = load_sprite(path)
        # geometry is built once per weapon and reused for every frame of the spin, so it
        # has to come from the union silhouette rather than from whichever frame happened
        # to be first
        quads, model = render3d.build_quads(weapon, _union_sprite(sprites), TEMPLATES_DIR)
        quads = render3d.apply_display(quads, model, "gui")
        # one array per texture frame, not one per rendered frame: a 12-frame material
        # spun over 24 angles would otherwise convert the same sprite dozens of times
        layers = [dict(extras, layer0=np.array(sprite)) for sprite in sprites]
        meshes.append((quads, layers, frametime))

    # One scale for the whole tier, so weapons stay honestly sized against each other and
    # nothing clips at any point in the spin.
    scale = render3d.fit_scale([quads for quads, _, _ in meshes], CANVAS, TILT)

    frames = []
    angles, face = spin_angles(spin_frames)
    for quads, layers, frametime in meshes:
        for angle, index, duration in weapon_timeline(angles, face, len(layers),
                                                      frametime, hold_frames):
            frame = render3d.to_image(
                render3d.render(quads, layers[index], angle, CANVAS, scale, TILT)
            )
            frames.append((frame, duration))
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


# --- thumbnail assembly -----------------------------------------------------------

def _save_thumbnail_gif(frames, durations, dest):
    """Write the thumbnail as GIF, exploiting the fact that its frames are opaque.

    The per-tier saver cannot do any of this: its frames are transparent, so every frame
    has to clear the last (disposal 2) and each is written whole. Here the backdrop and
    the logo are identical in every frame — most of the picture — and only the weapon
    changes, so leaving the previous frame in place (disposal 1) lets the encoder write
    just the rectangle that actually moved.

    That only works if consecutive frames share a palette, hence quantising every frame
    against one palette built from a sample of the loop rather than letting each pick its
    own 255 colours. Together the two take the file from ~2.5MB to under 1MB. Spreading
    one palette over 32 materials does cost a little colour accuracy, but at thumbnail
    size it is not visible against the WebP.
    """
    sample = frames[::PALETTE_SAMPLE]
    strip = Image.new("RGB", (sample[0].width, sample[0].height * len(sample)))
    for index, frame in enumerate(sample):
        strip.paste(frame.convert("RGB"), (0, index * frame.height))
    palette = strip.quantize(colors=256, method=Image.MEDIANCUT)

    # No dithering: the source is flat-shaded pixel art, and dithering would scatter noise
    # across the backdrop that then has to be re-encoded every frame.
    quantised = [frame.convert("RGB").quantize(palette=palette, dither=Image.NONE)
                 for frame in frames]
    quantised[0].save(
        dest,
        save_all=True,
        append_images=quantised[1:],
        duration=durations,
        loop=0,
        disposal=1,
    )


THUMB_SAVERS = {"gif": _save_thumbnail_gif, "webp": _save_webp}


def _load_logo(logo_path):
    """Load and upscale the mod logo, or None if it isn't on disk.

    Scaled with NEAREST at an integer factor: the logo is pixel art of the same kind as
    the sprites, and anything smoother would leave it looking soft against them.
    """
    if not logo_path or not os.path.isfile(logo_path):
        return None
    with Image.open(logo_path) as handle:
        logo = handle.convert("RGBA")
    return logo.resize((logo.width * LOGO_SCALE, logo.height * LOGO_SCALE), Image.NEAREST)


def _compose_thumbnail(frame, logo):
    """Drop one rendered spin frame onto the thumbnail backdrop and stamp the logo on.

    The weapon is centred in the square and the logo sits bottom-centre, overlapping the
    low edge of the art rather than being given a clear band of its own — the logo carries
    its own outline and shadow, so it reads over the weapon, and a reserved band would cost
    the weapon a third of the frame.
    """
    canvas = Image.new("RGBA", (THUMB_CANVAS, THUMB_CANVAS), THUMB_BACKGROUND)
    canvas.alpha_composite(frame, ((THUMB_CANVAS - frame.width) // 2,
                                   (THUMB_CANVAS - frame.height) // 2 - THUMB_LIFT))
    if logo is not None:
        canvas.alpha_composite(logo, ((THUMB_CANVAS - logo.width) // 2,
                                      THUMB_CANVAS - logo.height - LOGO_MARGIN))
    return canvas


def create_thumbnail(weapons, dest_stem, logo_path=None, mode="3d", formats=FORMATS):
    """Render the mod's showcase loop: one weapon spinning through every material.

    Same call shape as create_preview() and the same spin machinery, but `weapons` here is
    one entry per material rather than one per weapon, so the loop reads as a single item
    changing material instead of a single material changing item. Runs at the thumbnail
    spin speed and composites the logo over every frame. Returns the frame count.
    """
    if not weapons:
        return 0

    builder = build_frames_3d if mode == "3d" else build_frames_2d
    built = builder(weapons, THUMB_SPIN_FRAMES, THUMB_HOLD_FRAMES)
    logo = _load_logo(logo_path)

    frames = [_compose_thumbnail(frame, logo) for frame, _ in built]
    durations = [duration for _, duration in built]

    os.makedirs(os.path.dirname(dest_stem), exist_ok=True)
    for fmt in formats:
        THUMB_SAVERS[fmt](frames, durations, f"{dest_stem}.{fmt}")
    return len(frames)


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
