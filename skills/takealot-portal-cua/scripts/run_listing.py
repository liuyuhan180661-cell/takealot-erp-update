#!/usr/bin/env python3
"""统一入口：**优选 Hermes browser / 裸 CDP 驱动，连不上自动降级回 bsk**。

为什么这样设计（2026-10-09 实测）：
  · CDP 路（无扩展）：整条 listing 109.7–124.2s，服务端回读 PASS；Windows 不受输入法影响。
  · bsk 路（官方扩展）保留为兜底：CDP 端口起不来 / 客户机没装 Chrome / 排障时用。
  · 两条路共用同一份 tl_engine —— 换驱动只换 6 个原语（tl_cdp.install()）。

用法：
  python3 run_listing.py facts_X.json                 # 建草稿 → 断言 → 提交 → 核对
  python3 run_listing.py facts_X.json --no-submit     # 只到草稿 + 断言
  python3 run_listing.py --verify 5624176             # 服务端回读某条 submission
  python3 run_listing.py --check                      # 环境自检（CDP / bsk / 页面可见性）
  --driver auto|cdp|bsk   （默认 auto：先试 CDP，失败再用 bsk）
"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.expanduser(os.environ.get("TL_TOOLS") or "~/.hermes/tools"))

import tl_engine as E  # noqa: E402


def parse_args():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("facts", nargs="?")
    ap.add_argument("--no-submit", action="store_true")
    ap.add_argument("--verify", metavar="SUBMISSION_ID")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--driver", choices=["auto", "cdp", "bsk"], default=os.environ.get("TL_DRIVER", "auto"))
    return ap.parse_args()


def pick_driver(pref):
    """返回 (driver_name, engine_module)。auto = 先 CDP 后 bsk。"""
    tried = []
    if pref in ("auto", "cdp"):
        try:
            import tl_cdp
            eng = tl_cdp.install()
            eng._cdp.evaluate("1")                      # 真连一次才算数
            return "cdp", eng
        except Exception as e:                           # noqa: BLE001
            tried.append(f"cdp: {str(e)[:120]}")
            if pref == "cdp":
                raise SystemExit("[driver] CDP 不可用：\n  " + "\n  ".join(tried))
    if pref in ("auto", "bsk"):
        try:
            E.start_session()
            return "bsk", E
        except Exception as e:                           # noqa: BLE001
            tried.append(f"bsk: {str(e)[:120]}")
    raise SystemExit("[driver] 没有可用驱动：\n  " + "\n  ".join(tried))


def do_check():
    print("== 环境自检 ==")
    try:
        import tl_cdp
        cdp = tl_cdp.CDP()
        vis = cdp.evaluate("document.visibilityState")
        print(f"  CDP     : OK  port={tl_cdp.CDP_PORT}  url={cdp.evaluate('location.href')}  visibility={vis}")
        if vis != "visible":
            print("  ⚠ 页面不可见（窗口被遮挡/最小化）→ 键盘事件会被丢弃；"
                  "把窗口切前台或改用 --headless=new 启动")
    except Exception as e:                               # noqa: BLE001
        print(f"  CDP     : 不可用（{str(e)[:120]}）→ 可跑 cdp_browser.py 起一个")
    try:
        import subprocess
        out = subprocess.run(["bsk", "doctor"], capture_output=True, text=True, timeout=60).stdout
        print("  bsk     : " + ("OK" if "extension connected" in out else "异常（跑 bsk doctor 看）"))
    except Exception as e:                               # noqa: BLE001
        print(f"  bsk     : 不可用（{str(e)[:80]}）")
    for p in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
              r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Google\Chrome\Application\chrome.exe"):
        if os.path.exists(p):
            print(f"  browser : {p}")
    return 0


def main():
    args = parse_args()
    if args.check:
        return do_check()
    driver, eng = pick_driver(args.driver)
    print(f"[driver] {driver}", flush=True)

    if args.verify:
        src = open(os.path.join(HERE, "verify_persisted.py"), encoding="utf-8").read()
        src = src.replace('if __name__ == "__main__":', 'if False:')
        g = {"__name__": "__verify__", "__file__": "verify_persisted.py"}
        exec(compile(src, "verify_persisted.py", "exec"), g)     # noqa: S102
        # 第二个参数给 facts.json → 逐字比（真验收）；不给只能判「非空」。
        sys.argv = ["verify_persisted.py", args.verify] + ([args.facts] if args.facts else [])
        eng.start_session = lambda *a, **k: "cdp"
        return g["main"]() if g.get("main") else 0

    if not args.facts:
        print(__doc__)
        return 2
    facts = json.load(open(args.facts, encoding="utf-8"))
    t0 = time.time()
    try:
        report = eng.create_listing(facts, submit_it=not args.no_submit)
    finally:
        try:
            eng.stop_cors()
        except Exception:                                # noqa: BLE001
            pass
    report["driver"] = driver
    report["wall_s"] = round(time.time() - t0, 1)
    out = os.path.join(os.path.expanduser(os.environ.get("TL_WORKDIR") or "~/.hermes/portal_cua"),
                       "runs", f"{facts.get('name', 'listing')}.{driver}.report.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump(report, open(out, "w"), ensure_ascii=False, indent=1)
    print(json.dumps(report, ensure_ascii=False, indent=1))
    print(f"[{driver}] report -> {out}")
    print(f"\n下一步（服务端验收，唯一判据）：\n  python3 {os.path.basename(__file__)} --verify "
          f"{(report.get('submission') or {}).get('submission_id', {}).get('id', '<submission id>')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
