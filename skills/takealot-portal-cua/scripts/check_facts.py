#!/usr/bin/env python3
"""facts 守门（B 场景"一次过"的关键）：结构/必填/图片/照抄风险离线查，下拉值再 `--live` 读真实选项校验。

用法:
  python3 check_facts.py facts_X.json           # 离线（秒级，改完随时跑）
  python3 check_facts.py facts_X.json --live    # 再开一次新建页，读平台**真实**下拉选项校验值（≈1–2 分钟）

退出码：0 = 全过（可以跑 create_listing.py）；1 = 有 ERROR（先改，别跑）。

为什么必须有这个：B 的失败几乎不是"写不进去"，而是
  ① 字段名不在该类目里（拼错/多写）② 下拉值平台根本没有（实测坑：`option 'USB Type-C Cable' not found`）
  ③ 必填项没填够 ④ 图 <600px 会被**静默**禁用 Submit ⑤ 文案照抄源站（判重风险）。
这五类都能在跑之前静态查出来 —— 让"模型写内容"和"脚本守结构"各管一段。
"""

import json
import os
import re
import sys

MANIFEST_DIR = os.path.join(os.path.expanduser(os.environ.get("TL_WORKDIR") or "~/.hermes/portal_cua"), "manifests")
MIN_PX = 600
TYPE_MS = 152  # 实测：bsk press 逐字 152 ms/字（单条 listing 最大单项）


