#!/usr/bin/env python3
"""本地抠图（onnxruntime 直接跑模型，不装 rembg 全家桶）

用法
  matte.py <in> <out.png> [--model u2net|isnet-general-use] [--model-dir DIR]
           [--bg none|white|#rrggbb] [--verify]

设计要点
  - 只依赖 onnxruntime + numpy + Pillow（模型 168~170MB 一次性下载，之后全离线）
  - **产品像素零改动**：模型只产出 alpha 掩膜，原图 RGB 原样保留（--verify 会实测差值）
  - 掩膜尺寸：u2net 320×320 / isnet-general-use 1024×1024（CPU 上后者慢得多）
"""
from __future__ import annotations

import argparse
import pathlib
import resource
import sys
import time

import numpy as np
import onnxruntime as ort
from PIL import Image

DEFAULT_MODEL_DIR = pathlib.Path.home() / ".hermes" / "venvs" / "models"
MODEL_CFG = {
    "u2net": {"size": 320, "mean": (0.485, 0.456, 0.406), "std": (0.229, 0.224, 0.225)},
    "isnet-general-use": {"size": 1024, "mean": (0.5, 0.5, 0.5), "std": (1.0, 1.0, 1.0)},
}


def _peak_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024)  # macOS: bytes


_SESSIONS: dict = {}


def _session(model: str, model_dir: pathlib.Path):
    """会话缓存：批量跑图时模型只加载一次（加载 ~3s，比推理还贵）。"""
    key = f"{model_dir}/{model}"
    if key not in _SESSIONS:
        mp = pathlib.Path(model_dir) / f"{model}.onnx"
        if not mp.exists():
            raise SystemExit(f"模型不存在：{mp}\n  下载：curl -L -o {mp} "
                             f"https://github.com/danielgatis/rembg/releases/download/v0.0.0/{model}.onnx")
        so = ort.SessionOptions()
        so.intra_op_num_threads = 0  # 交给 onnxruntime 自动（普通电脑按核心数）
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        _SESSIONS[key] = ort.InferenceSession(str(mp), so, providers=["CPUExecutionProvider"])
    return _SESSIONS[key]


def compute_alpha(inp: pathlib.Path, model: str = "u2net",
                  model_dir: pathlib.Path = DEFAULT_MODEL_DIR) -> tuple[Image.Image, Image.Image]:
    """返回 (原图RGB, alpha掩膜L)。给 translate_local / composite 复用。"""
    cfg = MODEL_CFG[model]
    session = _session(model, pathlib.Path(model_dir))
    img = Image.open(inp)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        flat = Image.new("RGBA", img.size, (255, 255, 255, 255))
        flat.alpha_composite(img)
        rgb_src = flat.convert("RGB")
    else:
        rgb_src = img.convert("RGB")
    W, H = rgb_src.size
    s = cfg["size"]
    x = np.asarray(rgb_src.resize((s, s), Image.BILINEAR), dtype=np.float32) / 255.0
    x = (x - np.array(cfg["mean"], dtype=np.float32)) / np.array(cfg["std"], dtype=np.float32)
    x = np.transpose(x, (2, 0, 1))[None]
    pred = session.run(None, {session.get_inputs()[0].name: x})[0]
    m = pred[0, 0] if pred.ndim == 4 else pred[0]
    m = m - np.min(m)
    if np.max(m) > 0:
        m = m / np.max(m)
    mask = Image.fromarray((m * 255).astype(np.uint8)).resize((W, H), Image.BILINEAR)
    return rgb_src, mask


