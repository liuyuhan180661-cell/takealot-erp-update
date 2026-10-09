#!/usr/bin/env python3
"""交付自检（客户机可自证）：这台机器现在能不能跑 Takealot listing 引擎。

用法:
    python3 preflight.py            # 打印逐项 PASS/FAIL，最后给结论
退出码: 0 = 全部通过；非 0 = 有项失败（按提示修完再重跑）

不需要管理员权限。检查顺序 = 真正跑 listing 的准备顺序。
"""

import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bskhelp as B  # noqa: E402
import tl_engine as E  # noqa: E402

results = []


def check(name, fn, fix=""):
    try:
        detail = fn() or "ok"
        results.append((True, name, str(detail)[:110]))
        print(f"PASS  {name}: {str(detail)[:110]}", flush=True)
    except Exception as e:  # noqa: BLE001
        results.append((False, name, str(e)[:110]))
        print(f"FAIL  {name}: {str(e)[:110]}", flush=True)
        if fix:
            print(f"      → 怎么办: {fix}", flush=True)
    return results[-1][0]


def sh(args, timeout=90):
    p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    return ((p.stdout or "") + (p.stderr or "")).strip()


def main():
    print("== Takealot listing 引擎 交付自检 ==", flush=True)
    print(f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}  工作目录: {E.WORKDIR}", flush=True)

    ok = check("python3 >= 3.8", lambda: sys.version.split()[0])
    if not ok:
        print("结论: FAIL —— 装 python3 后重跑")
        return 2

    check("bsk CLI 可用", lambda: sh(["bsk", "--version"]) or "ok",
          fix="没安装 browser-skill：见技能 references/bsk-setup.md（装 CLI + 在 Chrome 里装扩展）")

    def doctor():
        out = sh(["bsk", "doctor"], timeout=120)
        bad = [l for l in out.splitlines() if l.strip().lower().startswith(("fail", "error", "warn"))]
        if bad:
            raise RuntimeError(" | ".join(bad)[:100])
        lines = [l for l in out.splitlines() if l.strip().startswith("ok")]
        return f"{len(lines)} 项 ok（守护进程 + 扩展已连）"

    check("bsk doctor", doctor, fix="按 bsk doctor 的修复提示做；最常见是 Chrome 没开或扩展没启用")

    def session():
        sid = E.start_session()
        return f"session {sid}（已写入 {os.environ.get('BSK_SID_FILE') or '/tmp/bsk_sid'}）"

    if not check("起 bsk 会话", session, fix="Chrome 打开 → 扩展图标确认已连接 → 重跑"):
        print("结论: FAIL —— 没有会话，后面都要用会话")
        return 3

    def reach_seller():
        url = ""
        for attempt in (1, 2):
            E.goto(E.NEW_LISTING_URL)
            url = E._js("location.href") or ""
            if "/login" in url or "signin" in url.lower():
                raise RuntimeError(f"未登录（当前 {url}）")
            if E._js("""!!document.querySelector('[data-sectionname="Product Category"]')"""):
                extra = "" if attempt == 1 else "（硬重置后恢复）"
                return f"新建 listing 页可用（类目面板已出现）{extra}"
            if attempt == 1:
                E.goto("about:blank")  # 同一 URL 的 SPA 不重建 → 残留状态会让面板不渲染
                time.sleep(2)
        raise RuntimeError(f"新建页没出类目面板（当前 {url}）；试过硬重置")

    login_ok = check("卖家后台登录态 + 新建页", reach_seller,
                     fix="① 在 Chrome 里手动登录 sellers.takealot.com（引擎不碰登录/密码）"
                         "② 若已登录仍不出面板：`bsk session stop --all` 后重跑本脚本"
                         "（会话退化会让页面只渲染空壳）③ 顺带把其它 Chrome 窗口关掉")

    def image_server():
        tmp = os.path.join(E.WORKDIR, "assets", "_preflight")
        os.makedirs(tmp, exist_ok=True)
        # 放一个 >2KB 的假图，让「服务是否真的在服务这个目录」的校验能通过
        with open(os.path.join(tmp, "probe.jpg"), "wb") as f:
            f.write(b"\xff\xd8\xff" + os.urandom(4096))
        try:
            E._start_cors(tmp)
            return f"本地图片服务可起（端口 {E._CORS.get('port')}）"
        finally:
            E.stop_cors()

    check("本地图片服务", image_server,
          fix="端口全被占：关掉占用 8899-8925 的程序；本机探测必须绕过系统代理（代理会让 127.0.0.1 返回 502）")

    def os_primitives():
        """OS 级剪贴板 + 真实按键（富文本写入的前提）。**不弹 GUI、不按键**，只验能力在不在。"""
        if E.IS_WIN:
            import ctypes
            if not hasattr(ctypes, "windll"):
                raise RuntimeError("ctypes.windll 不可用")
            ctypes.windll.user32.keybd_event  # 解析符号即可（不真按）
            try:
                import tkinter  # noqa: F401
                how = "tkinter"
            except Exception:
                if not shutil.which("powershell"):
                    raise RuntimeError("既没有 tkinter 也没有 powershell → 剪贴板写不进去")
                how = "powershell（无 tkinter 时的兜底）"
            return f"user32!keybd_event 可解析 + 剪贴板走 {how}（真自证要 GUI：python3 tl_engine.py --selftest-paste）"
        for tool in ("osascript", "pbcopy", "pbpaste"):
            if not shutil.which(tool):
                raise RuntimeError(f"缺 {tool}")
        E._clip_set("tl-probe")
        if "tl-probe" not in (E._clip_get() or ""):
            raise RuntimeError("剪贴板回读不一致")
        return "osascript + 剪贴板可用（真自证要 GUI：python3 tl_engine.py --selftest-paste）"

    check("兜底原语（可选：OS 粘贴 / 真实按键）", os_primitives,
          fix="macOS：终端要在 系统设置→隐私与安全性→辅助功能 里授权；Windows：确保在交互桌面会话里（远程桌面/计划任务会失败）")

    passed = sum(1 for ok_, _, _ in results if ok_)
    print(f"\n== 结论: {passed}/{len(results)} 项通过 ==", flush=True)
    if login_ok:
        print("可以开始：python3 discover_fields.py \"类目1\" \"类目2\" \"叶子\"  →  python3 create_listing.py facts_xxx.json")
        return 0
    print("先解决上面 FAIL 项（都是环境问题，不需要改脚本）")
    return 1


if __name__ == "__main__":
    sys.exit(main())