def slug_for(category):
    """类目 → 字段清单文件名（与 discover_fields.py 的命名保持一致：小写、空格转下划线）。"""
    return "fields_" + "_".join(re.sub(r"[^a-z0-9]+", "_", c.lower()).strip("_") for c in category) + ".json"


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    path = sys.argv[1]
    live = "--live" in sys.argv
    f = json.load(open(path, encoding="utf-8"))
    errors, warns, notes, oks = [], [], [], []

    # ① 结构
    for k in ("name", "category", "rich_fields", "text_fields", "dropdowns", "barcode", "image_urls", "images"):
        if k not in f:
            errors.append(f"缺字段 `{k}`（跑 replicate_facts.py 生成骨架最省事）")
    cat = f.get("category") or []
    if not (isinstance(cat, list) and len(cat) == 3):
        errors.append(f"category 必须是 3 级数组，现在是 {cat!r}")
    rich = f.get("rich_fields") or {}
    if not (rich.get("title") or "").strip():
        errors.append("rich_fields.title 空（AutoBuild 字段也要写，平台拿它当标题源）")
    desc = (rich.get("description") or "").strip()
    if not desc:
        errors.append("rich_fields.description 空")
    else:
        oks.append(f"description {len(desc)} 字 → 打字约 {len(desc) * TYPE_MS / 1000:.0f}s（152 ms/字）")

    # ② 类目字段清单：字段名合法性 + 必填覆盖
    fpath = os.path.join(MANIFEST_DIR, slug_for(cat)) if len(cat) == 3 else ""
    fields = []
    if fpath and os.path.exists(fpath):
        fields = (json.load(open(fpath, encoding="utf-8")).get("fields") or [])
        known = {x.get("fieldid") for x in fields}
        given = set(f.get("text_fields") or {}) | set(f.get("dropdowns") or {})
        for fid in sorted(given - known):
            errors.append(f"字段名 `{fid}` 不在该类目清单里（拼错？或换类目了 → 跑 discover_fields.py 重读）")
        have = {k for k, v in {**(f.get("text_fields") or {}), **(f.get("dropdowns") or {})}.items() if str(v).strip()}
        if (f.get("barcode") or "").strip():
            have.add("ProductID.Value")
        if rich.get("title"):
            have.add("title")
        if desc:
            have.add("description")
        if (f.get("warranty") or {}).get("type"):
            have.add("Attribute.warranty")
        for x in fields:
            if x.get("required") and x.get("fieldid") not in have:
                if x.get("fieldid") == "ProductID.Value":
                    notes.append("条码字段平台标了 required，但**实测留空能提交**（平台生成 + 默认允许跟卖）→ 按业务选，不算错")
                elif str(x.get("fieldid", "")).startswith(("Attribute.merchant_packaged_dimensions", "Attribute.merchant_packaged_weight")) \
                        and f.get("_logistics_source") == "model-estimate":
                    notes.append(f"⚠️ `{x.get('fieldid')}` 用的是**模型估值**（源页没有这几项：它们是卖家侧物流属性）"
                                 f"→ 上线后可用真实值覆盖，或写进 `config/spec_defaults.json` 一次固化")
                else:
                    errors.append(f"必填没填：`{x.get('fieldid')}`（{x.get('label')}）")
        oks.append(f"类目清单 {os.path.basename(fpath)}：{len(fields)} 字段，必填 {sum(1 for x in fields if x.get('required'))} 项")
    else:
        warns.append(f"没有类目字段清单 {os.path.basename(fpath) or '?'} → 字段名/必填没查（先跑 discover_fields.py）")

    # ③ 条码策略（业务开关）
    notes.append("barcode 留空 = 平台生成 + **默认允许他人跟卖**；填自有 GS1 = 独享。当前："
                 + ("**留空（平台生成/可被跟卖）**" if not (f.get("barcode") or "").strip() else f"自有 {f['barcode']}"))

    # ④ 图片
    urls, files = f.get("image_urls") or [], f.get("images") or []
    if len(urls) + len(files) > 20:
        errors.append(f"图片超过 20 张（{len(urls) + len(files)}）")
    for u in urls:
        m = re.search(r"/(s-[a-z]+)\.file$", u)
        if not m:
            warns.append(f"图片 URL 不是 covers_images/…/s-xx.file 形态，档位无法确认 ≥600px：{u[:70]}")
        elif m.group(1) != "s-zoom":
            errors.append(f"图片档位 {m.group(1)} 不保证 ≥600px（只有 s-zoom=1200px 合格；"
                          f"太小平台**不报错**、只把 Submit 静默禁用）→ 改成 /s-zoom.file：{u[:70]}")
    for p in files:
        if not os.path.exists(p):
            errors.append(f"本地图片不存在：{p}")
    if urls or files:
        oks.append(f"图片 {len(urls)} 张 URL + {len(files)} 张本地（≤20 ✓）")

    # ⑤ 照抄风险（判重最可能就栽在这）
    mat = f.get("_material") or {}
    src_title = re.sub(r"\s+", " ", (mat.get("source_title") or "")).strip()
    src_text = re.sub(r"\s+", " ", (mat.get("source_text") or ""))
    if src_title and rich.get("title") and rich["title"].strip().lower() == src_title.lower():
        warns.append("title 与源站标题**一字不差** → 判重风险（改写它）")
    if desc and src_text:
        long_run = max((len(m.group(0)) for m in re.finditer(r"[^\s]{20,}", desc) if m.group(0) in src_text), default=0)
        if long_run >= 40:
            warns.append(f"description 里有 {long_run} 字的整段与源站原文相同 → 判重风险（重写这几句）")
    elif desc:
        notes.append("facts 里没有 `_material`（源素材）→ 照抄风险没法查；B 场景建议保留它")

    # ⑥ 在线：读平台真实下拉选项校验值
    if live:
        if not fields:
            errors.append("--live 需要类目字段清单（先 discover_fields.py）")
        else:
            try:
                sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
                import tl_engine as E
                E.start_session()
                E.open_new_listing()
                E.pick_category(cat)
                E.ensure_attributes(f)
                bad = []
                for fid, val in (f.get("dropdowns") or {}).items():
                    if not str(val).strip():
                        continue
                    try:
                        # 直接让引擎**真去选一遍**（比"读选项列表"可信：可搜索下拉的选项只有输入后才渲染，
                        # 实测 cable_type 那种会读出假的 "(Optional)" → 假阴性）。
                        E.pick_dropdown(fid, val)
                        oks.append(f"[live] {fid} = `{val}` ✓（引擎真选上了）")
                    except Exception as e:  # noqa: BLE001
                        m = re.search(r"平台可选：(.+)$", str(e))
                        bad.append((fid, val, m.group(1) if m else "（读不到选项列表，人工看）"))
                for fid, val, hint in bad:
                    errors.append(f"[live] {fid}: 平台选不到 `{val}`；平台可选：{hint}")
                E.stop_cors()
            except Exception as e:  # noqa: BLE001
                warns.append(f"[live] 没跑成：{str(e)[:160]}（离线检查结果仍有效）")

    # 汇总
    for m in oks:
        print(f"  ✓ {m}")
    for m in notes:
        print(f"  · {m}")
    for m in warns:
        print(f"  ⚠ {m}")
    for m in errors:
        print(f"  ✗ {m}")
    print()
    print(f"结论: {'❌ {} 个必须改的问题'.format(len(errors)) if errors else '✅ 通过（可以跑 create_listing.py）'}"
          f"{'；另有 {} 条警告'.format(len(warns)) if warns else ''}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
