"""Preview GIF generation.

Renders one looping GIF per material tier: each weapon in the tier spins toward the
camera like a coin, and at the moment the spin is edge-on — when the sprite is only a
sliver wide and nothing is legible — the texture swaps to the next weapon. The swap is
invisible, so the tier reads as a single object rotating through its whole weapon set.

This is the only part of the project that needs a third-party package (Pillow). It is
imported lazily by main.py so JSON generation still works without it.
"""

import math
import os

from PIL import Image

# --- animation tuning -------------------------------------------------------------
# Frames per half turn. Each weapon owns exactly one half turn: it unfolds from edge-on,
# passes through full-face, and folds back to edge-on before handing off to the next.
SPIN_FRAMES = 18
# Extra frames held at full-face, so each weapon is actually readable before it spins on.
HOLD_FRAMES = 10
FRAME_MS = 40

# Sprites come in 16/32/48 px depending on weapon type, and that difference is meaningful
# — a halberd really is drawn three times the size of a sai. Everything is composited onto
# a canvas sized for the largest sprite so those proportions survive.
BASE_SPRITE = 48
SCALE = 4
CANVAS = BASE_SPRITE * SCALE

# Palette index reserved for transparency. quantize() below is capped at 255 colours so
# this one stays free.
TRANSPARENT_INDEX = 255

# How much the sprite darkens as it turns away from the camera, which is what sells the
# rotation as 3D rather than a horizontal squash.
MIN_BRIGHTNESS = 0.55


def _shade(sprite, factor):
    """Scale RGB brightness by factor, leaving alpha untouched."""
    r, g, b, a = sprite.split()
    lut = [min(255, int(i * factor)) for i in range(256)]
    return Image.merge("RGBA", (r.point(lut), g.point(lut), b.point(lut), a))


def _spin_frame(sprite, angle):
    """Composite one frame of the coin spin at the given angle in degrees.

    Width follows |cos(angle)|, so the sprite is full-face at 180 degrees and edge-on at
    90 and 270. The sprite is never mirrored past edge-on: these are flat textures with no
    meaningful back face, and a mirrored weapon reads as wrong rather than as rotated.
    """
    turn = abs(math.cos(math.radians(angle)))

    scaled = sprite.resize((sprite.width * SCALE, sprite.height * SCALE), Image.NEAREST)
    scaled = _shade(scaled, MIN_BRIGHTNESS + (1 - MIN_BRIGHTNESS) * turn)

    # Clamp to 1px: a zero-width frame would blink out and read as a dropped frame rather
    # than as an object turning through its own plane.
    width = max(1, round(scaled.width * turn))
    squashed = scaled.resize((width, scaled.height), Image.NEAREST)

    frame = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    frame.paste(squashed, ((CANVAS - width) // 2, (CANVAS - squashed.height) // 2))
    return frame


def _to_gif_frame(frame):
    """Convert an RGBA frame to a palettised frame with a transparent index."""
    opaque = frame.getchannel("A").point(lambda a: 255 if a > 128 else 0)
    palettised = frame.convert("RGB").quantize(colors=TRANSPARENT_INDEX, method=Image.MEDIANCUT)
    palettised.paste(TRANSPARENT_INDEX, mask=opaque.point(lambda a: 255 - a))
    return palettised


def build_frames(sprite_paths):
    """Build the full frame list for one tier from its ordered weapon sprites."""
    frames = []
    face = SPIN_FRAMES // 2
    for path in sprite_paths:
        with Image.open(path) as handle:
            sprite = handle.convert("RGBA")
        for step in range(SPIN_FRAMES):
            # Stop one step short of 270 degrees: that frame is the next weapon's opening
            # edge-on frame, and emitting both would stall the spin for a beat.
            angle = 90 + 180 * step / SPIN_FRAMES
            frame = _to_gif_frame(_spin_frame(sprite, angle))
            frames.append(frame)
            if step == face:
                frames.extend([frame] * (HOLD_FRAMES - 1))
    return frames


def create_preview_gif(sprite_paths, dest):
    """Render one tier's spin loop to dest. Returns the number of frames written."""
    frames = build_frames(sprite_paths)
    if not frames:
        return 0

    os.makedirs(os.path.dirname(dest), exist_ok=True)
    frames[0].save(
        dest,
        save_all=True,
        append_images=frames[1:],
        duration=FRAME_MS,
        loop=0,
        # Each frame must clear the last: the sprite changes shape constantly and without
        # this the wide frames leave fringes behind the narrow ones.
        disposal=2,
        transparency=TRANSPARENT_INDEX,
    )
    return len(frames)
