#!/usr/bin/env python3
"""类目字段发现：打开「新建 listing」并选到目标类目，把该类的属性字段清单（含必填标记、控件类型、标签）dump 出来。

用法:
  python3 discover_fields.py "Cellphones & Wearables" "Cellular Accessories" "Cellphone Cables"
输出:
  ~/.hermes/portal_cua/manifests/fields_<slug>.json   —— 供 create_listing 的参数映射用

为什么需要它：不同类目的必填属性完全不同（Backpacks 10 项 / Cable 另一套）。
字段清单不写死，每次现读 `data-isrequired` + 标签，才能「同一套机制换配置」。
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tl_engine as E  # noqa: E402

JS = r"""(() => {
  const rows = [...document.querySelectorAll('[data-fieldid]')].map(e => {
    const t = e.querySelector('.ZorkFieldContainer__title');
    const label = t ? (t.innerText || '').split('\n')[0].trim() : '';
    const ctrl = e.querySelector('input[type=file]') ? 'file'
      : e.querySelector('textarea') ? 'textarea'
      : e.querySelector('[role=combobox]') ? 'combobox'
      : e.querySelector('input') ? 'input'
      : e.querySelector('[contenteditable=true]') ? 'richtext' : '?';
    const opts = [...e.querySelectorAll('[role=option],option')].map(o => (o.innerText || '').trim()).slice(0, 12);
    return {fieldid: e.getAttribute('data-fieldid'), required: e.getAttribute('data-isrequired') === 'true',
            fieldtype: e.getAttribute('data-fieldtype'), label: label, control: ctrl, options: opts};
  });
  return rows;
})()"""


def main():
    levels = [a for a in sys.argv[1:] if not a.startswith("-")][:3]
    if not levels:
        print(__doc__)
        return 2
    E.start_session()
    E.open_new_listing()
    E.pick_category(levels)
    rows = E._js_json(JS)
    slug = re.sub(r"\W+", "_", "_".join(levels)).strip("_").lower()[:60]
    out_dir = os.path.join(os.path.expanduser(os.environ.get("TL_WORKDIR") or "~/.hermes/portal_cua"), "manifests")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"fields_{slug}.json")
    json.dump({"category": levels, "fields": rows}, open(path, "w"), ensure_ascii=False, indent=1)

    req = [r for r in rows if r["required"]]
    print(f"[fields] {len(rows)} 个字段，其中必填 {len(req)}：")
    for r in req:
        print(f"  REQUIRED  {r['fieldid']:52s} {r['control']:9s} {r['fieldtype'] or '':14s} {r['label'][:34]}")
        if r["options"]:
            print(f"            options: {r['options']}")
    print(f"[fields] full -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
