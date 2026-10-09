#!/usr/bin/env python3
"""B 场景脚手架：manifest（extract_listing.py 的产物）→ facts 骨架。

用法:
  python3 replicate_facts.py <manifest.json> <name> --category "L1/L2/L3" [--fields <fields_*.json>]

**分工（这条界线别越，B 一次过的关键）**
  · **结构由本脚本产**：字段名、图片档位（换成 ≥600px 的 `s-zoom`）、条码策略位 —— 全部从
    「类目字段清单」（`discover_fields.py` 的产物）来，保证 `create_listing.py` 认。
  · **内容由模型填**：重写后的标题/描述 + 各属性值。脚本只留空值，并把源素材塞进 `_material`
    给模型当改写输入（引擎不读这个键，纯素材）。

产出后**先过 `check_facts.py`**（离线 → 再 `--live` 读真实下拉选项），再跑 `create_listing.py`。
B 的失败几乎都不是"写不进去"，而是 facts 里的字段名/选项值平台没有 —— 那两类都由守门脚本拦。
"""

import json
import os
import re
import sys

MANIFEST_DIR = os.path.join(os.path.expanduser(os.environ.get("TL_WORKDIR") or "~/.hermes/portal_cua"), "manifests")
MAX_IMAGES = 20


def slug_for(category):
    """类目 → 字段清单文件名（与 discover_fields.py 的命名保持一致：小写、空格转下划线）。"""
    return "fields_" + "_".join(re.sub(r"[^a-z0-9]+", "_", c.lower()).strip("_") for c in category) + ".json"


def cover_ids(imgs):
    """从源图 URL 里抽 cover id（去重、保序）。源页会给同一张图的多个尺寸档，只留 id。"""
    out, seen = [], set()
    for u in imgs or []:
        m = re.search(r"covers_images/([0-9a-f]{8,})/", str(u))
        if m and m.group(1) not in seen:
            seen.add(m.group(1))
            out.append(m.group(1))
    return out


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    manifest_path, name = sys.argv[1], sys.argv[2]
    category = fields_path = None
    if "--category" in sys.argv:
        category = [c.strip() for c in sys.argv[sys.argv.index("--category") + 1].split("/") if c.strip()]
    if "--fields" in sys.argv:
        fields_path = sys.argv[sys.argv.index("--fields") + 1]

    man = json.load(open(manifest_path, encoding="utf-8"))
    if not category:
        print("[FATAL] 必须给 --category \"一级/二级/三级\"（类目路径不能猜：源站的面包屑和卖家后台类目名不一样）")
        return 2
    if not fields_path:
        fields_path = os.path.join(MANIFEST_DIR, slug_for(category))
    if not os.path.exists(fields_path):
        print(f"[FATAL] 找不到类目字段清单 {fields_path}\n        先跑：python3 discover_fields.py " +
              " ".join(f'"{c}"' for c in category))
        return 2

    fman = json.load(open(fields_path, encoding="utf-8"))
    fields = fman.get("fields") or []
    ids = [f.get("fieldid") for f in fields]

    text_fields, dropdowns, optional = {}, {}, []
    for f in fields:
        fid, ctrl = f.get("fieldid"), (f.get("control") or "").lower()
        if not fid or fid in ("title", "description"):
            continue
        if fid == "Attribute.warranty" or fid.startswith("ProductID"):
            continue  # 走 facts 的 `warranty` / `barcode` 两个专门键（引擎另有一套处理），别塞进通用桶
        box = dropdowns if any(k in ctrl for k in ("select", "combobox", "radio")) else text_fields
        if f.get("required"):
            box[fid] = ""
        else:
            optional.append(fid)

    ids_ = cover_ids(man.get("imgs"))
    images = [f"https://media.takealot.com/covers_images/{i}/s-zoom.file" for i in ids_[:MAX_IMAGES]]

    # 物流属性（包装长/宽/高/重）：**买家页从来不公开**（卖家侧属性），所以从 config/spec_defaults.json 按类目取。
    # 取不到就留空 → 由模型估值并在 facts 里标 _logistics_source="model-estimate"（守门脚本会把必填错误降级为提醒）。
    LOGI = {
        "length": "Attribute.merchant_packaged_dimensions.length",
        "width": "Attribute.merchant_packaged_dimensions.width",
        "height": "Attribute.merchant_packaged_dimensions.height",
        "weight": "Attribute.merchant_packaged_weight.value",
    }
    logistics, src = {}, ""
    try:
        cfg = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                          "..", "config", "spec_defaults.json"), encoding="utf-8"))
        entries = cfg.get("_已有条目") or {}
        ent = entries.get(category[-1].strip()) or entries.get("/".join(category)) or {}
        logistics = {k: str(v) for k, v in ent.items() if k in LOGI and str(v).strip()}
        if logistics:
            src = "spec_defaults"
    except Exception:
        pass
    for k, fid in LOGI.items():
        if logistics.get(k) and fid in text_fields:
            text_fields[fid] = logistics[k]

    facts = {
        "name": name,
        "scene": f"B 拆解重塑：源 {man.get('url','')}",
        "source": man.get("url", ""),
        "category": category,
        "rich_fields": {"title": "", "description": ""},
        "text_fields": text_fields,
        "dropdowns": dropdowns,
        "warranty": {"type": "", "period": ""} if "Attribute.warranty" in ids else {},
        "barcode": "",
        "images": [],
        "image_urls": images,
        "optional": optional,
        # "spec_defaults" = 来自 config/spec_defaults.json；"model-estimate" = 模型估值；"" = 还没有
        "_logistics_source": src,
        # 引擎不读这个键：纯给模型当改写素材（源文案 + 价格 + 规格段落）
        "_material": {
            "source_url": man.get("url", ""),
            "source_title": man.get("title", ""),
            "source_h1": man.get("h1", ""),
            "source_price": man.get("price") or [],
            "source_text": (man.get("text") or "")[:4000],
            "cover_ids": ids_,
        },
    }
    out = os.path.join(os.path.expanduser(os.environ.get("TL_WORKDIR") or "~/.hermes/portal_cua"),
                       "manifests", f"facts_{name}.json")
    json.dump(facts, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    todo = [fid for fid in text_fields if not text_fields[fid]] + [fid for fid in dropdowns if not dropdowns[fid]]
    if "Attribute.warranty" in ids:
        todo.insert(0, "warranty.type / warranty.period（例：Full / 60 Months）")
    if any(str(i).startswith("ProductID") for i in ids):
        todo.insert(0, "barcode（留空 = 平台生成 + 可被跟卖；填自有 GS1 = 独享）")
    print(f"[OK] facts 骨架 -> {out}")
    print(f"     category  = {' / '.join(category)}（字段清单 {os.path.basename(fields_path)}）")
    print(f"     image_urls= {len(images)} 张（已换成 s-zoom，≥600px；上限 {MAX_IMAGES}）")
    print(f"     源素材    = _material（{len(facts['_material']['source_text'])} 字原文 + 标题 + 价格）")
    print(f"\n留给模型/人填的 {len(todo)} 项（文案在 rich_fields，属性值在 text_fields/dropdowns）：")
    for fid in todo:
        print(f"  · {fid}")
    print("\n填完先守门（别直接跑）：")
    print(f"  python3 check_facts.py {out}")
    print(f"  python3 check_facts.py {out} --live     # 读平台真实下拉选项，校验值")
    print("  barcode 留空 = 平台生成 + 默认允许跟卖；填自有 GS1 = 独享（业务开关，按需选）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
