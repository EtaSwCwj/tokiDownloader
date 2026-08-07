from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "assets"
PNG_PATH = ASSET_DIR / "toki-downloader.png"
ICO_PATH = ASSET_DIR / "toki-downloader.ico"


def build_icon(size: int = 1024) -> Image.Image:
    scale = size / 256

    def points(values: list[tuple[int, int]]) -> list[tuple[int, int]]:
        return [(round(x * scale), round(y * scale)) for x, y in values]

    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (8 * scale, 8 * scale, 248 * scale, 248 * scale),
        radius=52 * scale,
        fill="#101c30",
        outline="#4bd5f7",
        width=max(1, round(8 * scale)),
    )
    draw.rounded_rectangle(
        (21 * scale, 21 * scale, 235 * scale, 235 * scale),
        radius=39 * scale,
        outline="#203a59",
        width=max(1, round(4 * scale)),
    )
    draw.polygon(
        points(
            [
                (63, 61),
                (193, 61),
                (193, 89),
                (143, 89),
                (143, 150),
                (178, 115),
                (199, 136),
                (128, 207),
                (57, 136),
                (78, 115),
                (113, 150),
                (113, 89),
                (63, 89),
            ]
        ),
        fill="#45cbea",
    )
    draw.ellipse(
        (175 * scale, 34 * scale, 221 * scale, 80 * scale),
        fill="#ff5d8f",
    )
    draw.line(
        points([(188, 57), (195, 64), (209, 47)]),
        fill="white",
        width=max(1, round(7 * scale)),
        joint="curve",
    )
    return image


def main() -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    source = build_icon()
    png = source.resize((256, 256), Image.Resampling.LANCZOS)
    png.save(PNG_PATH, format="PNG", optimize=True)
    source.save(
        ICO_PATH,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(PNG_PATH)
    print(ICO_PATH)


if __name__ == "__main__":
    main()
