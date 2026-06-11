#!/usr/bin/env python3
"""Generate the PWA PNG icons from the Naiad drop logo.

The app icon must be a PNG for Android install banners and iOS home-screen
icons (SVG is not universally supported there). This script redraws the
favicon's water-drop geometry (see src/frontend/public/favicon.svg) with
Pillow and writes the icon set into src/frontend/public/icons/.

Run from the repository root after changing the logo:

    python3 scripts/generate_pwa_icons.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

OUT_DIR = Path(__file__).resolve().parents[1] / "src" / "frontend" / "public" / "icons"

# Colors from the favicon / design tokens.
DROP = (26, 122, 138, 255)  # #1a7a8a
WAVE_1 = (94, 200, 216, 191)  # #5ec8d8, 75 %
WAVE_2 = (184, 234, 242, 115)  # #b8eaf2, 45 %
GLARE = (184, 234, 242, 64)  # #b8eaf2, 25 %
INNER = (94, 200, 216, 38)  # #5ec8d8, 15 %
BACKGROUND = (12, 20, 19, 255)  # #0c1413 (--n-bg)

# The drop geometry in the favicon's coordinate space (drop spans x 8..116,
# y 0..153). Each segment is a cubic bezier (p0, c1, c2, p1).
OUTER = [
    ((62, 0), (62, 0), (116, 63), (116, 100)),
    ((116, 100), (116, 131), (92, 153), (62, 153)),
    ((62, 153), (32, 153), (8, 131), (8, 100)),
    ((8, 100), (8, 63), (62, 0), (62, 0)),
]
INNER_PATH = [
    ((62, 22), (62, 22), (100, 68), (100, 96)),
    ((100, 96), (100, 118), (83, 136), (62, 136)),
    ((62, 136), (41, 136), (24, 118), (24, 96)),
    ((24, 96), (24, 68), (62, 22), (62, 22)),
]
WAVE_1_PATH = [
    ((20, 100), (32, 90), (50, 95), (62, 90)),
    ((62, 90), (74, 85), (88, 90), (104, 100)),
]
WAVE_2_PATH = [
    ((16, 116), (30, 105), (50, 111), (62, 106)),
    ((62, 106), (74, 101), (90, 106), (108, 116)),
]

DROP_W, DROP_H = 124.0, 153.0
DROP_X0 = 8.0


def _bezier(seg: tuple, steps: int = 64) -> list[tuple[float, float]]:
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = seg
    pts = []
    for i in range(steps + 1):
        u = i / steps
        v = 1.0 - u
        x = v**3 * x0 + 3 * v**2 * u * x1 + 3 * v * u**2 * x2 + u**3 * x3
        y = v**3 * y0 + 3 * v**2 * u * y1 + 3 * v * u**2 * y2 + u**3 * y3
        pts.append((x, y))
    return pts


def _path_points(path: list, tf) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for seg in path:
        pts.extend(p for p in map(tf, _bezier(seg)) if not pts or p != pts[-1])
    return pts


def _draw_drop(size: int, *, background: tuple | None, drop_scale: float) -> Image.Image:
    """Render the drop centered on a square canvas at 4x and downscale (AA)."""
    ss = 4
    canvas = size * ss
    img = Image.new("RGBA", (canvas, canvas), background or (0, 0, 0, 0))

    scale = canvas * drop_scale / DROP_H
    off_x = (canvas - DROP_W * scale) / 2.0
    off_y = (canvas - DROP_H * scale) / 2.0

    def tf(p: tuple[float, float]) -> tuple[float, float]:
        return ((p[0] - DROP_X0) * scale + off_x, p[1] * scale + off_y)

    # The drop silhouette doubles as a clip mask: translucent decorations are
    # alpha-composited (ImageDraw alone would overwrite the fill) and clipped so
    # the wave strokes cannot poke outside the body.
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).polygon(_path_points(OUTER, tf), fill=255)
    body = Image.new("RGBA", img.size, DROP)
    img.paste(body, (0, 0), mask)

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    odraw.polygon(_path_points(INNER_PATH, tf), fill=INNER)
    odraw.line(_path_points(WAVE_1_PATH, tf), fill=WAVE_1, width=max(1, round(2.5 * scale)))
    odraw.line(_path_points(WAVE_2_PATH, tf), fill=WAVE_2, width=max(1, round(1.8 * scale)))

    glare = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gw, gh = 6 * scale, 11 * scale
    gx, gy = tf((42, 65))
    ImageDraw.Draw(glare).ellipse((gx - gw, gy - gh, gx + gw, gy + gh), fill=GLARE)
    overlay.alpha_composite(glare.rotate(20, center=(gx, gy), resample=Image.BICUBIC))

    overlay.putalpha(ImageChops.multiply(overlay.getchannel("A"), mask))
    img.alpha_composite(overlay)

    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for size in (192, 512):
        _draw_drop(size, background=None, drop_scale=0.92).save(OUT_DIR / f"icon-{size}.png")
        # Maskable icons need the artwork inside the ~80 % safe zone on an
        # opaque background, or launchers crop the drop's tip away.
        _draw_drop(size, background=BACKGROUND, drop_scale=0.62).save(
            OUT_DIR / f"icon-maskable-{size}.png"
        )
    # iOS home-screen icon (Safari ignores manifest icons): opaque, 180 px.
    _draw_drop(180, background=BACKGROUND, drop_scale=0.72).save(OUT_DIR / "apple-touch-icon.png")
    print(f"Icons written to {OUT_DIR}")


if __name__ == "__main__":
    main()
