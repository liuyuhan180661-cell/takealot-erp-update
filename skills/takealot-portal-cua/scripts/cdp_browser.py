#!/usr/bin/env python3
"""给客户机起一个**带调试端口的浏览器**（CDP 驱动用；非默认 profile，不动用户的日常浏览器）。

设计要点（都是实测踩出来的）：
  · Chrome/Edge ≥136 **禁止默认 profile 开 --remote-debugging-port** → 必须用独立 user-data-dir。
  · 独立 profile 里**一次性登录卖家后台**即可长期复用（平台把登录凭据放在 localStorage 的
    `usr_st_auth` + cookie `taid`，跟 profile 走）→ 这就是「零扩展、不碰日常 Chrome」的路子。
  · 窗口**必须可见**（被遮挡/最小化时 Chrome 丢弃键盘事件）→ 想无人值守用 --headless。

用法：
  python3 cdp_browser.py --start            # 起浏览器（首次会打开登录页让你登一次）
  python3 cdp_browser.py --start --headless # 无人值守（确认已登录后再用这个）
  python3 cdp_browser.py --status           # 看端口通不通、在哪个页面、是否已登录
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

PORT = int(os.environ.get("TL_CDP_PORT") or 9222)
WORKDIR = os.path.expanduser(os.environ.get("TL_WORKDIR") or "~/.hermes/portal_cua")
PROFILE = os.path.join(WORKDIR, "chrome-profile")
LOGIN_URL = "https://sellers.takealot.com/single-product"

CANDIDATES = [
    os.environ.get("TL_BROWSER_BIN") or "",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/microsoft-edge",
]


def find_browser():
    for p in CANDIDATES:
        if p and os.path.exists(p):
            return p
    raise SystemExit("找不到 Chrome/Edge —— 用 TL_BROWSER_BIN=<可执行文件路径> 指定")


def api(path):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # 本机必须绕代理
    with opener.open(f"http://127.0.0.1:{PORT}{path}", timeout=6) as r:
        return json.load(r)


def alive():
    try:
        return api("/json/version")
    except Exception:                                    # noqa: BLE001
        return None


def start(headless=False):
    if alive():
        print(f"已有调试端口在 {PORT}（{alive().get('Browser')}）")
    else:
        exe = find_browser()
        os.makedirs(PROFILE, exist_ok=True)
        args = [exe, f"--remote-debugging-port={PORT}", f"--user-data-dir={PROFILE}",
                "--no-first-run", "--no-default-browser-check", "--remote-allow-origins=*"]
        if headless:
            args.append("--headless=new")
        args.append(LOGIN_URL)
        kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        if os.name == "nt":
            subprocess.Popen(args, creationflags=0x00000008, **kwargs)   # DETACHED_PROCESS
        else:
            subprocess.Popen(args, start_new_session=True, **kwargs)
        for _ in range(40):
            time.sleep(0.5)
            if alive():
                break
        else:
            raise SystemExit(f"浏览器起来了但 {PORT} 没响应 —— 换端口或看是否被安全软件拦")
        print(f"已启动：{exe}\n  调试端口 http://127.0.0.1:{PORT}\n  profile  {PROFILE}")
        print("  首次使用：在这个窗口里登录一次卖家后台，登录态会存在该 profile 里长期复用")
    return status()


def status():
    v = alive()
    if not v:
        print(f"CDP : 不可用（{PORT} 无响应）—— 跑 --start")
        return 1
    print(f"CDP : OK  {v.get('Browser')}  ws={v.get('webSocketDebuggerUrl', '')[:60]}…")
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        sys.path.insert(0, os.path.expanduser(os.environ.get("TL_TOOLS") or "~/.hermes/tools"))
        import tl_cdp
        c = tl_cdp.CDP()
        url = c.evaluate("location.href")
        auth = c.evaluate("!!localStorage.getItem('usr_st_auth')") if "takealot" in (url or "") else None
        print(f"页面: {url}\n可见: {c.evaluate('document.visibilityState')}"
              + (f"\n登录态 localStorage.usr_st_auth = {auth}" if auth is not None else ""))
        if auth is False:
            print("  → 还没登录：在浏览器窗口里登一次卖家后台")
    except Exception as e:                                # noqa: BLE001
        print(f"（页面信息读不到：{str(e)[:100]}）")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--headless", action="store_true")
    a = ap.parse_args()
    sys.exit(start(headless=a.headless) if a.start else status())
