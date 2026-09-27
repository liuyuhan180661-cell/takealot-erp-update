#!/usr/bin/env python3
"""ecom-product-images 引擎（纯 stdlib，Mac/Windows 同一份）

子命令
  doctor                自检：key / venv / 字体 / 通道连通性，输出可贴回的表格
  copy                  看图写文案（DeepSeek vision）→ JSON
  gen                   文生图 / 图生图（单张）
  white                 白底图（engine=model 重绘 | aliyun 商品分割保真 | local rembg）
  translate             图片翻译（mode=precise 保真档 | hifi 重绘档）
  set                   套图：文案 + 逐图位生成 + 本地排版 + 平台像素 + manifest
  check                 自检：视觉模型对比原图与产出（保真度/文字/可上架）

通道
  画面生成/重绘  Agnes  images/generations     env AGNES_NEW_KEY
  文案/看图/自检 DeepSeek chat/completions      env DEEPSEEK_API_KEY
  白底图保真     阿里云 imageseg SegmentCommodity env ALIYUN_ACCESS_KEY_ID/SECRET
  图片翻译保真   阿里云 alimt TranslateImage    同上
  本地排版        Pillow（~/.hermes/venvs/imgtools）
"""
from __future__ import annotations

import base64, hashlib, hmac, json, mimetypes, os, pathlib, re, subprocess, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone

HOME = pathlib.Path.home()
SKILL_DIR = pathlib.Path(__file__).resolve().parent.parent
SPECS = json.loads((SKILL_DIR / "scripts" / "specs.json").read_text(encoding="utf-8"))
VENV_PY = HOME / ".hermes" / "venvs" / "imgtools" / "bin" / "python"
DS_BASE = "https://api.deepseek.com/v1"
AGNES_BASE = "https://apihub.agnes-ai.com/v1"
IMG_MODELS = {"high": "agnes-image-2.1-flash", "fast": "agnes-image-2.5-flash"}
DS_VISION_MODEL = "deepseek-flash"


# ────────────────────────── 基础设施 ──────────────────────────

def load_env() -> dict:
    """进程环境优先，其次 ~/.hermes/.env（不覆盖已有值）。"""
    env = dict(os.environ)
    f = HOME / ".hermes" / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return env


ENV = load_env()


class Ctx:
    def __init__(self, out_dir: pathlib.Path | None = None, product: str = "product"):
        self.product = product
        stamp = datetime.now().strftime("%Y-%m-%d")
        self.dir = pathlib.Path(out_dir) if out_dir else (HOME / "Desktop" / "作图输出" / f"{stamp}-{product}")
        self.dir.mkdir(parents=True, exist_ok=True)
        self.manifest: list[dict] = []

    def add(self, **kw):
        self.manifest.append(kw)

    def save(self):
        p = self.dir / "manifest.json"
        data = {"product": self.product, "at": datetime.now().isoformat(timespec="seconds"), "shots": self.manifest}
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return p


