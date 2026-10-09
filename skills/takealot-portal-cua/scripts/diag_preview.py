#!/usr/bin/env python3
"""诊断：跑到预览页并 dump「提交按钮为什么 disabled」的真因。

用法: python3 diag_preview.py facts_B_cable.json
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tl_engine as E  # noqa: E402

JS_BTN = r"""(() => {
  const b = [...document.querySelectorAll('button')].find(x => /^Submit$/i.test(x.textContent.trim()));
  if (!b) return {found: false};
  const out = {found: true, disabled: !!b.disabled, html: b.outerHTML.slice(0, 200)};
  // 往上扒 React fiber 的 props/state，找“为什么不能提交”的字段
  let el = b, lvl = 0, trail = [];
  while (el && el !== document.body && lvl < 8) {
    const pk = Object.keys(el).find(k => k.startsWith('__reactProps$'));
    const fk = Object.keys(el).find(k => k.startsWith('__reactFiber$'));
    const row = {lvl, props: null, state: null};
    if (pk && el[pk]) {
      row.props = {};
      for (const k of Object.keys(el[pk]).slice(0, 40)) {
        const v = el[pk][k];
        row.props[k] = (typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean') ? v : typeof v;
      }
    }
    if (fk && el[fk]) {
      const f = el[fk];
      const st = f.memoizedState;
      if (st && typeof st === 'object' && !Array.isArray(st)) {
        row.state = {};
        for (const k of Object.keys(st).slice(0, 25)) {
          const v = st[k];
          row.state[k] = (typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean' || v === null) ? v : typeof v;
        }
      }
      if (f.memoizedProps) {
        row.memoProps = Object.keys(f.memoizedProps).slice(0, 30);
        for (const k of ['disabled', 'reason', 'message', 'error']) {
          if (k in f.memoizedProps && typeof f.memoizedProps[k] !== 'object') row['mp_' + k] = f.memoizedProps[k];
        }
      }
    }
    trail.push(row);
    el = el.parentElement;
    lvl++;
  }
  out.trail = trail;
  return out;
})()"""

JS_HINTS = r"""(() => ({
  submissionid: (document.querySelector('[data-submissionid]') || {}).getAttribute
      ? document.querySelector('[data-submissionid]').getAttribute('data-submissionid') : null,
  disabledEls: [...document.querySelectorAll('[disabled]')].map(e => (e.tagName + ':' + (e.textContent || '').trim().slice(0, 30))).slice(0, 10),
  notices: [...document.querySelectorAll('[role=alert],[class*=Toast],[class*=toast],[class*=Notification],[class*=Banner],[class*=warning],[class*=Warning]')]
      .map(e => (e.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 120)).filter(Boolean).slice(0, 6),
  keywords: (() => {
    const t = document.body.innerText || '';
    const hits = [];
    for (const w of ['Cannot', 'cannot', 'unable', 'pending', 'processing', 'validat', 'outstanding', 'complete', 'Not Supplied', 'duplicate']) {
      const i = t.indexOf(w);
      if (i >= 0) hits.push(t.slice(Math.max(0, i - 60), i + 80).replace(/\s+/g, ' '));
    }
    return hits.slice(0, 6);
  })(),
}))()"""


def main():
    facts = json.load(open(sys.argv[1]))
    E.start_session()
    E.open_new_listing()
    E.pick_category(facts["category"])
    for fid, val in (facts.get("text_fields") or {}).items():
        E.fill_text(fid, val)
    for fid, val in (facts.get("dropdowns") or {}).items():
        E.pick_dropdown(fid, val)
    for fid, vals in (facts.get("multi_selects") or {}).items():
        E.pick_multi(fid, vals)
    if facts.get("warranty"):
        E.pick_warranty(facts["warranty"]["type"], facts["warranty"]["period"])
    for fid, val in (facts.get("rich_fields") or {}).items():
        E.fill_rich(fid, val)
    files = facts.get("images") or []
    if facts.get("image_urls"):
        out_dir = os.path.join(os.path.expanduser(os.environ.get("TL_WORKDIR") or "~/.hermes/portal_cua"), "assets", facts.get("name", "x"))
        files += E.download_images(facts["image_urls"], out_dir)
    E.add_images(files)
    E.commit_sections()
    E.assert_clean(facts.get("name", ""))
    E.continue_to_preview()
    time.sleep(4)
    print("=== preview diagnostics ===", flush=True)
    print(json.dumps(E._js_json(JS_HINTS), ensure_ascii=False, indent=1)[:1800], flush=True)
    for i in range(3):
        print(f"--- button probe {i+1}", flush=True)
        print(json.dumps(E._js_json(JS_BTN), ensure_ascii=False)[:2200], flush=True)
        time.sleep(15)
    return 0


if __name__ == "__main__":
    sys.exit(main())
