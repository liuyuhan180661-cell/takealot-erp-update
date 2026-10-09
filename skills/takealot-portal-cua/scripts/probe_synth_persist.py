#!/usr/bin/env python3
"""合成粘贴 → 存草稿 → 重开 → 核对**服务端**（唯一判据）。

前置事实（本机实测）：
  · fiber 注入 / bsk fill / CDP Input.insertText：只改页面（状态或 DOM），**服务端存不进去**
  · OS 真实粘贴：服务端存得进（对照组 5551654 description=477）
  · 页面内合成 `paste` + `beforeinput(insertFromPaste)` 两条齐发：**Draft 会真正处理**
    （状态 0→142），单发任一条都不行

本脚本只回答一件事：这个合成粘贴能不能**持久化**。

用法：python3 probe_synth_persist.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tl_engine as E  # noqa: E402

CAT = ["Consumer Electronics", "Electronic Accessories", "Cellphone Cables"]
TITLE = "Synth Paste Durability Test 60W USB Type-C Cable 1m"
DESC = ("Synthetic paste durability check paragraph one.\n"
        "Second paragraph to verify multi-line persistence works.")

SYNTH = r"""
(() => {
  const txt = __TXT__, fid = __FID__;
  const box = document.querySelector('[data-fieldid="' + fid + '"]');
  if (!box) return {err: 'no box'};
  const ed = box.querySelector('[contenteditable="true"]');
  if (!ed) return {err: 'no contenteditable'};
  ed.scrollIntoView({block: 'center'});
  ed.focus();
  if (document.activeElement !== ed) return {err: 'focus failed'};
  const dt = new DataTransfer();
  dt.setData('text/plain', txt);
  dt.setData('text/html', '<div>' + txt.split('\n').join('</div><div>') + '</div>');
  const out = {events: []};
  const fire = (label, ev) => {
    try { const r = ed.dispatchEvent(ev);
      out.events.push(label + ': dispatched=' + r + ' prevented=' + ev.defaultPrevented); }
    catch (e) { out.events.push(label + ' THREW ' + String(e).slice(0, 120)); }
  };
  fire('paste', new ClipboardEvent('paste', {clipboardData: dt, bubbles: true, cancelable: true}));
  fire('beforeinput', new InputEvent('beforeinput', {inputType: 'insertFromPaste', data: txt,
    dataTransfer: dt, bubbles: true, cancelable: true}));
  return out;
})()
"""


def write_synth(fid, txt):
    return E._js_json(SYNTH.replace("__TXT__", json.dumps(txt)).replace("__FID__", json.dumps(fid)))


def main():
    E.start_session()
    E.open_new_listing()
    E.pick_category(CAT)
    if not (E._js("document.querySelectorAll('[data-fieldid]').length") or 0):
        print("FAIL 字段没渲染出来")
        return 1

    print("=== ① 合成粘贴写入 ===")
    for fid, val in (("title", TITLE), ("description", DESC)):
        r = write_synth(fid, val)
        time.sleep(1.2)
        st = (E._rich_truth(fid) or {}).get("len")
        dom = len(E._js("""(()=>{const ed=document.querySelector('[data-fieldid="%s"] [contenteditable="true"]');
            return ed?(ed.innerText||''):'';})()""" % fid) or "")
        print(f"  {fid}: {r}\n     状态 {st}（期望 {len(val)}）  DOM {dom}")

    print("=== ② 存草稿 → 重开 → 读服务端 ===")
    try:
        E.click_button(r"^Save and Close$", timeout=10)
    except Exception as e:
        print("  保存失败:", str(e)[:100])
        return 1
    time.sleep(6)
    ids = E._js_json("""(()=>{const o=[];document.querySelectorAll('a[href*="/single-product/"]').forEach(a=>{
        const m=(a.getAttribute('href')||'').match(/\\/single-product\\/(\\d+)/); if(m)o.push(m[1]);});return o.slice(0,3);})()""") or []
    if not ids:
        print("FAIL 列表里没找到草稿")
        return 1
    sid = ids[0]
    E.goto(f"https://sellers.takealot.com/single-product/{sid}")
    time.sleep(4)
    if not E._js("document.querySelectorAll('[data-fieldid]').length"):
        E._js("""(()=>{const b=Array.from(document.querySelectorAll('button')).find(x=>x.innerText.trim()==='Edit');
            if(b)b.click(); return true;})()""")
        for _ in range(24):
            time.sleep(1.5)
            if E._js("document.querySelectorAll('[data-fieldid]').length"):
                break
    dp = E._rich_truth("description") or {}
    tp = E._rich_truth("title") or {}
    print(f"  草稿 {sid}")
    print(f"  title       期望 {len(TITLE)} → 服务端 {tp.get('len')}  head={(tp.get('text') or '')[:40]!r}")
    print(f"  description 期望 {len(DESC)} → 服务端 {dp.get('len')}  head={(dp.get('text') or '')[:50]!r}")
    ok = (dp.get("len") or 0) > 0
    print("\n结论:", "✅ 合成粘贴能持久化 —— 富文本可全自动、无人值守" if ok
          else "❌ 合成粘贴也不持久（服务端仍为空）")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
