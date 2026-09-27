#!/usr/bin/env python3
"""本地图片翻译（离线·保真档）——不依赖任何云凭证

与云端保真档（阿里云 alimt.TranslateImage）等价的三件事，全部本地做：
  1. 「文字在商品主体上就不翻」= 用本地抠图掩膜做覆盖判定（ignoreEntityRecognize 的确定性等价）
  2. 擦字 + 原位置重排（保留版式，不重绘产品一像素）
  3. 自证：产出再 OCR 一遍，主体外文字==译文、主体内文字==原文（字节级判据，不用视觉模型）

用法
  translate_local.py 图.jpg --to en [--from auto] [--outdir DIR] [--matte-model u2net]
                    [--translate-inside-product] [--font PATH] [--no-verify]
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import pathlib
import re
import sys
import time
import urllib.request

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import matte as matte_mod  # noqa: E402

FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/msyh.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
LANG_NAME = {"en": "English", "ro": "Romanian", "ru": "Russian", "zh": "Simplified Chinese",
             "de": "German", "fr": "French", "es": "Spanish", "pt": "Portuguese", "it": "Italian",
             "nl": "Dutch", "pl": "Polish", "tr": "Turkish", "ja": "Japanese", "ko": "Korean",
             "ar": "Arabic", "th": "Thai", "bg": "Bulgarian", "hu": "Hungarian", "cs": "Czech"}


# ---------------------------------------------------------------- 环境 / 通道
def load_env() -> dict:
    env = dict(os.environ)
    for p in (pathlib.Path.home() / ".hermes" / ".env", pathlib.Path.home() / ".env"):
        if p.exists():
            for line in p.read_text(errors="ignore").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return env


ENV = load_env()


def ds_translate(items: list[dict], to_lang: str, from_lang: str = "auto") -> dict[str, str]:
    """一次批量翻译（DeepSeek），返回 {原文: 译文}。保持电商文案口径：短、直白、不扩写。"""
    key = ENV.get("DEEPSEEK_API_KEY")
    if not key:
        raise SystemExit("缺 DEEPSEEK_API_KEY（翻译用；也可换任意兼容 chat 的通道，改 ds_translate 即可）")
    base = ENV.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    model = ENV.get("DEEPSEEK_MODEL", "deepseek-flash")
    payload = {
        "model": model,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content":
             f"You are an e-commerce image copy translator. Translate each item from {from_lang} into "
             f"{LANG_NAME.get(to_lang, to_lang)}. Rules: keep it short and punchy (never longer than 1.4x the "
             "original character count), keep ALL-CAPS if the source is ALL-CAPS, keep numbers/units/model codes "
             "verbatim, do NOT add explanations, do NOT translate brand names or model numbers. "
             'Return STRICT JSON: {"items":[{"id":<same id>,"t":"<translation>"}]}'},
            {"role": "user", "content": json.dumps({"items": items}, ensure_ascii=False)},
        ],
    }
    req = urllib.request.Request(base + "/chat/completions", data=json.dumps(payload).encode(),
                                headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=180) as r:
        body = json.loads(r.read().decode())
    txt = body["choices"][0]["message"]["content"]
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        raise RuntimeError(f"翻译通道返回异常：{txt[:200]}")
    out = json.loads(m.group(0))
    return {str(it["id"]): str(it["t"]).strip() for it in out["items"]}


# ---------------------------------------------------------------- OCR
_OCR = None


def ocr(img_path: pathlib.Path) -> list[dict]:
    global _OCR
    if _OCR is None:
        from rapidocr_onnxruntime import RapidOCR
        _OCR = RapidOCR()
    res, _ = _OCR(str(img_path))
    items = []
    for box, text, score in (res or []):
        xs = [float(p[0]) for p in box]
        ys = [float(p[1]) for p in box]
        items.append({"box": [[round(float(p[0]), 1), round(float(p[1]), 1)] for p in box],
                      "rect": [int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))],
                      "text": str(text).strip(), "score": round(float(score), 3)})
    return [i for i in items if i["text"]]


# ---------------------------------------------------------------- 擦字 / 重排
def _ring_color(arr: np.ndarray, rect: list[int], pad: int = 4) -> tuple[tuple[int, int, int], float]:
    """取框外一圈像素的中位色（背景色）与其标准差（判断背景是否平整）。"""
    H, W = arr.shape[:2]
    x0, y0, x1, y1 = rect
    ox0, oy0 = max(0, x0 - pad), max(0, y0 - pad)
    ox1, oy1 = min(W, x1 + pad), min(H, y1 + pad)
    outer = arr[oy0:oy1, ox0:ox1].reshape(-1, 3)
    inner = arr[max(0, y0):min(H, y1), max(0, x0):min(W, x1)].reshape(-1, 3)
    if inner.size and len(outer) > len(inner):
        # 去掉内部像素，只留环带
        o = arr[oy0:oy1, ox0:ox1]
        m = np.ones(o.shape[:2], bool)
        m[max(0, y0) - oy0:max(0, y0) - oy0 + inner.shape[0] // max(1, (x1 - x0)),
          max(0, x0) - ox0:max(0, x0) - ox0 + (x1 - x0)] = False
        ring = o[m].reshape(-1, 3)
    else:
        ring = outer
    if ring.size == 0:
        ring = outer
    med = np.median(ring, axis=0).astype(int)
    return (int(med[0]), int(med[1]), int(med[2])), float(ring.std())


def _text_color(arr: np.ndarray, rect: list[int], bg: tuple[int, int, int]) -> tuple[int, int, int]:
    """字色 = 框内与背景色差异最大的那一簇像素的均值（不靠猜黑/白）。"""
    x0, y0, x1, y1 = rect
    H, W = arr.shape[:2]
    patch = arr[max(0, y0):min(H, y1), max(0, x0):min(W, x1)].reshape(-1, 3).astype(int)
    if patch.size == 0:
        return (0, 0, 0)
    d = np.abs(patch - np.array(bg)).sum(axis=1)
    ink = patch[d >= np.percentile(d, 75)]
    c = ink.mean(axis=0).astype(int)
    return (int(c[0]), int(c[1]), int(c[2]))


def erase_rect(img: Image.Image, rect: list[int], bg: tuple[int, int, int], feather: int = 3) -> None:
    """用背景中位色盖掉文字，边缘羽化（对纯色/渐变底图干净；纹理底会留痕，manifest 里会标）。"""
    x0, y0, x1, y1 = rect
    W, H = img.size
    x0e, y0e = max(0, x0 - feather), max(0, y0 - feather)
    x1e, y1e = min(W, x1 + feather), min(H, y1 + feather)
    patch = Image.new("RGB", (x1e - x0e, y1e - y0e), bg)
    img.paste(patch, (x0e, y0e))
    if feather:  # 边缘轻微模糊，避免硬边
        band = img.crop((x0e, y0e, x1e, y1e)).filter(ImageFilter.GaussianBlur(1.2))
        img.paste(band, (x0e, y0e))


def _fit_text(draw: ImageDraw.ImageDraw, text: str, box_w: int, box_h: int, font_path: str,
              max_size: int | None = None) -> tuple[ImageFont.FreeTypeFont, list[str], int, int]:
    """二分查找最大的能塞进框的字号 + 换行方案。"""
    words = text.split()
    lo, hi = 6, max(8, min(box_h, (max_size or box_w)))
    best = None
    for _ in range(14):
        mid = (lo + hi) // 2
        f = ImageFont.truetype(font_path, mid)
        lines, cur = [], ""
        for w in words:
            cand = (cur + " " + w).strip()
            lw = draw.textlength(cand, font=f)
            if lw <= box_w or not cur:
                cur = cand
            else:
                lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        widest = max((draw.textlength(l, font=f) for l in lines), default=0)
        line_h = mid * 1.18
        ok = widest <= box_w and line_h * len(lines) <= box_h
        if ok:
            best = (f, lines, int(widest), int(line_h * len(lines)))
            lo = mid + 1
        else:
            hi = mid - 1
    if best is None:
        f = ImageFont.truetype(font_path, 6)
        lines = [text]
        best = (f, lines, int(draw.textlength(text, font=f)), 8)
    return best[0], best[1], best[2], best[3]


def render_text(img: Image.Image, rect: list[int], text: str, font_path: str,
                color: tuple[int, int, int], bold: bool) -> dict:
    """在框内居中重排文字。返回实际用到的字号/行数（写进 manifest 便于自查）。"""
    x0, y0, x1, y1 = rect
    bw, bh = x1 - x0, y1 - y0
    draw = ImageDraw.Draw(img)
    font, lines, tw, th = _fit_text(draw, text, bw, bh, font_path)
    size = font.size
    line_h = size * 1.18
    y = y0 + (bh - line_h * len(lines)) / 2
    for ln in lines:
        lw = draw.textlength(ln, font=font)
        x = x0 + (bw - lw) / 2
        draw.text((x, y), ln, font=font, fill=color,
                  stroke_width=1 if bold else 0, stroke_fill=color)
        y += line_h
    return {"font_size": size, "lines": len(lines), "text_w": int(tw), "text_h": int(th)}


# ---------------------------------------------------------------- 覆盖判定（= ignoreEntityRecognize 的本地等价）
def coverage_in_product(mask: Image.Image, rect: list[int], grid: int = 12) -> float:
    x0, y0, x1, y1 = rect
    a = np.asarray(mask)
    H, W = a.shape[:2]
    xs = np.linspace(max(0, x0), max(0, x1 - 1), grid).astype(int)
    ys = np.linspace(max(0, y0), max(0, y1 - 1), grid).astype(int)
    vals = a[np.clip(ys, 0, H - 1)[:, None], np.clip(xs, 0, W - 1)[None, :]]
    return float((vals > 128).mean())


# ---------------------------------------------------------------- 校验
_HOMOGLYPH = str.maketrans({"0": "o", "1": "l", "5": "s", "8": "b", "2": "z", "6": "g", "9": "g"})


def _norm(s: str) -> str:
    """OCR 比对用的规范化：只留字母数字（罗/俄/欧语字符保留），并把常见形近字符归一（O↔0、I↔1…）。"""
    s = re.sub(r"[^0-9a-z\u0400-\u04ff\u00c0-\u024f]+", "", s.lower())
    return s.translate(_HOMOGLYPH)


def _sim(a: str, b: str) -> float:
    """规范化后的字符集相似度（Jaccard on bigrams，短串退化为字符集比较）。"""
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ga = {a[i:i + 2] for i in range(len(a) - 1)} or set(a)
    gb = {b[i:i + 2] for i in range(len(b) - 1)} or set(b)
    return len(ga & gb) / len(ga | gb)


def _iou(r1: list[int], r2: list[int]) -> float:
    x0, y0 = max(r1[0], r2[0]), max(r1[1], r2[1])
    x1, y1 = min(r1[2], r2[2]), min(r1[3], r2[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    inter = (x1 - x0) * (y1 - y0)
    u = (r1[2] - r1[0]) * (r1[3] - r1[1]) + (r2[2] - r2[0]) * (r2[3] - r2[1]) - inter
    return inter / u if u else 0.0


def verify(out_path: pathlib.Path, plan: list[dict]) -> dict:
    """确定性验收：产出再 OCR，按位置对上原框，逐条比对预期文字。"""
    got = ocr(out_path)
    rows = []
    for it in plan:
        best, bi = 0.0, None
        for o in got:
            v = _iou(it["rect"], o["rect"])
            if v > best:
                best, bi = v, o
        seen = bi["text"] if bi else ""
        expect = it["expected"]
        s = _sim(expect, seen)
        rows.append({"text": it["text"], "expected": expect, "seen": seen,
                     "iou": round(best, 2), "similarity": round(s, 2),
                     "action": it["action"],
                     "pass": bool(s >= (0.99 if it["action"] == "keep" else 0.6) and best >= 0.1)})
    ok = sum(1 for r in rows if r["pass"])
    return {"checked": len(rows), "passed": ok, "failed": len(rows) - ok,
            "all_pass": ok == len(rows), "rows": rows}


# ---------------------------------------------------------------- 主流程
def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="translate_local", description="本地图片翻译（离线保真档，无需云凭证）")
    p.add_argument("src")
    p.add_argument("--to", required=True, help="目标语言代码，如 en/ro/ru/zh")
    p.add_argument("--from", dest="from_", default="auto")
    p.add_argument("--outdir", help="输出目录（默认 <图目录>/translate_local）")
    p.add_argument("--matte-model", default="u2net", choices=["u2net", "isnet-general-use"])
    p.add_argument("--translate-inside-product", action="store_true",
                   help="连商品主体/包装上的文字也翻（默认不翻 —— 用户的硬口径）")
    p.add_argument("--font", help="重排字体路径（默认自动找 Arial Unicode / DejaVu）")
    p.add_argument("--min-score", type=float, default=0.5, help="OCR 置信度低于此值不翻（保留原样更安全）")
    p.add_argument("--no-verify", action="store_true")
    a = p.parse_args(argv)

    src = pathlib.Path(a.src).expanduser()
    if not src.exists():
        raise SystemExit(f"图不存在：{src}")
    outdir = pathlib.Path(a.outdir) if a.outdir else src.parent / "translate_local"
    outdir.mkdir(parents=True, exist_ok=True)
    font_path = a.font or next((f for f in FONT_CANDIDATES if pathlib.Path(f).exists()), None)
    if not font_path:
        raise SystemExit("找不到可用字体，用 --font 指定（需覆盖目标语言字符集）")

    t0 = time.time()
    print(f"① OCR：{src.name}")
    items = ocr(src)
    for i, it in enumerate(items):
        it["id"] = i
    print(f"   识别 {len(items)} 个文字块")

    print(f"② 抠图掩膜（判断文字是否在商品主体上，模型 {a.matte_model}）")
    rgb, mask = matte_mod.compute_alpha(src, a.matte_model)
    arr = np.asarray(rgb).copy()
    for it in items:
        it["coverage"] = round(coverage_in_product(mask, it["rect"]), 2)
        it["on_product"] = it["coverage"] >= 0.6
        it["skip"] = bool(it["on_product"] and not a.translate_inside_product)
        it["skip_reason"] = "在商品主体/包装上（按口径不翻）" if it["skip"] else (
            "OCR 置信度低" if it["score"] < a.min_score else "")
    todo = [i for i in items if not i["skip"] and i["score"] >= a.min_score]
    print(f"   主体上的文字不翻：{sum(1 for i in items if i['skip'])} 块；待翻：{len(todo)} 块；"
          f"低置信保留：{sum(1 for i in items if not i['skip'] and i['score'] < a.min_score)} 块")

    tr: dict[str, str] = {}
    if todo:
        print(f"③ 翻译 → {LANG_NAME.get(a.to, a.to)}（{len(todo)} 条）")
        tr = ds_translate([{"id": i["id"], "text": i["text"]} for i in todo], a.to, a.from_)
        for i in todo:
            i["translated"] = tr.get(str(i["id"]), "")
            if not i["translated"]:
                i["skip"], i["skip_reason"] = True, "翻译通道未返回该条"

    print("④ 擦字 + 原位置重排（只动文字区域，产品像素不碰）")
    out_img = Image.fromarray(arr)
    plan = []
    for it in items:
        rect = it["rect"]
        if it["skip"]:
            plan.append({"text": it["text"], "expected": it["text"], "rect": rect, "action": "keep"})
            continue
        bg, std = _ring_color(arr, rect)
        ink = _text_color(arr, rect, bg)
        ink_ratio = float(np.mean(np.abs(arr[max(0, rect[1]):rect[3], max(0, rect[0]):rect[2]].astype(int)
                                        - np.array(bg)).sum(axis=2) > 120))
        erase_rect(out_img, rect, bg)
        info = render_text(out_img, rect, it["translated"], font_path, ink, bold=ink_ratio > 0.30)
        it["erase"] = {"bg": bg, "ring_std": round(std, 1), "text_color": ink,
                       "ink_ratio": round(ink_ratio, 2), "bg_flat": bool(std < 12)}
        it.update(info)
        plan.append({"text": it["text"], "expected": it["translated"], "rect": rect, "action": "translate"})

    suffix = f"_{a.from_}-{a.to}_local"
    out_path = outdir / (src.stem + suffix + ".png")
    out_img.save(out_path, "PNG")

    manifest = {"src": str(src), "out": str(out_path), "to": a.to, "from": a.from_,
                "mode": "local", "font": font_path, "matte_model": a.matte_model,
                "seconds": round(time.time() - t0, 1),
                "stats": {"blocks": len(items), "translated": sum(1 for i in items if not i["skip"] and i.get("translated")),
                          "kept_on_product": sum(1 for i in items if i["on_product"]),
                          "low_conf_kept": sum(1 for i in items if not i["skip"] and i["score"] < a.min_score),
                          "texture_bg_warn": sum(1 for i in items if i.get("erase") and not i["erase"]["bg_flat"])},
                "items": items}
    if not a.no_verify:
        print("⑤ 自证：产出再 OCR 逐条比对（主体内文字必须==原文，主体外==译文）")
        v = verify(out_path, plan)
        manifest["verify"] = v
        print(f"   {'✅' if v['all_pass'] else '❌'} {v['passed']}/{v['checked']} 条一致")
        for r in v["rows"]:
            if not r["pass"]:
                print(f"      ✗ [{r['action']}] 期望「{r['expected']}」实得「{r['seen']}」(sim={r['similarity']}, iou={r['iou']})")
    (outdir / (src.stem + suffix + ".manifest.json")).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2))
    print(json.dumps({"out": str(out_path), "stats": manifest["stats"],
                      "verify": (manifest.get("verify") or {}).get("all_pass"),
                      "seconds": manifest["seconds"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