def http_json(url: str, body: dict | bytes | None, headers: dict, timeout: int = 240, tries: int = 4) -> dict:
    payload = body if isinstance(body, (bytes, type(None))) else json.dumps(body, ensure_ascii=False).encode()
    last = ""
    for t in range(tries):
        try:
            req = urllib.request.Request(url, data=payload, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            txt = e.read().decode(errors="replace")[:300]
            # 4xx 里除了限流都不值得重试
            if e.code < 500 and e.code not in (429, 408):
                raise RuntimeError(f"HTTP {e.code}: {txt}")
            last = f"HTTP {e.code}: {txt}"
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
        time.sleep(3 + 3 * t)
    raise RuntimeError(f"请求失败（已重试 {tries} 次）{url} → {last}")


def data_url(path: pathlib.Path) -> str:
    mime = mimetypes.guess_type(str(path))[0] or "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(pathlib.Path(path).read_bytes()).decode()


def download(url: str, dest: pathlib.Path, tries: int = 3) -> pathlib.Path:
    for t in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
                f.write(r.read())
            return dest
        except Exception as e:  # noqa: BLE001
            if t == tries - 1:
                raise RuntimeError(f"下载失败 {url} → {e}")
            time.sleep(3)
    return dest


# ────────────────────────── 通道：Agnes 生图 ──────────────────────────

def agnes_generate(prompt: str, refs: list[pathlib.Path], ratio: str = "1:1", quality: str = "high") -> str:
    key = ENV.get("AGNES_NEW_KEY") or ENV.get("AGNES_API_KEY")
    if not key:
        raise RuntimeError("AGNES_NEW_KEY 未配置（~/.hermes/.env）")
    size = SPECS["ratios_px"].get(ratio, "1024x1024")
    body: dict = {"model": IMG_MODELS.get(quality, IMG_MODELS["high"]), "prompt": prompt, "size": size}
    if refs:
        urls = [data_url(p) for p in refs]
        body["image"] = urls[0] if len(urls) == 1 else urls
    d = http_json(f"{AGNES_BASE}/images/generations", body,
                  {"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    if "data" not in d or not d["data"]:
        raise RuntimeError(f"Agnes 未返回图片：{json.dumps(d, ensure_ascii=False)[:200]}")
    return d["data"][0]["url"]


# ────────────────────────── 通道：DeepSeek 视觉 ──────────────────────────

def ds_vision(prompt: str, images: list[pathlib.Path], max_tokens: int = 4000) -> str:
    key = ENV.get("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY 未配置")
    content = [{"type": "text", "text": prompt}]
    for p in images:
        content.append({"type": "image_url", "image_url": {"url": data_url(p)}})
    # deepseek-flash 偶发返回空 content（reasoning 吃满 token）→ 提高上限并重试
    for attempt, budget in enumerate((max_tokens, 6000, 8000)):
        d = http_json(f"{DS_BASE}/chat/completions",
                      {"model": DS_VISION_MODEL, "messages": [{"role": "user", "content": content}],
                       "max_tokens": budget},
                      {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, timeout=200)
        txt = (d["choices"][0]["message"].get("content") or "").strip()
        if txt:
            return txt
        time.sleep(2 + attempt)
    return ""


def parse_json_block(text: str) -> dict:
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        raise RuntimeError(f"模型未返回 JSON：{text[:200]}")
    return json.loads(m.group(0))


# ────────────────────────── 通道：阿里云 ACS3 签名 ──────────────────────────

def _aliyun_creds() -> tuple[str, str]:
    ak = ENV.get("ALIYUN_ACCESS_KEY_ID") or ENV.get("ALIBABA_CLOUD_ACCESS_KEY_ID")
    sk = ENV.get("ALIYUN_ACCESS_KEY_SECRET") or ENV.get("ALIBABA_CLOUD_ACCESS_KEY_SECRET")
    if not ak or not sk:
        raise RuntimeError("阿里云凭证未配置：需要 ALIYUN_ACCESS_KEY_ID / ALIYUN_ACCESS_KEY_SECRET"
                           "（与百炼 DASHSCOPE_API_KEY 是同一账号下的两把不同凭证）")
    return ak, sk


def aliyun_rpc(host: str, action: str, version: str, params: dict, method: str = "POST") -> dict:
    """阿里云 RPC 风格接口，ACS3-HMAC-SHA256 签名（无 SDK 依赖）。"""
    ak, sk = _aliyun_creds()
    body = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}).encode()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    nonce = hashlib.md5(f"{now}{action}{time.time()}".encode()).hexdigest()
    headers = {
        "host": host,
        "x-acs-action": action,
        "x-acs-version": version,
        "x-acs-date": now,
        "x-acs-signature-nonce": nonce,
        "x-acs-content-sha256": hashlib.sha256(body).hexdigest(),
        "content-type": "application/x-www-form-urlencoded",
    }
    signed = ";".join(sorted(headers))
    canonical_headers = "".join(f"{k}:{headers[k]}\n" for k in sorted(headers))
    canonical_request = "\n".join([method, "/", "", canonical_headers, signed, headers["x-acs-content-sha256"]])
    string_to_sign = "ACS3-HMAC-SHA256\n" + hashlib.sha256(canonical_request.encode()).hexdigest()
    sig = hmac.new(sk.encode(), string_to_sign.encode(), hashlib.sha256).hexdigest()
    headers["Authorization"] = (f"ACS3-HMAC-SHA256 Credential={ak},SignedHeaders={signed},Signature={sig}")
    out = http_json(f"https://{host}/", body, headers, timeout=180, tries=3)
    if out.get("Code") and str(out.get("Code")) not in ("200", "0") and not out.get("Data"):
        raise RuntimeError(f"阿里云 {action} 失败：{out.get('Code')} {out.get('Message')}")
    return out


def alimt_translate_image(path: pathlib.Path, src: str, dst: str, field: str = "e-commerce",
                          ext: dict | None = None) -> str:
    """图片翻译保真档：擦字+原版式重排，返回译图 URL。

    ext.ignoreEntityRecognize 官方语义：false/不传 = 执行主体识别，印在商品主体上的文字被**跳过**；
    true = 不做该判断，全部文字都翻。默认必须保持 false —— 包装/产品本体上的字不能动。
    """
    b64 = base64.b64encode(pathlib.Path(path).read_bytes()).decode()
    params: dict = {"SourceLanguage": src, "TargetLanguage": dst, "ImageBase64": b64, "Field": field}
    if ext:
        params["Ext"] = json.dumps(ext, ensure_ascii=False)
    out = aliyun_rpc("mt.cn-hangzhou.aliyuncs.com", "TranslateImage", "2018-10-12", params)
    data = out.get("Data") or {}
    url = data.get("FinalImageUrl") or data.get("ImageUrl")
    if not url:
        raise RuntimeError(f"TranslateImage 未返回译图：{json.dumps(out, ensure_ascii=False)[:300]}")
    return url


def imageseg_commodity(image_url: str, return_form: str = "whiteBK") -> str:
    """商品分割：whiteBK=白底图 / crop=去边四通道PNG / mask=单通道。注意：只接受公网 URL。"""
    out = aliyun_rpc("imageseg.cn-shanghai.aliyuncs.com", "SegmentCommodity", "2019-12-30",
                     {"ImageURL": image_url, "ReturnForm": return_form})
    url = ((out.get("Data") or {}).get("ImageURL")) or ""
    if not url:
        raise RuntimeError(f"SegmentCommodity 未返回图像：{json.dumps(out, ensure_ascii=False)[:300]}")
    return url


# ────────────────────────── 本地排版（Pillow 子进程） ──────────────────────────

def compose(*args: str) -> None:
    if not VENV_PY.exists():
        raise RuntimeError(f"Pillow venv 不存在：{VENV_PY}\n  修复：uv venv ~/.hermes/venvs/imgtools && "
                           f"uv pip install --python {VENV_PY} pillow")
    r = subprocess.run([str(VENV_PY), str(SKILL_DIR / "scripts" / "compose.py"), *args],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"compose 失败：{r.stderr.strip()[:300]}")


# ────────────────────────── 子命令 ──────────────────────────

def cmd_doctor(_args) -> int:
    rows = []
    rows.append(("Agnes 生图 key", "OK" if ENV.get("AGNES_NEW_KEY") or ENV.get("AGNES_API_KEY") else "缺失 AGNES_NEW_KEY"))
    rows.append(("DeepSeek 文案/自检 key", "OK" if ENV.get("DEEPSEEK_API_KEY") else "缺失 DEEPSEEK_API_KEY"))
    ak = ENV.get("ALIYUN_ACCESS_KEY_ID") or ENV.get("ALIBABA_CLOUD_ACCESS_KEY_ID")
    rows.append(("阿里云凭证（抠图/图片翻译）", "OK" if ak else "缺失 ALIYUN_ACCESS_KEY_ID/SECRET（需先开通 机器翻译 + 视觉智能-分割抠图）"))
    rows.append(("百炼 Key（千问图像翻译·主路线）",
                 "OK" if ENV.get("DASHSCOPE_API_KEY") else
                 "缺失 DASHSCOPE_API_KEY（百炼控制台创建，0.004元/张，主体文字不翻）"))
    rows.append(("Pillow 排版 venv", "OK" if VENV_PY.exists() else f"缺失：{VENV_PY}"))
    # 本地抠图（免费离线路线）：onnxruntime + 模型文件
    mdir = HOME / ".hermes" / "venvs" / "models"
    found = [m for m in ("u2net", "isnet-general-use") if (mdir / f"{m}.onnx").exists()]
    has_ort = VENV_PY.exists() and subprocess.run(
        [str(VENV_PY), "-c", "import onnxruntime, numpy"], capture_output=True).returncode == 0
    if found and has_ort:
        rows.append(("本地抠图（免费离线）", "OK 模型=" + ",".join(found)))
    else:
        rows.append(("本地抠图（免费离线）",
                     "缺 " + ("onnxruntime/numpy（uv pip install --python %s pillow numpy onnxruntime）" % VENV_PY
                              if not has_ort else "模型文件")
                     + "；下载：curl -L -o %s/u2net.onnx https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx" % mdir))
    if VENV_PY.exists():
        r = subprocess.run([str(VENV_PY), str(SKILL_DIR / "scripts" / "compose.py"), "font"],
                           capture_output=True, text=True)
        rows.append(("排版字体", f"OK {r.stdout.strip()[:110]}" if r.returncode == 0 else f"异常 {r.stderr.strip()[:110]}"))
    else:
        rows.append(("排版字体", "跳过（venv 缺失）"))
    # 连通性
    try:
        agnes_generate("a plain white studio packshot of a black USB-C wall charger, e-commerce product photo", [], "1:1", "fast")
        rows.append(("Agnes 连通性", "OK"))
    except Exception as e:  # noqa: BLE001
        rows.append(("Agnes 连通性", f"失败 {str(e)[:120]}"))
    try:
        r = ds_vision("只回复 OK 两个字", [])
        rows.append(("DeepSeek 连通性", "OK" if r else "空响应"))
    except Exception as e:  # noqa: BLE001
        rows.append(("DeepSeek 连通性", f"失败 {str(e)[:120]}"))
    w = max(len(k) for k, _ in rows)
    print("| 项目".ljust(w + 2) + "| 状态 |")
    print("|" + "-" * (w + 1) + "|---|")
    for k, v in rows:
        print(f"| {k.ljust(w)} | {v} |")
    return 0


COPY_PROMPT = ('请看产品图，写营销内容，语言必须是【{lang}】。{info}\n'
               '要求输出 JSON：{{"copies":[{{"headline":"2~4词醒目卖点标题","subtitle":"<=8词补充卖点"}}],'
               '"specs":["规格1","规格2"]}}\ncopies 共 {count} 组，突出不同卖点角度。specs 4~6 条简短规格参数。只输出 JSON。')


def do_copy(refs: list[pathlib.Path], lang: str, count: int, info: str = "") -> dict:
    txt = ds_vision(COPY_PROMPT.format(lang=lang, count=count, info=f"卖家补充信息：{info}。" if info else ""), refs, 2500)
    data = parse_json_block(txt)
    copies = [{"headline": str(c.get("headline", ""))[:40], "subtitle": str(c.get("subtitle", ""))[:80]}
              for c in (data.get("copies") or [])][:count]
    specs = [str(s)[:40] for s in (data.get("specs") or [])][:6]
    if not copies:
        raise RuntimeError("文案为空")
    return {"copies": copies, "specs": specs}


def build_prompt(shot: dict, bg: str, copy: dict | None, lang: str, scene: str = "", specs_text: str = "") -> str:
    p = (f"Take the exact product shown in the reference image(s) and render it "
         f"{shot['prompt'].replace('{BG}', bg)}. Keep the product's shape, color, logo, proportions and details "
         f"strictly identical to the reference. Photorealistic, high resolution, clean composition.")
    if shot.get("spec"):
        p += " Leave clean empty space for specification callouts and thin divider lines. No gibberish text, no watermark, no extra logos."
    elif shot.get("text"):
        if scene:
            p += f" Seller's desired scene direction (follow faithfully): {scene}."
        p += (" Do NOT print any text, letters or numbers anywhere in the image; leave clean empty areas for typography later."
              " No watermark, no extra logos.")
    else:
        p += " Absolutely no text, no captions, no watermark, no extra logos."
    return p


COMPOSITE_POSE = {  # 图位 → (产品占短边比例, 水平位置, 垂直位置, 阴影)
    "main": (0.85, 0.5, 0.5, "none"), "show": (0.72, 0.5, 0.58, "soft"),
    "scene": (0.50, 0.5, 0.64, "soft"), "inuse": (0.50, 0.5, 0.64, "soft"),
    "detail": (0.95, 0.5, 0.5, "none"),
    "d-hero": (0.42, 0.5, 0.66, "soft"), "d-sell1": (0.45, 0.45, 0.62, "soft"),
    "d-sell2": (0.45, 0.55, 0.62, "soft"), "d-life": (0.42, 0.5, 0.64, "soft"),
    "d-spec": (0.50, 0.32, 0.55, "soft"),
}


def make_product_rgba(ref: pathlib.Path, dest: pathlib.Path, matte_model: str) -> pathlib.Path:
    """本地抠图（onnxruntime，产品像素零改动），产出透明 PNG 供合成。"""
    r = subprocess.run([str(VENV_PY), str(SKILL_DIR / "scripts" / "matte.py"), str(ref),
                        "--out", str(dest), "--model", matte_model, "--bg", "none", "--verify"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"本地抠图失败：{(r.stderr or r.stdout).strip()[:240]}")
    print("      抠图: " + r.stdout.strip()[:220])
    return dest


def do_shot_composite(shot: dict, idx: int, total: int, ctx: Ctx, spec: dict, ratio: str,
                      out_px: tuple[int, int], copy: dict | None, quality: str,
                      product_rgba: pathlib.Path, scale_override: float = 0.0) -> dict:
    """合成路线：生成/构造背景 → 把抠好的产品贴上去 → 本地叠字。产品像素零改动，包装文字不可能被改。"""
    name = f"{idx:02d}_{shot['key']}"
    scale, cx, cy, shadow = COMPOSITE_POSE.get(shot["key"], (0.55, 0.5, 0.62, "soft"))
    if scale_override:
        scale = scale_override
    print(f"  [{idx}/{total}] {shot['label']} 背景中…", flush=True)
    if shot["key"] == "main" and spec["bg"] == "white":
        bg = ctx.dir / f"{name}_bg.png"
        compose("blank", str(bg), str(out_px[0]), str(out_px[1]), "--bg", spec["bg"])  # 主图直接白底，省一次生图
    else:
        p = (f"Render a background plate only: {shot.get('bg_prompt') or shot['prompt']}. "
             "Photorealistic, high resolution, professional e-commerce photography background. "
             "IMPORTANT: the image must contain NO product and NO object of any kind — only the background / environment.")
        url = agnes_generate(p, [], ratio, quality)
        bg = download(url, ctx.dir / f"{name}_bg.png")
    final = ctx.dir / f"{name}_{out_px[0]}x{out_px[1]}.png"
    compose("composite", str(bg), str(product_rgba), str(final), "--w", str(out_px[0]), "--h", str(out_px[1]),
            "--scale", str(scale), "--cx", str(cx), "--cy", str(cy), "--shadow", shadow)
    text_planned = ""
    if shot.get("text") and copy:
        c = copy["copies"][(idx - 1) % len(copy["copies"])]
        compose("overlay", str(final), str(final), "--headline", c["headline"], "--subtitle", c["subtitle"],
                "--w", str(out_px[0]), "--h", str(out_px[1]))
        text_planned = f'{c["headline"]} | {c["subtitle"]}'
    elif shot.get("spec") and copy:
        st = " · ".join(copy.get("specs") or [])
        if st:
            compose("overlay", str(final), str(final), "--specs", st, "--w", str(out_px[0]), "--h", str(out_px[1]))
            text_planned = st
    rec = {"idx": idx, "shot": shot["key"], "label": shot["label"], "file": str(final), "mode": "composite",
           "product_rgba": str(product_rgba), "pose": {"scale": scale, "cx": cx, "cy": cy, "shadow": shadow},
           "out_px": list(out_px), "text_planned": text_planned, "bg": str(bg)}
    ctx.add(**rec)
    print(f"      → {final.name}")
    return rec


def do_shot(shot: dict, idx: int, total: int, refs: list[pathlib.Path], ctx: Ctx, spec: dict, ratio: str,
            out_px: tuple[int, int], copy: dict | None, lang: str, scene: str, specs_text: str, quality: str) -> dict:
    name = f"{idx:02d}_{shot['key']}"
    prompt = build_prompt(shot, spec["bg"], copy, lang, scene, specs_text)
    print(f"  [{idx}/{total}] {shot['label']} 生成中…", flush=True)
    url = agnes_generate(prompt, refs, ratio, quality)
    raw = download(url, ctx.dir / f"{name}_raw.png")
    final = ctx.dir / f"{name}_{out_px[0]}x{out_px[1]}.png"
    compose("fit", str(raw), str(final), str(out_px[0]), str(out_px[1]), "--bg", "white")
    text_planned = ""
    if shot.get("text") and copy:
        c = copy["copies"][(idx - 1) % len(copy["copies"])]
        compose("overlay", str(final), str(final), "--headline", c["headline"], "--subtitle", c["subtitle"],
                "--w", str(out_px[0]), "--h", str(out_px[1]))
        text_planned = f'{c["headline"]} | {c["subtitle"]}'
    elif shot.get("spec") and specs_text:
        compose("overlay", str(final), str(final), "--specs", specs_text,
                "--w", str(out_px[0]), "--h", str(out_px[1]))
        text_planned = specs_text
    rec = {"idx": idx, "shot": shot["key"], "label": shot["label"], "file": str(final), "prompt": prompt,
           "model": IMG_MODELS.get(quality), "ratio": ratio, "out_px": list(out_px),
           "text_planned": text_planned, "source_url": url}
    ctx.add(**rec)
    print(f"      → {final.name}")
    return rec


def cmd_gen(args) -> int:
    refs = [pathlib.Path(p) for p in (args.ref or [])]
    for r in refs:
        if not r.exists():
            raise SystemExit(f"参考图不存在：{r}")
    ctx = Ctx(args.out, args.product or "gen")
    url = agnes_generate(args.prompt, refs, args.ratio, args.quality)
    dest = ctx.dir / f"{args.name or 'gen'}_{args.ratio.replace(':', 'x')}.png"
    download(url, dest)
    if args.platform:
        spec = SPECS["platforms"][args.platform]
        w, h = (spec["gallery_out"] if not args.detail else spec["detail_out"])
        out = dest.with_name(f"{dest.stem}_{w}x{h}.png")
        compose("fit", str(dest), str(out), str(w), str(h), "--bg", "white")
        dest = out
    ctx.add(shot="gen", label="文生图" if not refs else "图生图", file=str(dest), prompt=args.prompt,
            model=IMG_MODELS.get(args.quality), ratio=args.ratio)
    print(json.dumps({"file": str(dest), "source_url": url}, ensure_ascii=False))
    ctx.save()
    return 0


def cmd_set(args) -> int:
    spec = SPECS["platforms"][args.platform]
    refs = [pathlib.Path(p) for p in args.images]
    for r in refs:
        if not r.exists():
            raise SystemExit(f"产品图不存在：{r}")
    g_n = args.gallery if args.gallery is not None else spec["gallery_count"]
    d_n = args.detail if args.detail is not None else spec["detail_count"]
    if g_n + d_n == 0:
        raise SystemExit("张数为 0：至少给 --gallery 或 --detail 一个正数")
    lang = args.lang or spec["copy_lang"]
    ctx = Ctx(args.out, args.product or refs[0].stem[:20])

    shots: list[dict] = []
    gshots = SPECS["shots"]["gallery"]
    dshots = SPECS["shots"]["detail"]
    for i in range(g_n):
        shots.append(("gallery", gshots[i % len(gshots)]))
    for i in range(d_n):
        shots.append(("detail", dshots[i % len(dshots)]))

    need_copy = any(s.get("text") or s.get("spec") for _, s in shots)
    copy = None
    if need_copy:
        n_text = sum(1 for _, s in shots if s.get("text"))
        print(f"① 文案（{lang}，{max(n_text, 1)} 组）…", flush=True)
        copy = do_copy(refs, lang, max(n_text, 1), args.info or "")
        print("   " + json.dumps(copy, ensure_ascii=False))
    specs_text = " · ".join(copy["specs"]) if copy and copy.get("specs") else ""

    print(f"② 出图：{len(shots)} 张（{spec['name']}）" + ("｜合成路线" if args.composite else "｜图生图路线"))
    product_rgba = None
    if args.composite:
        product_rgba = pathlib.Path(args.product_rgba) if args.product_rgba else ctx.dir / "product_rgba.png"
        if not args.product_rgba:
            print("②a 本地抠图（产品像素零改动）…")
            make_product_rgba(refs[0], product_rgba, args.matte_model)
    for i, (kind, shot) in enumerate(shots, start=1):
        ratio = spec["gallery_gen"] if kind == "gallery" else spec["detail_gen"]
        px = tuple(spec["gallery_out"] if kind == "gallery" else spec["detail_out"])
        if args.custom_w and args.custom_h:
            px = (args.custom_w, args.custom_h)
        try:
            if args.composite:
                do_shot_composite(shot, i, len(shots), ctx, spec, ratio, px, copy, args.quality,
                                  product_rgba, args.product_scale)
            else:
                do_shot(shot, i, len(shots), refs, ctx, spec, ratio, px, copy, lang, args.scene or "",
                        specs_text, args.quality)
        except Exception as e:  # noqa: BLE001
            print(f"      ✗ 失败：{str(e)[:160]}", file=sys.stderr)
            ctx.add(idx=i, shot=shot["key"], label=shot["label"], error=str(e)[:300])

    man = ctx.save()
    ok = sum(1 for s in ctx.manifest if s.get("file"))
    print(json.dumps({"dir": str(ctx.dir), "manifest": str(man), "ok": ok, "total": len(shots)}, ensure_ascii=False))
    if args.check:
        cmd_check(type("A", (), {"dir": str(ctx.dir), "ref": str(refs[0]), "image": None, "set_": False})())
    return 0 if ok == len(shots) else 1


def cmd_white(args) -> int:
    src = pathlib.Path(args.image)
    if not src.exists():
        raise SystemExit(f"图片不存在：{src}")
    ctx = Ctx(args.out, args.product or f"{src.stem}-white")
    spec = SPECS["platforms"][args.platform]
    w, h = (spec["gallery_out"] if not args.detail else spec["detail_out"])
    dest = ctx.dir / f"white_{w}x{h}.png"
    if args.engine == "aliyun":
        url = args.image_url or ""
        if not url:
            raise SystemExit("aliyun engine 需要 --image-url（SegmentCommodity 只接受公网 URL，≤3MB、<2000px）："
                             "先把图放到公网可访问地址，或用 engine=model")
        out = imageseg_commodity(url, args.return_form)
        raw = download(out, ctx.dir / "white_raw.png")
    elif args.engine == "model":
        url = agnes_generate(build_prompt(SPECS["shots"]["gallery"][0], spec["bg"], None, "", "", ""), [src],
                             spec["gallery_gen"], args.quality)
        raw = download(url, ctx.dir / "white_raw.png")
    else:  # local：本地抠图（onnxruntime 直接跑模型，不需要 rembg 全家桶）
        matte = SKILL_DIR / "scripts" / "matte.py"
        if not VENV_PY.exists():
            raise SystemExit(f"local engine 需要 venv：uv venv {VENV_PY.parent.parent} && "
                             f"uv pip install --python {VENV_PY} pillow numpy onnxruntime")
        raw = ctx.dir / "white_raw.png"
        r = subprocess.run([str(VENV_PY), str(matte), str(src), "--out", str(raw),
                            "--model", args.matte_model, "--bg", "white", "--verify"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit(f"本地抠图失败：{(r.stderr or r.stdout).strip()[:300]}")
        print("      抠图: " + (r.stdout.strip()[:200]))
    compose("fit", str(raw), str(dest), str(w), str(h), "--bg", "white")
    ctx.add(shot="white", label="白底主图", file=str(dest), engine=args.engine, out_px=[w, h])
    ctx.save()
    print(json.dumps({"file": str(dest), "engine": args.engine}, ensure_ascii=False))
    return 0


HIFI_PROMPT = ("Translate ONLY the marketing / descriptive copy overlaid in this image into {lang} "
               "(headlines, subtitles, banners, callouts, bullet points). "
               "Do NOT translate, alter or redraw any text printed on the product itself or on its packaging: "
               "keep the product, its labels, brand names and printed packaging text exactly as they are, "
               "faithful to the original. Keep the same layout, background, icons and colors. "
               "Render the translated marketing copy cleanly in a matching font style, spelled correctly.")


def has_aliyun_creds() -> bool:
    ak = ENV.get("ALIYUN_ACCESS_KEY_ID") or ENV.get("ALIBABA_CLOUD_ACCESS_KEY_ID")
    sk = ENV.get("ALIYUN_ACCESS_KEY_SECRET") or ENV.get("ALIBABA_CLOUD_ACCESS_KEY_SECRET")
    return bool(ak and sk)


DASHSCOPE_IMG_TRANS = "https://dashscope.aliyuncs.com/api/v1/services/aigc/image2image/image-synthesis"
DASHSCOPE_UPLOAD = "https://dashscope.aliyuncs.com/api/v1/uploads"


def _safe_name(name: str) -> str:
    """百炼要求 URL 不能含中文 → 文件名压成 ASCII。"""
    import re as _re
    keep = _re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    return (_re.sub(r"_+", "_", keep).strip("_.") or "image")[-90:]


def dashscope_upload(path: pathlib.Path, api_key: str, model: str = "qwen-mt-image-2.0") -> str:
    """本地图 → 百炼临时 oss:// URL（官方三步：getPolicy → OSS 直传 → oss://key，48h 有效）。"""
    import io
    import uuid
    req = urllib.request.Request(f"{DASHSCOPE_UPLOAD}?action=getPolicy&model={model}",
                                headers={"Authorization": f"Bearer {api_key}"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            data = json.loads(r.read().decode())["data"]
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"获取上传凭证失败 HTTP {e.code}: {e.read().decode()[:300]}")
    fname = _safe_name(path.name)
    key = f"{data['upload_dir']}/{fname}"
    bnd = "----hermes" + uuid.uuid4().hex
    fields = {"OSSAccessKeyId": data["oss_access_key_id"], "Signature": data["signature"],
              "policy": data["policy"], "x-oss-object-acl": data["x_oss_object_acl"],
              "x-oss-forbid-overwrite": data["x_oss_forbid_overwrite"],
              "key": key, "success_action_status": "200"}
    buf = io.BytesIO()
    for k, v in fields.items():
        buf.write(f'--{bnd}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    buf.write(f'--{bnd}\r\nContent-Disposition: form-data; name="file"; filename="{fname}"\r\n'
              f'Content-Type: application/octet-stream\r\n\r\n'.encode())
    buf.write(path.read_bytes())
    buf.write(f"\r\n--{bnd}--\r\n".encode())
    req2 = urllib.request.Request(data["upload_host"], data=buf.getvalue(),
                                  headers={"Content-Type": f"multipart/form-data; boundary={bnd}"})
    try:
        with urllib.request.urlopen(req2, timeout=300) as r2:
            r2.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"上传到 OSS 失败 HTTP {e.code}: {e.read().decode()[:300]}")
    return "oss://" + key


def bailian_translate_image(path: pathlib.Path, src: str, dst: str, api_key: str,
                            segment: bool = True, model: str = "qwen-mt-image-2.0",
                            terms: list[tuple[str, str]] | None = None,
                            domain_hint: str | None = None) -> str:
    """千问图像翻译（百炼）：保排版，**imageSegment=true 时主体/Logo上的字不翻**（我们的硬口径）。

    返回翻译后图像 URL（同步模式，仅 qwen-mt-image-2.0 支持）。
    """
    oss = dashscope_upload(path, api_key, model)
    body: dict = {"model": model,
                  "input": {"image_url": oss, "source_lang": src or "auto", "target_lang": dst},
                  "config": {"imageSegment": bool(segment)}}
    ext: dict = {}
    if terms:
        ext["terminologies"] = [{"src": s, "tgt": t} for s, t in terms]
    if domain_hint:
        ext["domainHint"] = domain_hint
    if ext:
        body["ext"] = ext
    req = urllib.request.Request(DASHSCOPE_IMG_TRANS, data=json.dumps(body).encode(),
                                headers={"Authorization": f"Bearer {api_key}",
                                         "Content-Type": "application/json",
                                         "X-DashScope-OssResourceResolve": "enable"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            res = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"千问图像翻译失败 HTTP {e.code}: {e.read().decode()[:400]}")
    if res.get("code"):
        raise RuntimeError(f"千问图像翻译失败 {res.get('code')}: {res.get('message')} "
                           f"(request_id={res.get('request_id')})")
    return res["output"]["image_url"]


def resolve_translate_mode(requested: str) -> tuple[str, str]:
    """确定性选档（不靠模型猜）：百炼 Key → 千问图像翻译（主）；阿里云 AK → alimt；都没有 → 本地。"""
    if requested != "auto":
        return requested, f"用户指定 {requested}"
    if ENV.get("DASHSCOPE_API_KEY"):
        return "bailian", "检测到 DASHSCOPE_API_KEY → 千问图像翻译 qwen-mt-image-2.0（主路线，0.004元/张，主体文字不翻）"
    if has_aliyun_creds():
        return "precise", "检测到阿里云 AccessKey → alimt 电商图片翻译（0.06元/张，保留原版式）"
    return "local", "未检测到 DASHSCOPE_API_KEY / 阿里云 AccessKey → 本地保真档（离线兜底）"


def cmd_translate(args) -> int:
    src = pathlib.Path(args.image)
    if not src.exists():
        raise SystemExit(f"图片不存在：{src}")
    args.mode, why = resolve_translate_mode(args.mode)
    print(f"[translation] 选档：{args.mode} —— {why}", file=sys.stderr)
    ctx = Ctx(args.out, args.product or f"{src.stem}-{args.to}")
    lang_en = {"en": "English", "ro": "Romanian", "ru": "Russian", "de": "German", "fr": "French", "es": "Spanish",
               "it": "Italian", "pl": "Polish"}.get(args.to, args.to)
    if args.mode == "bailian":
        # 千问图像翻译（百炼）：一把 DASHSCOPE_API_KEY，保排版，主体上的字默认不翻
        key = ENV.get("DASHSCOPE_API_KEY")
        if not key:
            print(json.dumps({"error": "缺 DASHSCOPE_API_KEY（百炼 API Key）",
                              "options": ["百炼控制台创建 API Key → 写入 ~/.hermes/.env 的 DASHSCOPE_API_KEY",
                                          "零凭证兜底：translate --mode local（离线）",
                                          "或配阿里云 AccessKey 走 --mode precise"],
                              "doc": "https://help.aliyun.com/zh/model-studio/get-api-key"}, ensure_ascii=False, indent=2))
            return 3
        terms = [tuple(t.split("=", 1)) for t in args.term if "=" in t]
        dest = ctx.dir / f"translated_{args.from_}-{args.to}_bailian.jpg"
        try:
            url = bailian_translate_image(src, args.from_, args.to, key,
                                          segment=not args.no_image_segment,
                                          model=args.dashscope_model, terms=terms,
                                          domain_hint=args.domain_hint)
        except RuntimeError as e:
            print(json.dumps({"error": str(e)[:500],
                              "options": ["检查 DASHSCOPE_API_KEY 是否有效/地域是否北京",
                                          "图片需 15~8192px、≤100MB、宽高比 1:10~10:1",
                                          "零凭证兜底：translate --mode local"]}, ensure_ascii=False, indent=2))
            return 4
        download(url, dest)
        ctx.add(shot="translate", label=f"图片翻译 {args.from_}→{args.to} (bailian/{args.dashscope_model})",
                file=str(dest), image_segment=not args.no_image_segment, terms=terms)
        ctx.save()
        print(json.dumps({"file": str(dest), "mode": "bailian", "model": args.dashscope_model,
                          "image_segment": not args.no_image_segment, "source_url": url}, ensure_ascii=False))
        return 0
    if args.mode == "local":
        # 离线保真档：本地 OCR + 抠图掩膜判定「字在商品主体上」+ 擦字重排 + OCR 自证（无需任何凭证）
        outdir = ctx.dir
        cmd = [str(VENV_PY), str(SKILL_DIR / "scripts" / "translate_local.py"), str(src),
               "--to", args.to, "--from", args.from_, "--outdir", str(outdir),
               "--matte-model", getattr(args, "matte_model", "u2net")]
        if getattr(args, "translate_packaging_text", False):
            cmd.append("--translate-inside-product")
        if not VENV_PY.exists():
            raise SystemExit(f"local 档需要 venv：{VENV_PY}（需 rapidocr-onnxruntime + opencv + numpy<2 + Pillow）")
        r = subprocess.run(cmd, text=True)
        if r.returncode != 0:
            return r.returncode
        dest = next(dir for dir in outdir.glob("*.png") if "_local" in dir.name and dir.name.startswith(src.stem))
        ctx.add(shot="translate", label=f"图片翻译 {args.from_}→{args.to} (local)", file=str(dest))
        ctx.save()
        print(json.dumps({"file": str(dest), "mode": "local", "engine": "rapidocr+u2net+pillow"}, ensure_ascii=False))
        return 0
    if args.mode == "precise":
        # 默认：包装/产品本体上的文字不翻（ignoreEntityRecognize=false = 执行主体识别 → 跳过主体上的字）
        ext = {"ignoreEntityRecognize": "true" if getattr(args, "translate_packaging_text", False) else "false"}
        if getattr(args, "editor_data", False):
            ext["needEditorData"] = "true"
        try:
            url = alimt_translate_image(src, args.from_, args.to, args.field, ext)
        except RuntimeError as e:
            # 凭证缺失 → 可行动降级，而不是抛裸异常（客户 agent 自己配 key 时最需要这段）
            if "阿里云凭证未配置" in str(e):
                print(json.dumps({
                    "error": str(e),
                    "options": [
                        "零凭证今天就跑：translate --mode local（本地 OCR+抠图掩膜+本地字体重排，实测 4/4 自证通过；"
                        "普通字体文案图可用，艺术字/设计字体体会降档）",
                        "配置凭证上云端保真档：~/.hermes/.env 写 ALIYUN_ACCESS_KEY_ID / ALIYUN_ACCESS_KEY_SECRET"
                        "（阿里云控制台开通『机器翻译』+『视觉智能-分割抠图』后创建 AccessKey，RAM 权限 AliyunMTFullAccess）",
                        "保真档备选：百度图片翻译 V2（需 BAIDU_TRANSLATE_APPID/KEY）",
                        "重绘档（最后手段，仅限艺术字）：translate --mode hifi —— 实测 Agnes 图生图会把文字写花"
                        "（包装原字也会被改），质量档请换 grsai gpt-image-2，且必须过 check",
                    ],
                    "doctor": "python3 imgctl.py doctor  # 复核对通道是否就绪",
                }, ensure_ascii=False, indent=2))
                return 3
            raise
        dest = ctx.dir / f"translated_{args.from_}-{args.to}_precise.png"
        download(url, dest)
    else:
        url = agnes_generate(HIFI_PROMPT.format(lang=lang_en), [src], "1:1", args.quality)
        raw = download(url, ctx.dir / "hifi_raw.png")
        dest = ctx.dir / f"translated_{args.from_}-{args.to}_hifi.png"
        compose("fit", str(raw), str(dest), "1024", "1024", "--bg", "white")
    ctx.add(shot="translate", label=f"图片翻译 {args.from_}→{args.to} ({args.mode})", file=str(dest))
    ctx.save()
    print(json.dumps({"file": str(dest), "mode": args.mode, "source_url": url}, ensure_ascii=False))
    return 0


CHECK_PROMPT = ('图1是原图，图2是AI产出。只输出 JSON：{"same_product":true|false,"fidelity_1_10":n,'
                '"text_rendered":"图2中所有文字原样抄录，无文字写 none","text_correct":true|false,'
                '"usable":true|false,"reason":"一句话中文说明"}')


TRANSLATE_CHECK_PROMPT = ('图1是翻译前的原图，图2是翻译后的产出。只输出 JSON：'
                          '{"marketing_copy_translated":true|false,   // 画面上的文案描述是否已译成目标语言\n'
                          ' "packaging_text_unchanged":true|false,     // 商品/包装上原本印的文字是否一仍其旧（未被翻译/改写）\n'
                          ' "text_rendered":"图2中所有文字原样抄录","spelling_correct":true|false,\n'
                          ' "usable":true|false,"reason":"一句话中文说明"}')


def check_pair(ref: pathlib.Path, img: pathlib.Path, kind: str | None = None) -> dict:
    prompt = TRANSLATE_CHECK_PROMPT if kind == "translate" else CHECK_PROMPT
    txt = ds_vision(prompt, [ref, img], 4000)
    try:
        v = parse_json_block(txt)
    except Exception:  # noqa: BLE001
        v = {"raw": txt[:300], "usable": None}
    if kind == "translate":
        # 包装文字被改动 = 直接判不可用（硬规则）
        if v.get("packaging_text_unchanged") is False:
            v["usable"] = False
            v.setdefault("reason", "包装/产品本体上的文字被改动了，违反硬规则")
    v["file"] = str(img)
    return v


def cmd_check(args) -> int:
    results = []
    ref = pathlib.Path(args.ref) if args.ref else None
    out_dir = None
    if args.image:
        results.append(check_pair(ref, pathlib.Path(args.image), getattr(args, "kind", None)))
    else:
        out_dir = pathlib.Path(args.dir)
        man_path = out_dir / "manifest.json"
        if not man_path.exists():
            raise SystemExit(f"找不到 manifest：{man_path}")
        man = json.loads(man_path.read_text(encoding="utf-8"))
        for s in man["shots"]:
            if not s.get("file"):
                continue
            results.append(check_pair(ref, pathlib.Path(s["file"]), s.get("shot")))
    ok = sum(1 for r in results if r.get("usable"))
    summary = {"checked": len(results), "usable": ok, "results": results}
    if out_dir:
        (out_dir / "check.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"自检结果 → {out_dir / 'check.json'}", file=sys.stderr)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if results and ok == len(results) else 1


# ────────────────────────── CLI ──────────────────────────

def main(argv: list[str]) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="imgctl", description="电商商品图引擎（自然语言 → 一整套图）")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="自检：key/venv/字体/通道连通性")

    pc = sub.add_parser("copy", help="看图写文案")
    pc.add_argument("--images", nargs="+", required=True)
    pc.add_argument("--lang", default="English")
    pc.add_argument("--count", type=int, default=3)
    pc.add_argument("--info", default="")

    pg = sub.add_parser("gen", help="文生图 / 图生图（单张）")
    pg.add_argument("--prompt", required=True)
    pg.add_argument("--ref", nargs="*")
    pg.add_argument("--ratio", default="1:1")
    pg.add_argument("--quality", choices=["high", "fast"], default="high")
    pg.add_argument("--name")
    pg.add_argument("--product")
    pg.add_argument("--out")
    pg.add_argument("--platform", choices=list(SPECS["platforms"]))
    pg.add_argument("--detail", action="store_true")

    pw = sub.add_parser("white", help="白底图")
    pw.add_argument("--image", required=True)
    pw.add_argument("--engine", choices=["model", "aliyun", "local"], default="model")
    pw.add_argument("--matte-model", dest="matte_model", choices=["u2net", "isnet-general-use"], default="u2net",
                    help="local 引擎的抠图模型：u2net 快（~4s/张）/ isnet 慢但边缘更细（~11s/张）")
    pw.add_argument("--image-url", dest="image_url", default="")
    pw.add_argument("--return-form", dest="return_form", choices=["whiteBK", "crop", "mask"], default="whiteBK")
    pw.add_argument("--platform", default="takealot", choices=list(SPECS["platforms"]))
    pw.add_argument("--detail", action="store_true")
    pw.add_argument("--quality", choices=["high", "fast"], default="high")
    pw.add_argument("--product")
    pw.add_argument("--out")

    pt = sub.add_parser("translate", help="图片翻译")
    pt.add_argument("--image", required=True)
    pt.add_argument("--from", dest="from_", default="auto")
    pt.add_argument("--to", default="en")
    pt.add_argument("--mode", choices=["auto", "bailian", "local", "precise", "hifi"], default="auto",
                    help="auto=bailian>precise>local 自动选｜也可显式指定")
    pt.add_argument("--no-image-segment", dest="no_image_segment", action="store_true",
                    help="bailian 档：连商品主体/Logo 上的文字也翻（默认不翻 = imageSegment=true）")
    pt.add_argument("--term", action="append", default=[], metavar="源=译",
                    help="bailian 档：术语干预，锁定品牌/型号不翻或固定译法，可重复")
    pt.add_argument("--domain-hint", dest="domain_hint",
                    help="bailian 档：英文领域提示（≤200 词），影响译文风格")
    pt.add_argument("--dashscope-model", dest="dashscope_model", default="qwen-mt-image-2.0",
                    choices=["qwen-mt-image-2.0", "qwen-mt-image"], help="bailian 档模型")
    pt.add_argument("--matte-model", dest="matte_model", choices=["u2net", "isnet-general-use"], default="u2net",
                    help="local 档判定「字在商品主体上」用的抠图模型")
    pt.add_argument("--field", choices=["e-commerce", "general"], default="e-commerce")
    pt.add_argument("--quality", choices=["high", "fast"], default="high")
    pt.add_argument("--translate-packaging-text", dest="translate_packaging_text", action="store_true",
                    help="连商品/包装上原本的文字一起翻（默认为否：只翻画面文案，包装上的字保持原样）")
    pt.add_argument("--editor-data", dest="editor_data", action="store_true",
                    help="额外返回译后编辑器排版数据 TemplateJson")
    pt.add_argument("--product")
    pt.add_argument("--out")

    ps = sub.add_parser("set", help="套图：文案 + 逐图位生成 + 排版 + 平台像素")
    ps.add_argument("--images", nargs="+", required=True, help="产品图（1~4 张）")
    ps.add_argument("--platform", default="takealot", choices=list(SPECS["platforms"]))
    ps.add_argument("--gallery", type=int)
    ps.add_argument("--detail", type=int)
    ps.add_argument("--lang", default="")
    ps.add_argument("--scene", default="", help="场景描述（会翻成英文进 prompt）")
    ps.add_argument("--info", default="", help="卖家补充信息（规格/材质等）")
    ps.add_argument("--quality", choices=["high", "fast"], default="high")
    ps.add_argument("--custom-w", dest="custom_w", type=int)
    ps.add_argument("--custom-h", dest="custom_h", type=int)
    ps.add_argument("--product")
    ps.add_argument("--out")
    ps.add_argument("--check", action="store_true", help="出图后自动逐张自检")
    ps.add_argument("--composite", action="store_true",
                    help="合成路线（推荐）：本地抠图 + 模型只生成背景 + 本地合成 → 产品像素零改动、包装文字不可能被改")
    ps.add_argument("--product-rgba", dest="product_rgba", help="已有的产品透明 PNG（不给则本地抠图）")
    ps.add_argument("--matte-model", dest="matte_model", choices=["u2net", "isnet-general-use"], default="u2net")
    ps.add_argument("--product-scale", dest="product_scale", type=float, default=0.0, help="产品占短边比例（默认按图位自动）")

    pk = sub.add_parser("check", help="自检：原图 vs 产出")
    pk.add_argument("--ref", help="原图路径")
    pk.add_argument("--image", help="单张产出")
    pk.add_argument("--dir", help="套图输出目录（读 manifest.json）")
    pk.add_argument("--kind", choices=["translate"], help="翻译类产出用专门的验收判据（包装文字不得被改）")

    args = p.parse_args(argv)
    fn = {"doctor": cmd_doctor, "copy": lambda a: (print(json.dumps(do_copy(
        [pathlib.Path(x) for x in a.images], a.lang, a.count, a.info), ensure_ascii=False, indent=2)), 0)[1],
        "gen": cmd_gen, "white": cmd_white, "translate": cmd_translate, "set": cmd_set, "check": cmd_check}[args.cmd]
    try:
        return fn(args)
    except RuntimeError as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
