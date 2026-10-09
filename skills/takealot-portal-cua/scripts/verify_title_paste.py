#!/usr/bin/env python3
"""标题自动写入验收（客户机/本机都能跑）——一条命令给出 PASS/FAIL。

它做的事：
  0) 前置检查：Chrome 必须有可见窗口（扩展掉线最常见的原因就是"一个窗口都没有"）
  1) 清掉所有 bsk 会话，只起 1 个（多个会话 = 多个 agent 窗口 = 窗口寻址歧义，实测过）
  2) 往 agent 标签注入受控探针（contenteditable），测「置前 + ⌘V」能否落到页面里
  3) 全通 → 可选跑 A 场景全流程（--full），用 assert_clean 做最终判定

用法：
  python3 verify_title_paste.py          # 只测粘贴原语
  python3 verify_title_paste.py --full   # 顺便跑 A 场景（标题/描述在 assert_clean 范围内）
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bskhelp as B  # noqa: E402
import tl_engine as E  # noqa: E402


def osa(script):
    return subprocess.run(["osascript", "-e", script], capture_output=True, text=True).stdout.strip()


def probe_paste(rounds=3):
    E.goto("https://sellers.takealot.com/catalogue/submissions")
    time.sleep(2)
    if not (E._js("location.href") or "").startswith("https://sellers"):
        print("FAIL  agent 标签不在卖家后台（URL=%r）" % E._js("location.href"))
        return False
    E._js("""(()=>{let w=document.getElementById('tlp');
if(!w){w=document.createElement('div');w.id='tlp';document.body.appendChild(w);}
w.style.cssText='position:fixed;top:0;left:0;z-index:2147483647;background:#fff;padding:8px';
w.innerHTML='<div id="tlp-ce" contenteditable="true" style="border:2px solid #000;width:440px;height:44px"></div>';
return true;})()""")
    ok = 0
    for r in range(1, rounds + 1):
        txt = "PASTE-PROBE-%d-%d" % (int(time.time()) % 100000, r)
        E._clip_set(txt)
        hit = E._raise_window()
        time.sleep(0.6)
        E._js("(()=>{document.getElementById('tlp-ce').focus();return true;})()")
        time.sleep(0.3)
        E._key("select_all")
        time.sleep(0.2)
        E._key("paste")
        time.sleep(1.2)
        got = (E._js("(()=>{const e=document.getElementById('tlp-ce');return e?e.innerText:'<gone>';})()") or "").strip()
        good = got == txt
        ok += good
        print(f"  轮{r}: raise命中={hit} {'PASS' if good else 'FAIL'} 期望 {txt} 实得 {got!r}")
    E._js("document.getElementById('tlp')?.remove(); true")
    return ok == rounds


def main():
    print("== 标题自动写入验收 ==")
    pids = subprocess.run(["pgrep", "-f", "Google Chrome.app/Contents/MacOS/Google Chrome"],
                          capture_output=True, text=True).stdout.split()
    real = [p for p in pids if "headless" not in subprocess.run(["ps", "-o", "command=", "-p", p],
                                                               capture_output=True, text=True).stdout]
    wins = osa('tell application "Google Chrome" to get title of every window')
    print(f"Chrome 实例(非 headless)={len(real)}  可见窗口={wins or '（无）'}")
    if not wins:
        print("FAIL  没有可见的 Chrome 窗口 —— 请手动启动 Chrome 并留一个窗口开着，再重跑本脚本")
        return 3

    import json as _json
    _raw = subprocess.run(["bsk", "status", "--json"], capture_output=True, text=True).stdout
    try:
        _sess = _json.loads(_raw).get("sessions") or []
    except Exception:
        _sess = []
    for sid in [x.get("session_id") for x in _sess if isinstance(x, dict)]:
        B.bsk("session", "stop", sid)
    time.sleep(2)
    print("session:", E.start_session())

    print("① 粘贴原语（受控探针）")
    if not probe_paste():
        print("\n结论: FAIL —— ⌘V 落不进 agent 窗口。")
        print("  交付口径：引擎会全自动填完其余字段 + 存草稿 + 打印标题/描述待粘文本（人工粘两下）。")
        print("  排查顺序：Chrome 是否只有一个实例且窗口可见 → 是否只有 1 个 bsk 会话 → 是否有别的 Seller Portal 窗口")
        return 1
    print("\n结论: PASS —— 置前 + ⌘V 可用")

    if "--full" in sys.argv:
        print("\n② A 场景全流程（断言驱动）")
        import json
        fpath = "facts_A_backpack.json"
        if "--facts" in sys.argv:
            fpath = sys.argv[sys.argv.index("--facts") + 1]
        if not os.path.isabs(fpath):
            fpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), fpath)
        facts = json.load(open(fpath, encoding="utf-8"))
        print(f"facts: {fpath}  类目: {facts.get('category')}")
        try:
            rep = E.create_listing(facts, submit_it=False)
            print("ASSERT_CLEAN 通过 ✓ 标题/描述已真的落值")
            print(json.dumps(rep, ensure_ascii=False))
            return 0
        except Exception as e:
            print(f"FAIL  {e}")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
