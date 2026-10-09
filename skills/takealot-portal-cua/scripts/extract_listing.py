#!/usr/bin/env python3
"""B1：从一条 takealot.com listing（PDP）抽出结构 → manifest.json。

用法: python3 extract_listing.py <pdp_url> [name]
输出: ~/.hermes/portal_cua/manifests/<name>.json

抽的东西：标题、品牌、类目路径、图片 URL 列表、卖点、描述、规格行、价格。
优先用页面里的 JSON-LD（结构最干净），缺失再用 DOM 兜底。
"""

import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bskhelp as B  # noqa: E402
import tl_engine as E  # noqa: E402

OUT_DIR = os.path.join(os.path.expanduser(os.environ.get("TL_WORKDIR") or "~/.hermes/portal_cua"), "manifests")

JS_EXTRACT = r"""(() => {
  const out = {};
  const ld = [...document.querySelectorAll('script[type="application/ld+json"]')]
      .map(s => { try { return JSON.parse(s.textContent); } catch (e) { return null; } })
      .filter(Boolean);
  out.ld = ld;
  out.url = location.href;
  out.title = document.title;
  out.h1 = (document.querySelector('h1') || {}).innerText || '';
  const main = document.querySelector('main') || document.body;
  out.text = (main.innerText || '').replace(/\n{2,}/g, '\n').slice(0, 12000);
  // 产品图集在 DOM 里最先出现；推荐位（carousel）在后面。故按 DOM 顺序按 hash 去重取前 10。
  const seen = new Set(), imgs = [];
  for (const u of [...document.querySelectorAll('img')].map(i => i.src)) {
    const m = /covers_images\/([0-9a-f]+)\//.exec(u || '');
    if (!m || seen.has(m[1])) continue;
    seen.add(m[1]); imgs.push(u);
    if (imgs.length >= 10) break;
  }
  out.images = imgs;
  const crumbs = [...document.querySelectorAll('a')].map(a => (a.innerText || '').trim())
      .filter(t => t && t.length < 40);
  out.crumbWords = crumbs.slice(0, 12);
  return JSON.stringify(out);
})()"""


def _from_ld(ld):
    """从 JSON-LD 里取 Product 节点。"""
    for node in ld:
        items = node if isinstance(node, list) else [node]
        for it in items:
            if not isinstance(it, dict):
                continue
            t = it.get("@type")
            types = t if isinstance(t, list) else [t]
            if any(str(x).lower() == "product" for x in types):
                return it
    return {}


def parse(img_url):
    """把抽取到的原始结构整理成 manifest。"""
    ld = _from_ld(img_url.get("ld") or [])
    text = img_url.get("text") or ""
    title = (ld.get("name") or img_url.get("h1") or "").strip()
    brand = ""
    b = ld.get("brand")
    if isinstance(b, dict):
        brand = b.get("name", "")
    elif isinstance(b, str):
        brand = b
    if not brand:
        m = re.search(r"\n([A-Z][A-Za-z&\.\- ]{1,24})\n", text[:1500])
        brand = m.group(1).strip() if m else ""

    # 类目：PDP 顶部面包屑是连续拼接的（如 Cellphones & WearablesCellular AccessoriesCellphone Cables）
    head = text[:300].split("\n")[0]
    cat = []
    if "category" in ld:
        c = ld["category"]
        cat = [c] if isinstance(c, str) else list(c)

    # 图片：优先 PDP 大图，去掉重复 hash
    seen, images = set(), []
    for u in img_url.get("images") or []:
        m = re.search(r"covers_images/([0-9a-f]+)/([^/]+)$", u)
        if not m:
            continue
        h, f = m.groups()
        if h in seen:
            continue
        seen.add(h)
        images.append(u if f.startswith("s-pdpxl") else u)

    # 卖点 / 描述 / 规格：从正文里切
    keys, desc, rows = [], "", []
    i = text.find("Description")
    if i >= 0:
        desc = text[i + len("Description"):].split("Show More")[0].strip()[:4000]
    for line in text.split("\n"):
        line = line.strip()
        if re.match(r"^(Cable length|Material|Colour|Color|Connector|Warranty|Brand|Item code|What's in the box|Length|Weight|Battery|Power)", line, re.I) and 3 < len(line) < 160:
            rows.append(line)
    return {
        "source_url": img_url.get("url"),
        "source_title": title,
        "brand": brand,
        "category_path_hint": head[:120],
        "category_ld": cat,
        "images": images[:12],
        "description_raw": desc,
        "spec_rows": sorted(set(rows))[:40],
        "pf": ld.get("offers") if ld.get("offers") else None,
    }


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    url = sys.argv[1]
    name = sys.argv[2] if len(sys.argv) > 2 else re.sub(r"\W+", "_", url.split("/")[-1])[:40]
    E.start_session()
    E.goto(url)
    E._js("window.scrollTo(0, document.body.scrollHeight*0.5)")
    time.sleep(2)
    E._js("window.scrollTo(0, document.body.scrollHeight)")
    time.sleep(2)
    raw = E._js_json(f"""(()=>{{return JSON.parse({json.dumps(JS_EXTRACT)}() || 'null');}})()""")
    man = parse(raw)
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"{name}.json")
    json.dump({"raw": raw, "manifest": man}, open(path, "w"), ensure_ascii=False, indent=1)
    print(json.dumps({k: man[k] for k in ("source_title", "brand", "category_path_hint", "images")}, ensure_ascii=False, indent=1)[:1200])
    print(f"[B1] manifest -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
