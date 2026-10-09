#!/usr/bin/env python3
"""A 场景：自编辑新建 listing。

用法:
  python3 create_listing.py facts_A_backpack.json            # 建草稿 → 断言 → 提交 → 核对
  python3 create_listing.py facts_A_backpack.json --no-submit # 只建草稿 + 断言，不提交

facts JSON 结构见 facts_A_backpack.json。
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tl_engine as E  # noqa: E402


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    facts = json.load(open(sys.argv[1], encoding="utf-8"))
    submit_it = "--no-submit" not in sys.argv
    E.start_session()
    try:
        report = E.create_listing(facts, submit_it=submit_it)
    finally:
        E.stop_cors()
    # 报告文件按 **facts 文件名** 命名（不要用 facts["name"]：复制模板时那个字段常忘改，
    # 会让两次跑盖成同一份报告 —— 2026-09-26 实测踩过，害得 D 跑的报告冒充了 C 跑的）。
    report["facts_file"] = os.path.abspath(sys.argv[1])
    report["facts_name"] = facts.get("name")
    print(json.dumps(report, ensure_ascii=False, indent=1))
    stem = os.path.splitext(os.path.basename(sys.argv[1]))[0]
    out = os.path.join(os.path.expanduser(os.environ.get("TL_WORKDIR") or "~/.hermes/portal_cua"), "runs", f"{stem}.report.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump(report, open(out, "w"), ensure_ascii=False, indent=1)
    print(f"[A] report -> {out}")
    sid = (report.get("submission") or {}).get("submission_id") or {}
    if sid.get("id"):
        print(f"\n★ 下一步（验收必须做，否则等于没验）：python3 verify_persisted.py {sid['id']}")
        if sid.get("url"):
            print(f"  提交记录: {sid['url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