def run(inp: pathlib.Path, out: pathlib.Path, model: str = "u2net",
        model_dir: pathlib.Path = DEFAULT_MODEL_DIR, bg: str = "none", verify: bool = False) -> dict:
    cfg = MODEL_CFG[model]
    t0 = time.time()
    session = _session(model, pathlib.Path(model_dir))

    img = Image.open(inp)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        flat = Image.new("RGBA", img.size, (255, 255, 255, 255))
        flat.alpha_composite(img)
        rgb_src = flat.convert("RGB")
    else:
        img = img.convert("RGB")
        rgb_src = img.copy()
    W, H = rgb_src.size

    # 预处理
    s = cfg["size"]
    x = np.asarray(rgb_src.resize((s, s), Image.BILINEAR), dtype=np.float32) / 255.0
    x = (x - np.array(cfg["mean"], dtype=np.float32)) / np.array(cfg["std"], dtype=np.float32)
    x = np.transpose(x, (2, 0, 1))[None]  # 1,3,H,W

    t_infer = time.time()
    out_name = session.get_inputs()[0].name
    pred = session.run(None, {out_name: x})[0]
    infer_s = time.time() - t_infer

    # 掩膜后处理（rembg 同款做法）
    m = pred[0, 0] if pred.ndim == 4 else pred[0]
    m = m - np.min(m)
    if np.max(m) > 0:
        m = m / np.max(m)
    mask = Image.fromarray((m * 255).astype(np.uint8)).resize((W, H), Image.BILINEAR)

    rgba = rgb_src.convert("RGBA")
    rgba.putalpha(mask)
    if bg == "none":
        rgba.save(out, "PNG")
    else:
        bgrgb = (255, 255, 255) if bg == "white" else tuple(int(bg.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        canvas = Image.new("RGBA", (W, H), (*bgrgb, 255))
        canvas.alpha_composite(rgba)
        canvas.convert("RGB").save(out, "PNG")

    info = {"file": str(out), "model": model, "infer_s": round(infer_s, 2),
            "total_s": round(time.time() - t0, 2), "peak_rss_mb": round(_peak_mb()), "size": [W, H]}

    if verify:  # 产品像素零改动验证：掩膜覆盖区（腐蚀 2px）的 RGB 必须与原图逐像素相同（只动 alpha 通道）
        from PIL import ImageFilter
        a = np.asarray(mask)
        inner = np.asarray(Image.fromarray(((a > 200) * 255).astype(np.uint8)).filter(ImageFilter.MinFilter(5))) > 0
        src_rgb = np.asarray(rgb_src)
        out_rgb = np.asarray(rgba)[:, :, :3]
        if not inner.any():
            info["verify"] = "掩膜为空，跳过"
        else:
            diff = np.abs(src_rgb[inner].astype(np.int16) - out_rgb[inner].astype(np.int16))
            info["verify"] = {"masked_pixels_checked": int(inner.sum()),
                              "max_abs_diff": int(diff.max()), "mean_abs_diff": round(float(diff.mean()), 4),
                              "product_pixels_unchanged": bool(diff.max() == 0), "note": "只动 alpha；交付白底图的边缘羽化区会与白底混合（正常）"}
    return info


def main(argv: list[str]) -> int:
    import json
    p = argparse.ArgumentParser(prog="matte", description="本地抠图（onnxruntime CPU，可批量；会话只加载一次）")
    p.add_argument("src", nargs="+", help="一张或多张原图")
    p.add_argument("--out", help="单张输出路径（不给则 <stem>.matte.png）")
    p.add_argument("--out-dir", help="多张输出目录（文件名同原图 stem + .png）")
    p.add_argument("--model", choices=list(MODEL_CFG), default="u2net")
    p.add_argument("--model-dir", default=str(DEFAULT_MODEL_DIR))
    p.add_argument("--bg", default="none", help="none|white|#rrggbb")
    p.add_argument("--verify", action="store_true")
    a = p.parse_args(argv)
    if len(a.src) == 1:
        out = pathlib.Path(a.out or (pathlib.Path(a.src[0]).with_suffix(".matte.png")))
        print(json.dumps(run(pathlib.Path(a.src[0]), out, a.model, pathlib.Path(a.model_dir), a.bg, a.verify),
                         ensure_ascii=False))
        return 0
    if not a.out_dir:
        raise SystemExit("多张输入时必须给 --out-dir")
    od = pathlib.Path(a.out_dir); od.mkdir(parents=True, exist_ok=True)
    # 批量：会话加载一次（首张含加载耗时，后续为纯推理）
    t0 = time.time()
    rows = []
    for s in a.src:
        rows.append(run(pathlib.Path(s), od / (pathlib.Path(s).stem + ".png"), a.model,
                        pathlib.Path(a.model_dir), a.bg, a.verify))
    print(json.dumps({"batch": len(rows), "total_s": round(time.time() - t0, 2),
                      "per_image_s": [r["infer_s"] for r in rows],
                      "peak_rss_mb": round(_peak_mb()), "results": rows}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
