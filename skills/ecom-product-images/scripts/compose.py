#!/usr/bin/env python3
"""本地排版（Pillow）—— 尺寸规范化 + 确定性文字上版。

用法
  compose.py fit     <src> <out> <W> <H> [--bg #ffffff] [--mode contain|cover]
  compose.py overlay <src> <out> [--headline "..."] [--subtitle "..."] [--specs "a · b · c"]
                    [--w 1500] [--h 1500] [--font /path.ttf]
  compose.py font                 # 打印实际解析到的字体路径（doctor 用）

设计要点：文字永远本地绘制（拼写零错、字体可控），模型只负责画面。
"""
from __future__ import annotations

import pathlib
import sys

from PIL import Image, ImageDraw, ImageFont

SKILL_DIR = pathlib.Path(__file__).resolve().parent.parent
FONT_DIR = SKILL_DIR / "assets" / "fonts"

SYSTEM_FONTS = [
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def resolve_font(explicit: str | None = None) -> str:
    if explicit and pathlib.Path(explicit).exists():
        return explicit
    if FONT_DIR.exists():
        ttf = sorted(list(FONT_DIR.glob("*.ttf")) + list(FONT_DIR.glob("*.otf")))
        if ttf:
            bold = [p for p in ttf if "bold" in p.name.lower() or "bd" in p.stem.lower()]
            return str((bold or ttf)[0])
    for p in SYSTEM_FONTS:
        if pathlib.Path(p).exists():
            return p
    return ""  # 交给 Pillow 内置位图字体


def _load(size: int, path: str):
    if path:
        try:
            return ImageFont.truetype(path, size)
        except Exception:  # noqa: BLE001
            pass
    return ImageFont.load_default()


_NAMED = {"white": "ffffff", "black": "000000", "gray": "808080", "grey": "808080"}


def _hex(c: str) -> tuple[int, int, int]:
    c = str(c).strip().lstrip("#").lower()
    c = _NAMED.get(c, c)
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def cmd_fit(src: str, out: str, w: int, h: int, bg: str = "#ffffff", mode: str = "contain") -> int:
    img = Image.open(src)
    bg_rgb = _hex(bg)
    canvas = Image.new("RGB", (w, h), bg_rgb)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        sw, sh = img.size
        scale = max(w / sw, h / sh) if mode == "cover" else min(w / sw, h / sh)
        nw, nh = max(1, round(sw * scale)), max(1, round(sh * scale))
        resized = img.resize((nw, nh), Image.LANCZOS)
        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        layer.paste(resized, ((w - nw) // 2, (h - nh) // 2), resized)
        canvas = Image.alpha_composite(canvas.convert("RGBA"), layer).convert("RGB")
    else:
        img = img.convert("RGB")
        sw, sh = img.size
        scale = max(w / sw, h / sh) if mode == "cover" else min(w / sw, h / sh)
        nw, nh = max(1, round(sw * scale)), max(1, round(sh * scale))
        resized = img.resize((nw, nh), Image.LANCZOS)
        canvas.paste(resized, ((w - nw) // 2, (h - nh) // 2))
    canvas.save(out, "PNG")
    print(f"fit {src} -> {out} {w}x{h} ({mode})")
    return 0


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: int, max_lines: int = 3) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
            if len(lines) == max_lines:
                break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    return lines


def _band_stats(img: Image.Image, box: tuple[int, int, int, int]) -> float:
    region = img.crop(box).convert("L").resize((32, 32))
    px = region.tobytes()
    return sum(px) / max(1, len(px))


def cmd_overlay(src: str, out: str, headline: str = "", subtitle: str = "", specs: str = "",
                w: int = 0, h: int = 0, font_path: str | None = None) -> int:
    base = Image.open(src).convert("RGB")
    W, H = base.size if not (w and h) else (w, h)
    if (W, H) != base.size:
        base = base.resize((W, H), Image.LANCZOS)
    fp = resolve_font(font_path)
    draw = ImageDraw.Draw(base, "RGBA")

    margin = int(W * 0.055)
    items: list[tuple[str, int, bool]] = []  # (text, size, is_headline)
    if headline:
        items.append((headline, max(30, int(W * 0.082)), True))
    if subtitle:
        items.append((subtitle, max(20, int(W * 0.045)), False))
    if specs:
        for s in [x.strip() for x in specs.split("·") if x.strip()]:
            items.append((s, max(18, int(W * 0.036)), False))
    if not items:
        base.save(out, "PNG")
        print("overlay: 无文字，直接输出")
        return 0

    # 量算：先分行算高度
    blocks: list[tuple[list[str], int, bool, int]] = []
    total_h = 0
    for text, size, is_head in items:
        f = _load(size, fp)
        lines = _wrap(draw, text, f, W - margin * 2, 3 if is_head else 2)
        lh = int(size * 1.22)
        blocks.append((lines, size, is_head, lh))
        total_h += lh * len(lines) + int(size * 0.35)

    top = int(H * 0.62) - total_h // 2 if total_h < H * 0.32 else int(H * 0.06)
    top = max(margin, min(top, H - total_h - margin))
    # 文字带底色：按该区域亮度决定浅/深
    lum = _band_stats(base, (0, top - margin // 2, W, min(H, top + total_h + margin // 2)))
    light_bg = lum > 140
    panel = (255, 255, 255, 150) if light_bg else (17, 24, 39, 132)
    fg = (17, 24, 39, 255) if light_bg else (255, 255, 255, 255)
    shadow = (255, 255, 255, 90) if light_bg else (0, 0, 0, 110)

    pad = int(margin * 0.6)
    draw.rounded_rectangle([margin - pad, top - pad, W - margin + pad, top + total_h + pad],
                           radius=int(margin * 0.5), fill=panel)

    y = top
    for lines, size, is_head, lh in blocks:
        f = _load(size, fp)
        for line in lines:
            if is_head:
                draw.text((margin + 2, y + 2), line, font=f, fill=shadow)
            draw.text((margin, y), line, font=f, fill=fg)
            y += lh
        y += int(size * 0.35)
    base.save(out, "PNG")
    print(f"overlay -> {out} ({'dark text' if light_bg else 'light text'})")
    return 0


def cmd_composite(scene: str, product: str, out: str, w: int = 0, h: int = 0, scale: float = 0.62,
                  cx: float = 0.5, cy: float = 0.6, shadow: str = "soft") -> int:
    """把抠好的产品（RGBA）贴进场景图/纯背景：**产品像素零改动**，只缩放+落位+投投影。"""
    base = Image.open(scene).convert("RGB")
    W, H = (base.size if not (w and h) else (w, h))
    if (W, H) != base.size:
        base = base.resize((W, H), Image.LANCZOS)
    prod = Image.open(product).convert("RGBA")
    pw, ph = prod.size
    target = scale * min(W, H) if scale <= 1 else scale
    s = target / max(pw, ph)
    nw, nh = max(1, round(pw * s)), max(1, round(ph * s))
    prod = prod.resize((nw, nh), Image.LANCZOS)
    x, y = int(W * cx - nw / 2), int(H * cy - nh / 2)
    canvas = base.convert("RGBA")
    if shadow in ("soft", "hard"):
        blur = max(3, int(min(nw, nh) * (0.06 if shadow == "soft" else 0.02)))
        sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        dark = Image.new("RGBA", prod.size, (0, 0, 0, 120 if shadow == "soft" else 160))
        sh.paste(dark, (x + int(nw * 0.04), y + int(nh * 0.045)), prod.split()[3])
        from PIL import ImageFilter
        sh = sh.filter(ImageFilter.GaussianBlur(blur))
        canvas = Image.alpha_composite(canvas, sh)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    layer.paste(prod, (x, y), prod)
    canvas = Image.alpha_composite(canvas, layer)
    canvas.convert("RGB").save(out, "PNG")
    print(f"composite -> {out} ({W}x{H}, product {nw}x{nh} @ {cx},{cy}, shadow={shadow})")
    return 0


def cmd_blank(out: str, w: int, h: int, bg: str = "white") -> int:
    Image.new("RGB", (w, h), _hex(bg)).save(out, "PNG")
    print(f"blank -> {out} {w}x{h} {bg}")
    return 0


def main(argv: list[str]) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="compose")
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fit")
    f.add_argument("src"); f.add_argument("out"); f.add_argument("w", type=int); f.add_argument("h", type=int)
    f.add_argument("--bg", default="#ffffff"); f.add_argument("--mode", choices=["contain", "cover"], default="contain")
    o = sub.add_parser("overlay")
    o.add_argument("src"); o.add_argument("out")
    o.add_argument("--headline", default=""); o.add_argument("--subtitle", default=""); o.add_argument("--specs", default="")
    o.add_argument("--w", type=int, default=0); o.add_argument("--h", type=int, default=0); o.add_argument("--font")
    sub.add_parser("font")
    b = sub.add_parser("blank")
    b.add_argument("out"); b.add_argument("w", type=int); b.add_argument("h", type=int); b.add_argument("--bg", default="white")
    c = sub.add_parser("composite")
    c.add_argument("scene"); c.add_argument("product"); c.add_argument("out")
    c.add_argument("--w", type=int, default=0); c.add_argument("--h", type=int, default=0)
    c.add_argument("--scale", type=float, default=0.62, help="产品占短边比例（<=1）或目标像素（>1）")
    c.add_argument("--cx", type=float, default=0.5); c.add_argument("--cy", type=float, default=0.6)
    c.add_argument("--shadow", choices=["soft", "hard", "none"], default="soft")
    a = p.parse_args(argv)
    if a.cmd == "fit":
        return cmd_fit(a.src, a.out, a.w, a.h, a.bg, a.mode)
    if a.cmd == "overlay":
        return cmd_overlay(a.src, a.out, a.headline, a.subtitle, a.specs, a.w, a.h, a.font)
    if a.cmd == "composite":
        return cmd_composite(a.scene, a.product, a.out, a.w, a.h, a.scale, a.cx, a.cy, a.shadow)
    if a.cmd == "blank":
        return cmd_blank(a.out, a.w, a.h, a.bg)
    print(resolve_font())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
