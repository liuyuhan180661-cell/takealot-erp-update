#!/usr/bin/env python3
"""服务端持久化核对：某条 submission 的 description 与 facts 里写的**是否逐字一致**。

**为什么必须有这个命令**：Draft.js 富文本可以被 JS 直接改页面状态（fiber 注入）或用 `bsk fill`
写进去，页面上读回一切正常 —— 但**存不进服务器**。唯一可信的判据是「从服务器重新读回来」。

**判据（2026-09-27 收紧）**：
  · 找到该 submission 对应的 facts（自动从 `runs/*.report.json` 里按 submission_id 反查，或第二个参数直接给路径）；
  · 服务端 description 与 `facts.rich_fields.description` **逐字比**；
  · 完全一致 → ✅ PASS；
  · 只在**末尾**差 ≤2 字 → ⚠ PASS(近似)，并打印差在哪里（平台最后一次输入事件会滞后一步，
    引擎"补尾"可能多补一个字；见 pitfalls G9）；
  · 其它任何差异（含中间）→ ❌ FAIL，打印首个差异位置 + 前后各 30 字；
  · 找不到 facts → 退化为"非空即通过"的**弱判据**并明确警告（别把弱判据当验收）。
  · title 是平台 AutoBuild 字段（服务端为空属正常），只提示不判 FAIL。

用法：
  python3 verify_persisted.py 5552977                      # 自动反查 facts
  python3 verify_persisted.py 5552977 /path/facts_X.json   # 手动指定（最稳）
"""
import glob
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tl_engine as E  # noqa: E402

FIELDS = ("title", "description")


def open_draft(sid):
    """打开草稿编辑页（列表链接是 /single-product/<id>，进去是摘要页，再点 Edit）。"""
    E.goto(f"https://sellers.takealot.com/single-product/{sid}")
    time.sleep(4)
    if not E._js("document.querySelectorAll('[data-fieldid]').length"):
        E._js("""(()=>{const b=Array.from(document.querySelectorAll('button'))
            .find(x=>x.innerText.trim()==='Edit'); if(b)b.click(); return true;})()""")
        for _ in range(24):
            time.sleep(1.5)
            if E._js("document.querySelectorAll('[data-fieldid]').length"):
                break
    return E._js("document.querySelectorAll('[data-fieldid]').length") or 0


def latest_draft_id():
    E.goto("https://sellers.takealot.com/catalogue/submissions")
    time.sleep(3)
    ids = E._js_json("""(()=>{const o=[];document.querySelectorAll('a[href*="/single-product/"]')
        .forEach(a=>{const m=(a.getAttribute('href')||'').match(/\\/single-product\\/(\\d+)/);
        if(m)o.push(m[1]);});return o.slice(0,5);})()""") or []
    return ids[0] if ids else None


def facts_for(sid, explicit=None):
    """按 submission id 反查 facts 路径：报告里存了 facts_file（create_listing 写的）。"""
    if explicit:
        return explicit if os.path.exists(explicit) else None
    workdir = os.path.expanduser(os.environ.get("TL_WORKDIR") or "~/.hermes/portal_cua")
    for rp in sorted(glob.glob(os.path.join(workdir, "runs", "*.report.json")),
                     key=os.path.getmtime, reverse=True):
        try:
            rep = json.load(open(rp, encoding="utf-8"))
        except Exception:
            continue
        got = ((rep.get("submission") or {}).get("submission_id") or {}).get("id")
        fp = rep.get("facts_file")
        if str(got) == str(sid) and fp and os.path.exists(fp):
            return fp
    return None


def first_diff(a, b):
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return i
    return min(len(a), len(b))


def main():
    arg = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
    facts_arg = (sys.argv[2] if len(sys.argv) > 2 else "").strip()
    E.start_session()
    if arg and not arg.isdigit():
        print(f"FAIL 参数不是 submission id：{arg!r}（要 6 位纯数字，例如 5552890）")
        return 2
    if arg:
        sid = arg
    else:
        sid = latest_draft_id()
        if not sid:
            print("FAIL 没在列表里找到草稿，传一个 submission id 进来")
            return 1
        print(f"⚠️ 没给 id → 只能拿列表最新草稿 {sid} 来验。**它不是你要验的那条时结论无效**："
              f"submission id 在 create_listing.py 的报告/日志里都有（`submission_id.id`）。")
    server = {}
    n = open_draft(sid)
    print(f"草稿 {sid}：字段数={n}")
    if not n:
        print("FAIL 编辑页没渲染出字段（会话退化？重启会话再试）")
        return 1
    for fid in FIELDS:
        server[fid] = E._rich_truth(fid) or {}

    fpath = facts_for(sid, facts_arg or None)
    if not fpath:
        for fid in FIELDS:
            t = server[fid]
            ln, head = t.get("len"), (t.get("text") or "")[:60].replace("\n", "\\n")
            if fid == "title":
                print(f"  {fid:<12} 服务端长度={ln}  {'✅' if ln else '⚠ 空（AutoBuild 字段：平台自生成，正常）'}  {head!r}")
            else:
                print(f"  {fid:<12} 服务端长度={ln}  {'✅ 非空' if ln else '❌ 空（服务端没存）'}  {head!r}")
        print("\n⚠️ 结论: 只能判到「非空」（找不到该 submission 的 facts，无法逐字比）。"
              "\n   要真验收 → 把 facts 路径当第二个参数传进来：python3 verify_persisted.py "
              f"{sid} <facts.json>")
        return 0 if server["description"].get("len") else 1

    facts = json.load(open(fpath, encoding="utf-8"))
    want = (facts.get("rich_fields") or {}).get("description") or ""
    got = server["description"].get("text") or ""
    print(f"比对面: facts={os.path.basename(fpath)}（期望 {len(want)} 字）| 服务端 {len(got)} 字")

    t = server["title"]
    print(f"  title        服务端长度={t.get('len')}  "
          f"{'✅' if t.get('len') else '⚠ 空（AutoBuild 字段：平台自生成，正常）'}  "
          f"{(t.get('text') or '')[:50]!r}")

    if got == want:
        print(f"  description  ✅ **逐字一致**（{len(got)} 字）")
        print(f"\n结论: PASS —— facts 的 description 与服务端逐字一致。")
        return 0

    d = first_diff(want, got)
    tail_only = d >= min(len(want), len(got)) - 2      # 只在末尾附近差
    ctx_w = want[max(0, d - 30):d + 30]
    ctx_g = got[max(0, d - 30):d + 30]
    print(f"  description  首个差异在第 {d + 1} 字（期望 {len(want)} / 实际 {len(got)}）")
    print(f"               期望: {ctx_w!r}")
    print(f"               实际: {ctx_g!r}")
    if tail_only and abs(len(got) - len(want)) <= 2:
        print(f"\n结论: ⚠ PASS(近似) —— 只在末尾差 {abs(len(got) - len(want))} 字。"
              "\n   成因：平台最后一次输入事件会滞后一步，引擎「补尾」可能多补一个字（见 pitfalls G9）。"
              "\n   要严格逐字一致 → 把文案末尾写成句末标点后重跑，或人工删掉多余的那个字。")
        return 0
    print(f"\n结论: FAIL —— 服务端与 facts 不一致（第 {d + 1} 字起）。"
          "\n   （页面内写进去不等于存进去；见 references/pitfalls.md G3）")
    return 1


if __name__ == "__main__":
    sys.exit(main())
