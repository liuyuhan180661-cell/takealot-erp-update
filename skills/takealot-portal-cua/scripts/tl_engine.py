"""Takealot 卖家后台 listing 引擎（A 自编辑 / B 拆解重塑 共用）。

只做「已被实测验证」的动作；任何一步失败即抛错停止（断言式，不猜、不重试掩盖）。
验证记录见技能 takealot-portal-cua。

依赖：bsk（browser-skill）+ 本目录 cors_http.py（图片上传用本地 CORS 服务）。
"""

import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bskhelp as B  # noqa: E402

NEW_LISTING_URL = "https://sellers.takealot.com/single-product"
SUBMISSIONS_URL = "https://sellers.takealot.com/catalogue/submissions"
WORKDIR = os.path.expanduser(os.environ.get("TL_WORKDIR") or "~/.hermes/portal_cua")
IMG_PORT = 8899


class StepError(RuntimeError):
    pass


def log(msg):
    print(f"[engine] {msg}", flush=True)


# ---------------------------------------------------------------- session / nav
def start_session(browser=None):
    """起一个 bsk 会话，并把 SID 写到 bskhelp 会读的文件里。

    客户机不需要知道 instance id：`bsk session start` 直接对着唯一连上的浏览器起会话
    （多浏览器时才需要 --browser，用 `bsk browsers` 看）。
    """
    args = ["bsk", "session", "start"]
    if browser:
        args += ["--browser", browser]
    out = subprocess.run(args, capture_output=True, text=True).stdout.strip().splitlines()
    sid = out[-1].strip() if out else ""
    if not sid or len(sid) > 12 or " " in sid:
        raise StepError(f"session start failed: {out} —— 先跑 doctor：bsk doctor（看扩展是否连上）")
    with open(os.environ.get("BSK_SID_FILE") or "/tmp/bsk_sid", "w") as f:
        f.write(sid)
    log(f"session {sid}")
    return sid


def goto(url):
    B.bsk("navigate", url)
    time.sleep(3)


def open_new_listing(timeout=60):
    goto(NEW_LISTING_URL)
    _t("  · goto 新建页")
    # 坑（客户机口径复跑时实测）：bsk navigate 到**同一个 URL** 时 SPA 不重建，上一轮的类目树/已选层级
    # 还在 DOM 里 —— 这时再点那一级等于**反选**，面板 Next 一直 disabled，后面 0 字段。
    # 处理：先确认在干净起点；否则 about:blank 跳一下再回来（真正的文档级重载，比 location.reload 稳）。
    clean = _js("""(()=>{const s=document.querySelector('[data-sectionname="Product Category"]');
if(!s) return false;return /Please make a selection/i.test(s.innerText||'');})()""")
    if not clean:
        log("wizard 有上一轮残留状态 → 硬重置（about:blank → 新建页）")
        goto("about:blank")
        goto(NEW_LISTING_URL)
        time.sleep(1)
        _t("  · 硬重置（about:blank + goto）")
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _js("""!!document.querySelector('[data-sectionname="Product Category"]')"""):
            _t("  · 等类目面板")
            return
        time.sleep(0.4)
    raise StepError(f"new-listing page not loaded (url={_js('location.href')})")


def _candidates(raw):
    out = []
    lines = [l.strip() for l in raw.split("\n") if l.strip()]
    if lines:
        out.append(lines[-1])
    m = re.search(r"(\{.*\}|\[.*\])", raw, re.S)
    if m:
        out.append(m.group(1))
    out.append(raw.strip())
    return out


def _js(expr):
    """Evaluate JS returning a scalar; returns Python value (or None)."""
    for cand in _candidates(B.bsk("evaluate", f"(()=>{{return JSON.stringify({expr});}})()").strip()):
        try:
            return json.loads(cand)
        except Exception:
            continue
    return None


def _js_json(expr):
    for cand in _candidates(B.bsk("evaluate", f"(()=>{{return JSON.stringify({expr});}})()").strip()):
        try:
            v = json.loads(cand)
            if isinstance(v, (dict, list)):
                return v
        except Exception:
            continue
    raise StepError(f"js returned no json for: {expr[:80]}")


def _click_ref(ref, what=""):
    out = B.bsk("click", ref)
    if "ok" not in out:
        raise StepError(f"click {ref} ({what}) failed: {out.strip()[-120:]}")
    time.sleep(1.1)


def _find_ref(pred, what):
    for line in B.observe().split("\n"):
        if pred(line):
            m = re.search(r"@e\d+", line)
            if m:
                return m.group(0)
    raise StepError(f"no element found for {what}")


# ---------------------------------------------------------------- category
def _wait(js_cond, timeout, interval=0.3):
    """轮询 DOM 条件（比固定 sleep 快得多，也比重试掩盖问题诚实）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if _js(js_cond):
                return True
        except Exception:
            pass
        time.sleep(interval)
    return False


_HYD = ('(()=>{const el=(%s); if(!el) return false;'
        'return Object.keys(el).some(k=>k.startsWith("__reactProps$"));})()')


def _js_click(expr, ready=None, timeout=6.0, settle=0.2):
    """JS 原生 click（实测 ~0.1s/次；bsk 真点击要 10s+）。

    向导里的按钮/选项都是普通 React 按钮，合成点击能触发 onClick（已实测：3 级类目 + 2 次 Next
    生效，字段 0→27）。**写入类控件不适用**（Draft 富文本仍需 OS 级粘贴，见 fill_rich）。

    必须先等 React **hydrate 完**：刚加载完时 DOM 有了但事件还没挂，`el.click()` 是空操作
    （实测踩到：类目点了没反应 → 白等超时后走 bsk 慢路）。判定 hydrate=元素上出现 `__reactProps$…`。
    """
    if not _js(_HYD % expr) and not _wait(_HYD % expr, 10):
        return False
    hit = _js(f"(()=>{{const el=({expr}); if(!el) return false; el.click(); return true;}})()")
    if not hit:
        return False
    time.sleep(settle)
    return True if not ready else _wait(ready, timeout)


def _fast_click(expr, what, ready=None, timeout=12.0, js_first=True):
    """快路（JS click）→ 慢路（打标记 + bsk 真点击）。两边都带就绪断言。

    `js_first=False` 直接用 bsk 真点击：**末级类目**必须这样——实测叶子节点用 JS click
    点不生效（Next 永远不 enable），而 bsk 真点击带内置的稳定性等待，能选中。
    """
    if js_first and _js_click(expr, ready, min(timeout, 6.0)):
        log(f"click·js {what}")
        return True
    tag = "tl%d" % (int(time.time() * 1000) % 1000000)
    got = _js(f"(()=>{{const el=({expr});if(!el)return '';el.setAttribute('data-tl-tag','{tag}');return '{tag}';}})()")
    if got == tag and B.bsk("click", f'[data-tl-tag="{tag}"]'):
        log(f"click·bsk {what}")
        if not ready or _wait(ready, timeout):
            return True
    return False


def _cat_expr(name):
    """在产品类目面板里找某一级选项。

    实测（2026-09-26）：选项是 `div.ZorkMillerColumns__item` 渲染的（面板里 button/a/li 只有
    3 个），且 Miller 列**保留多列** —— 同名项在旧列里也有。按"最短文本"挑会挑到不可见/旧列的
    节点，点下去 UI 看着变了、应用状态其实没提交（控制台 `undefined category`）。
    所以：① 只认**可见**元素 ② 优先 `[class*="MillerColumns__item"]` ③ 再取最短文本。
    """
    js = r"""
(() => {
  const P = document.querySelector('[data-sectionname="Product Category"]');
  if (!P) return null;
  const want = __WANT__;
  const vis = (e) => {
    if (!e || e.offsetParent === null) return false;
    const r = e.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  let best = null, bl = 1e9;
  const scan = (sel, needVis) => {
    for (const e of P.querySelectorAll(sel)) {
      if (needVis && !vis(e)) continue;
      let t = (e.innerText || '').trim().toLowerCase().replace(/\s*>\s*$/, '');
      if (!t || t.length > 120 || !t.includes(want)) continue;
      if (t.length < bl) { bl = t.length; best = e; }
    }
  };
  scan('[class*="MillerColumns__item"]', true);
  if (!best) scan('[class*="MillerColumns__item"]', false);
  if (!best) scan('button,a,li,div[role="button"]', true);
  if (!best) scan('span,div', true);
  return best;
})()
"""
    return js.replace("__WANT__", json.dumps(name.strip().lower()))


def _section_next_expr(section_name):
    """某个分区里的 Next 按钮（JS 定位 + 滚到视口中央）。"""
    js = r"""
(() => {
  const s = document.querySelector('[data-sectionname="__SEC__"]');
  if (!s) return null;
  const b = [...s.querySelectorAll('button')].find(x => /^Next$/i.test((x.textContent || '').trim()));
  if (!b) return null;
  b.scrollIntoView({block: 'center'});
  return b;
})()
"""
    return js.replace("__SEC__", section_name)


# 就绪信号（实测）：末级类目点完 → Next 从 disabled 变 enabled；点 Next → 属性字段 0→27。
# 注意 `[data-sectionname]` 六个分区**一直存在**，不能当就绪信号。
_NEXT_EXPR = ('(()=>{const b=[...document.querySelectorAll("button")]'
              '.find(b=>/^Next$/i.test((b.innerText||"").trim())&&!b.disabled);return b||null;})()')
_FIELDS_EXPR = 'document.querySelectorAll("[data-fieldid]").length > 0'
_PANEL_TEXT = ('(()=>{const P=document.querySelector(\'[data-sectionname="Product Category"]\');'
               'return P?(P.innerText||""):"";})()')


def _panel_text():
    return _js(_PANEL_TEXT) or ""


def _wait_change(fn, before, timeout=8.0):
    """等 fn() 的结果发生变化——用来判定「刚才那次点击真的生效了」。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if fn() != before:
            return True
        time.sleep(0.25)
    return False


def _wait_quiet(fn, stable=0.5, timeout=15.0):
    """等 fn() 连续 stable 秒不再变化（UI 停下来了）。

    实测必要性：类目点完面板会先变成“加载中”，此时立刻点下一级会点在骨架/旧节点上
    （点了等于没点，Next 永远不 enable）。bsk 真点击慢就是因为内置了这种稳定性等待。
    """
    prev = fn()
    t0 = last = time.time()
    while time.time() - t0 < timeout:
        time.sleep(0.2)
        cur = fn()
        if cur != prev:
            prev = cur
            last = time.time()
        elif time.time() - last >= stable:
            return True
    return False


def _restart_session():
    """会话退化自愈：`bsk session stop --all` → 重起会话。

    实测（2026-09-26）：退化时类目选了但属性全渲染成 "Unknown field"、字段数 0，
    重启会话后立刻恢复（27 字段 + 正常标签）。这条比在坏状态里继续填值诚实得多。
    """
    try:
        B.bsk("session", "stop", "--all")
    except Exception:
        pass
    time.sleep(2.5)
    start_session()
    log("已重启 bsk 会话（退化自愈）")


def ensure_attributes(facts, tries=3):
    """类目选完必须看到字段。

    排查顺序（2026-09-26 修正：过去一律归因"会话退化"，其实是**类目没点中**）：
    ① 字段没出现 → 先重做类目（pick_category 自带 hydrate 门 + 未提交就硬重置重试）
    ② 重做仍不行 → 才怀疑会话退化：`bsk session stop --all` 重启会话再来
    """
    for i in range(tries):
        if _wait(_FIELDS_EXPR, 6):
            return True
        if i == tries - 1:
            break
        if i == 0:
            log("类目选完但字段数=0 → 先重做类目（含 hydrate 等待 + 提交校验）")
            open_new_listing()
            pick_category(facts["category"])
        else:
            log("重做类目仍 0 字段 → 怀疑会话退化：重启会话 + 重做")
            _restart_session()
            open_new_listing()
            pick_category(facts["category"])
    raise StepError("类目/属性没渲染出来：已重做类目 + 重启会话都没救回；人工看一眼页面")


def pick_category(levels, max_levels=3):
    """类目 → 变体确认。**JS 点击可见选项**是默认路径。

    2026-09-26 定版（带实测证据）：
    - ✅ 三级 JS 点击 + JS 点类目区「Next」→ 属性字段 **0→27**（Brand/Cable Type 等全部渲染）。
    - ❌ bsk/AX-ref 点击这条路**看着成功、其实没提交**：面板列会变、Next 也会变可用，但应用
      内部状态里没有类目（控制台 `undefined category`）→ 属性全渲染成 "Unknown field"、字段 0。
      所以老路（`_pick_category_legacy`）只当兜底。
    - 提交成功的**唯一判据 = 字段真的出现**（`_FIELDS_EXPR`），不是「点完了」。
    """
    lv = list(levels[:max_levels])
    t0 = time.time()
    clicked = False
    ok = _wait(_HYD % _cat_expr(lv[0]), 25)        # hydrate 门（不等就是空操作）
    if ok:
        for i, name in enumerate(lv):
            last = (i + 1 == len(lv))
            _wait_quiet(_panel_text, 0.5, 10)      # 等上一列渲染停下来再点
            before = _panel_text()
            if not _fast_click(_cat_expr(name), f"category level {i+1} '{name}'",
                               None, timeout=8, js_first=True):
                ok = False
                break
            clicked = True
            if not last and not _wait_change(_panel_text, before, 8):
                log(f"level {i+1} 点了但面板没变 → 重找元素再点一次")
                before = _panel_text()
                if not (_fast_click(_cat_expr(name), f"category level {i+1} '{name}' (retry)",
                                    None, timeout=8, js_first=True)
                        and _wait_change(_panel_text, before, 8)):
                    ok = False
                    break
            picked = _js("((%s).innerText||'').trim().slice(0,60)" % _cat_expr(name)) or "?"
            log(f"category level {i+1}: {name}  ← 点中 {picked!r}")
            time.sleep(0.2)
    # 注意：**不要**用「Next 可用」当门（实测：手动点的时候 Next 还是 disabled，但点下去
    # 照样推进、字段照样出来）。唯一判据就是字段有没有出现。
    if ok:
        _fast_click(_section_next_expr("Product Category"), "category Next",
                    None, timeout=8, js_first=True)
        if not _wait(_FIELDS_EXPR, 30):
            log("类目 Next 后字段没出现 → 试变体区 Next")
            _fast_click(_section_next_expr("Product Variants"), "variants Next",
                        None, timeout=8, js_first=True)
            if not _wait(_FIELDS_EXPR, 20):
                log("再点一次类目区 Next（有些类目要点两下才推进）")
                _fast_click(_section_next_expr("Product Category"), "category Next#2",
                            None, timeout=8, js_first=True)
                ok = _wait(_FIELDS_EXPR, 20)
        else:
            _fast_click(_section_next_expr("Product Variants"), "variants Next",
                        None, timeout=6, js_first=True)
    if ok:
        log(f"category + variants committed（JS 快路 {time.time()-t0:.1f}s，字段已出现）")
        return
    if clicked:
        log("回退前硬重置（避免半选状态）")
        open_new_listing()
    log(f"类目 JS 快路未成功（{time.time()-t0:.1f}s）→ 走 observe+ref 老路")
def _pick_category_legacy(levels, max_levels=3):
    """levels: ['Consumer Electronics','Electronic Accessories','Backpacks']

    返回 True = 点完且**字段真的出现了**（类目确实提交）；False = 没提交。

    实测（2026-09-26 连续复现）：`open_new_listing` 后 React 还没 hydrate 时点击就是
    **空操作** —— 日志会打 "category + variants committed" 但面包屑其实只到第一级、
    叶子列还整列摆着，于是面板永远 0 字段。所以这里必须先等 hydrate，且**必须用
    「字段出现」当提交成功的判据**，不能只记录"点过"。
    """
    _wait(_HYD % _cat_expr(levels[0]), 25)      # hydrate 门（不加这句 = 点击空操作）
    for i, name in enumerate(levels[:max_levels]):
        try:
            ref = _find_ref(lambda l, n=name: "button" in l and n.lower() in l.lower(),
                            f"category level {i+1} '{name}'")
        except StepError:
            # 这一级已经在向导里选中（复跑同一 URL 时常见）→ 跳过，不要报错
            shown = _js("""(()=>{const s=document.querySelector('[data-sectionname="Product Category"]');
return s?(s.innerText||'').replace(/\\s+/g,' ').slice(0,300):'';})()""") or ""
            if name.lower() in shown.lower():
                log(f"category level {i+1}: {name}（向导里已选中，跳过）")
                continue
            raise
        try:
            _click_ref(ref, f"category {name}")
        except StepError as e:
            if "renderer" in str(e).lower():
                log("renderer not ready → reload & retry")
                open_new_listing()
                ref = _find_ref(lambda l, n=name: "button" in l and n.lower() in l.lower(),
                                f"category level {i+1} '{name}' (retry)")
                _click_ref(ref, f"category {name} (retry)")
            else:
                raise
        log(f"category level {i+1}: {name}")
    # panel Next (Product Category) then variants Next
    _click_ref(_find_ref(lambda l: 'button "Next"' in l and "Product Category" in l,
                         "category Next"), "category Next")
    _click_ref(_find_ref(lambda l: 'button "Next"' in l and "to consolidate products" in l,
                         "variants Next"), "variants Next")
    if _wait(_FIELDS_EXPR, 30):
        log("category + variants committed（字段已出现，确认真提交）")
        return True
    log("类目点完但 30s 内字段仍未出现 → 判定**未提交**（不是会话退化）")
    return False


# ---------------------------------------------------------------- fields
def _reveal(sel):
    """只滚动定位，不点击。

    实测教训：bsk 会在页面里插一个 `<browser-skill-overlay>`，它盖住了整页 ——
    OS 级点击会被它吃掉，而且 bsk click 落到不可见元素时会把点击丢到固定底栏
    （等于误点 Save and Close）。所以定位靠 scrollIntoView，写入靠 CDP fill / OS 粘贴。
    """
    info = _js(f"""(()=>{{const el=document.querySelector('{sel}');
if(!el) return null; el.scrollIntoView({{block:'center'}}); const r=el.getBoundingClientRect();
return {{y:Math.round(r.top+r.height/2), winX:window.screenX, winY:window.screenY,
 chromeH:window.outerHeight-window.innerHeight, vis:(r.top>=0 && r.bottom<=window.innerHeight)}};}})()""")
    time.sleep(0.6)
    if not isinstance(info, dict):
        raise StepError(f"element not found: {sel}")
    return info


# ---------------------------------------------------------------- OS 原语（跨平台）
# 富文本（Draft.js）只认「真实 OS 剪贴板粘贴」。macOS 用 pbcopy + System Events ⌘V；
# Windows 用 PowerShell 剪贴板 + keybd_event（Ctrl+V）。两边都靠**读回断言**判定成败。
IS_WIN = sys.platform.startswith("win")
_tk_root = None  # Windows 剪贴板用的常驻隐藏 Tk root（见 _win_clip）
_RAISE_N = [0]    # _raise_window 的候选窗口轮换下标
_T0 = time.time()   # 计时基准（见 _t）
_TPREV = _T0


def _ps(script, timeout=60, env=None):
    """跑一段 PowerShell（Windows 上所有 OS 级动作都走它）。

    用 -EncodedCommand（UTF-16LE base64）传脚本：引号/中文/换行都不会被 shell 吃掉。
    """
    import base64
    enc = base64.b64encode(script.encode("utf-16-le")).decode()
    return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", enc],
                          capture_output=True, text=True, timeout=timeout, env=env)


def _win_clip(text=None):
    """Windows 剪贴板：tkinter（stdlib）优先，没有 tkinter 才退回 PowerShell。

    - 隐藏的 Tk root 必须**常驻**（模块级 _tk_root）：Windows 上剪贴板归窗口所有，
      root 销毁后内容会丢。
    - text=None → 读；给 text → 写。
    """
    global _tk_root
    try:
        import tkinter
    except Exception:
        import base64
        if text is None:
            return _ps("Get-Clipboard -Raw").stdout or ""
        b64 = base64.b64encode(text.encode("utf-16-le")).decode()
        _ps(f'$t=[Text.Encoding]::Unicode.GetString([Convert]::FromBase64String("{b64}")); Set-Clipboard -Value $t')
        return ""
    if _tk_root is None:
        _tk_root = tkinter.Tk()
        _tk_root.withdraw()
    if text is None:
        try:
            return str(_tk_root.clipboard_get())
        except Exception:
            return ""
    _tk_root.clipboard_clear()
    _tk_root.clipboard_append(text)
    _tk_root.update()
    return ""


def _clip_get():
    if IS_WIN:
        return _win_clip() or ""
    return subprocess.run(["pbpaste"], capture_output=True, text=True).stdout


def _clip_set(text):
    if IS_WIN:
        _win_clip(text)
        return
    subprocess.run(["pbcopy"], input=text.encode(), capture_output=True)


def _key(combo):
    """发一个真实按键组合：'select_all' | 'copy' | 'paste'。

    macOS：System Events keystroke（需要目标窗口在前台）。
    Windows：user32!keybd_event（ctypes 直调；不用 SendKeys/PowerShell——少一层语法与执行策略风险）。
    """
    if IS_WIN:
        u = _u32()
        if combo == "delete":
            u.keybd_event(0x2E, 0, 0, 0)   # VK_DELETE
            u.keybd_event(0x2E, 0, 2, 0)
            return
        vk = {"select_all": 0x41, "copy": 0x43, "paste": 0x56}[combo]  # A / C / V
        u.keybd_event(0x11, 0, 0, 0)   # Ctrl down
        u.keybd_event(vk, 0, 0, 0)
        u.keybd_event(vk, 0, 2, 0)     # key up
        u.keybd_event(0x11, 0, 2, 0)   # Ctrl up
        return
    if combo == "delete":
        _osa('tell application "System Events" to key code 51')
        return
    mac = {"select_all": "a", "copy": "c", "paste": "v"}[combo]
    _osa(f'tell application "System Events" to keystroke "{mac}" using command down')


def os_paste(sel, text):
    """OS 级真实粘贴（可信的 paste 事件）—— 富文本字段最稳的写入方式。

    实测：
    - title（ZorkAutoBuildTitleField）拒绝 CDP 注入 → 只有这条路
    - 逐字 OS 键入会被 IME/掉字污染（" Backpack" 变成 "Baa'ckpack"）→ 不要用键入
    - 一次 pbcopy + 真实 Cmd+V 可以带空格、连字符、多段换行
    """
    info = _reveal(sel)
    if not info.get("vis"):
        raise StepError(f"os_paste: {sel} not in viewport")
    _raise_window(info["winX"], info["winY"])
    focused = False
    for attempt in range(3):
        focused = _js(f"""(()=>{{const el=document.querySelector('{sel}');if(!el) return false; el.focus();
return document.activeElement===el || el.contains(document.activeElement);}})()""")
        if focused:
            break
        _raise_window(info["winX"], info["winY"])
    if not focused:
        raise StepError(f"os_paste: could not focus {sel}")

    norm = lambda s: re.sub(r"\s+", " ", (s or "")).strip()
    prev_clip = _clip_get()
    _clip_set(text)
    got = ""
    try:
        for attempt in range(4):
            if attempt:
                # 第一次没进去，多半是焦点被别的 App/窗口抢了 → 重新前台化再试
                _raise_window(info["winX"], info["winY"])
                _js(f"""(()=>{{const el=document.querySelector('{sel}');if(el)el.focus();return !!el;}})()""")
                time.sleep(0.4)
            _key("select_all")
            time.sleep(0.3)
            _key("paste")
            time.sleep(1.4)
            got = _js(f"""(()=>{{const el=document.querySelector('{sel}');return el?el.innerText:'';}})()""") or ""
            if norm(got) == norm(text):
                return True
        raise StepError(f"os_paste mismatch: wanted {len(norm(text))} got {len(norm(got))} chars")
    finally:
        _clip_set(prev_clip)


def fill_text(fieldid, value):
    for suffix in ("input", "textarea"):
        sel = f'[data-fieldid="{fieldid}"] {suffix}'
        # 刚点完类目时字段是分批挂载的 → 等它出现，别立刻判死（实测踩到 hydration 竞争）
        if not _js(f"!!document.querySelector('{sel}')") and not _wait(f"!!document.querySelector('{sel}')", 6):
            continue
        _reveal(sel)
        B.bsk("focus", sel)
        B.bsk("fill", sel, "--value", str(value))
        time.sleep(0.5)
        got = _js(f"""(()=>{{const el=document.querySelector('{sel}');return el?el.value:null;}})()""")
        if str(got).strip() in ("", "None") and str(value).strip():
            raise StepError(f"fill {fieldid} ({suffix}) read back empty")
        return True
    n_fields = _js('document.querySelectorAll("[data-fieldid]").length')
    has_box = _js(f"""!!document.querySelector('[data-fieldid=\"{fieldid}\"]')""")
    raise StepError(f"fill {fieldid}: no input/textarea found"
                    f"（该 fieldid 容器存在={has_box}，页面上字段总数={n_fields}）")


def _osa(script):
    return subprocess.run(["osascript", "-e", script], capture_output=True, text=True).stdout.strip()


def _u32():
    """Windows user32（ctypes 直调；macOS 上不存在，只在 IS_WIN 分支被调用）。"""
    import ctypes
    return ctypes.windll.user32


def _raise_window_win(title_hint="Seller Portal"):
    """Windows：把标题含 hint（或 takealot）的窗口提到最前。

    EnumWindows 遍历 → GetWindowTextW 取标题 → 匹配就 SW_RESTORE + BringWindowToTop +
    SetForegroundWindow。比按进程名猜窗口稳（一个 Chrome 进程可能挂多个窗口）。
    """
    import ctypes
    from ctypes import wintypes
    u = _u32()
    hits = []
    try:
        CB = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)  # Windows 专有
    except Exception as e:
        return f"err:WINFUNCTYPE {e}"

    def _cb(hwnd, _lparam):
        n = u.GetWindowTextLengthW(hwnd)
        if n:
            buf = ctypes.create_unicode_buffer(n + 1)
            u.GetWindowTextW(hwnd, buf, n + 1)
            t = buf.value
            if t and (title_hint in t or "takealot" in t.lower()):
                hits.append((hwnd, t))
        return True

    try:
        u.EnumWindows(CB(_cb), 0)
        for hwnd, _t in hits:
            u.ShowWindow(hwnd, 9)          # SW_RESTORE（最小化/隐藏都能拉回来）
            u.BringWindowToTop(hwnd)
            u.SetForegroundWindow(hwnd)
    except Exception as e:
        return f"err:{e}"                  # 抬窗口失败不致命：os_paste 会靠读回断言判定
    return str(len(hits))


def _raise_window(x=None, y=None, title_hint="Seller Portal", width=1512, height=900):
    """前台化 bsk 的 Agent Window（富文本 OS 粘贴的前提）。

    macOS（实测真因 2026-09-26，四条写入路全部读回 0 字符）：
    - Chrome 的 **AppleScript 字典看不到 Agent Window**（只列得出扩展 popup），
      按 position 匹配 / `activate` 都会失手 → ⌘V 落到别的窗口。
    - System Events(AX) 能看到，但可能有**多个同名窗口**（用户的 Seller Portal 窗口 1200 宽 vs
      Agent Window 1512 宽）→ 盲 raise 会提到错的那个。
    做法：① `bsk window resize` 把 Agent Window 定到**特征尺寸** ② AX 里按**宽度**精确定位并 AXRaise。
    ⇒ 前提是环境干净（其它同名 Chrome 窗口关掉），见 references/pitfalls.md G3。

    Windows：按窗口标题（MainWindowTitle 含 hint / takealot）找 chrome 窗口 →
    ShowWindow(SW_RESTORE) + BringWindowToTop + SetForegroundWindow。
    """
    if os.environ.get("TL_RESIZE"):
        # 默认**不**动窗口尺寸：实测加了这个 resize 之后 ⌘V 就再也落不进 agent 窗口了
        # （窗口被重设尺寸/状态后，OS 焦点路由不再指向它）。只有在明确需要时用 TL_RESIZE=1 打开。
        try:
            B.bsk("window", "resize", "--width", str(width), "--height", str(height))
            time.sleep(0.6)
        except Exception:
            pass
    if IS_WIN:
        return _raise_window_win(title_hint)
    # ① Chrome 的 AppleScript 字典：**按 agent 标签当前 URL 精确匹配**那个窗口（活动标签不是 agent 标签时，
    #    即使窗口置前 ⌘V 也会落到别的文档里——实测踩过）。匹配不到才退回"含 takealot 的窗口"。
    #    多个候选时**轮换**（每次调用换下一个），配合 os_paste 的读回断言，等于用实验找出对的那个窗口。
    url = _js("location.href") or ""
    _RAISE_N[0] = _RAISE_N[0] % 8 + 1
    hit = _osa(f'''tell application "Google Chrome"
set target to "{url}"
set hits to {{}}
if target is not "" then
  repeat with i from 1 to (count windows)
    try
      if (URL of active tab of window i) is target then set end of hits to i
    end try
  end repeat
end if
if (count of hits) = 0 then
  repeat with i from 1 to (count windows)
    try
      if (URL of active tab of window i) contains "takealot.com" then set end of hits to i
    end try
  end repeat
end if
if (count of hits) = 0 then return 0
set idx to (item (({_RAISE_N[0]} - 1) mod (count of hits) + 1) of hits)
set index of window idx to 1
activate
return (count of hits)
end tell''')
    if str(hit).strip().isdigit() and int(str(hit).strip() or 0) > 0:
        time.sleep(0.9)
        return hit
    _osa('tell application "Google Chrome" to activate')
    hit = _osa(f'''tell application "System Events"
set raised to 0
repeat with p in (every process whose name contains "Chrome")
  repeat with w in (windows of p)
    try
      set sz to size of w
      if (item 1 of sz) > {int(width) - 4} and (item 1 of sz) < {int(width) + 4} then
        perform action "AXRaise" of w
        set frontmost of p to true
        set raised to raised + 1
      end if
    end try
  end repeat
end repeat
return raised
end tell''')
    if not hit.strip().isdigit() or int(hit.strip() or 0) == 0:
        # 兜底 1：按窗口名
        hit = _osa(f'''tell application "System Events"
set raised to 0
repeat with p in (every process whose name contains "Chrome")
  repeat with w in (windows of p)
    try
      if (name of w) contains "{title_hint}" then
        perform action "AXRaise" of w
        set frontmost of p to true
        set raised to raised + 1
      end if
    end try
  end repeat
end repeat
return raised
end tell''')
    if x is not None and y is not None and (not str(hit).strip().isdigit() or int(str(hit).strip() or 0) == 0):
        # 兜底 2：老的位置匹配
        _osa(f'''tell application "System Events" to tell process "Google Chrome"
repeat with w in windows
  set p to position of w
  if (item 1 of p) is {int(x)} and (item 2 of p) is {int(y)} then perform action "AXRaise" of w
end repeat
end tell''')
    time.sleep(0.9)
    return hit


def _click_screen(x, y):
    if IS_WIN:
        _ps(f'''Add-Type -TypeDefinition @"
using System; using System.Runtime.InteropServices;
public class M {{
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, UIntPtr e);
}}
"@
[M]::SetCursorPos({int(x)},{int(y)}); [M]::mouse_event(0x0002,0,0,0,[UIntPtr]::Zero); [M]::mouse_event(0x0004,0,0,0,[UIntPtr]::Zero)''')
        return
    subprocess.run(["/usr/local/bin/cliclick", f"c:{x},{y}"])


def selftest_paste(hint=None):
    """验证「OS 剪贴板 + 真实按键」原语（不依赖卖家后台）——客户机可自证的一条命令。

    做法：打开一个纯文本编辑器（macOS TextEdit / Windows 记事本）→ 粘一段标记文本 →
    全选复制回读比对。PASS 说明富文本写入的底层能力在本机可用。
    """
    hint = hint or ("Notepad" if IS_WIN else "TextEdit")
    marker = "TL-PASTE-OK-%d" % int(time.time())
    was_running = False
    try:
        if IS_WIN:
            was_running = bool(subprocess.run(["tasklist", "/FI", "IMAGENAME eq notepad.exe"],
                                              capture_output=True, text=True).stdout.lower().count("notepad.exe"))
        else:
            was_running = "TextEdit" in subprocess.run(["pgrep", "-x", "TextEdit"],
                                                       capture_output=True, text=True).stdout
    except Exception:
        pass
    if IS_WIN:
        subprocess.Popen(["notepad.exe"])
    else:
        subprocess.Popen(["open", "-a", "TextEdit"])
    time.sleep(4)
    if IS_WIN:
        raised = _raise_window_win(hint)
    else:
        _osa(f'tell application "{hint}" to activate')
        raised = hint
    time.sleep(1.2)
    prev = _clip_get()
    got = ""
    try:
        _clip_set(marker)
        time.sleep(0.5)
        _key("paste")
        time.sleep(1.4)
        _key("select_all")
        time.sleep(0.4)
        _key("copy")
        time.sleep(1.0)
        got = (_clip_get() or "").strip()
    finally:
        _clip_set(prev)
        if not was_running:
            if IS_WIN:
                subprocess.run(["taskkill", "/IM", "notepad.exe", "/F"], capture_output=True)
            else:
                _osa('tell application "TextEdit" to quit saving no')
    ok = got == marker
    print(f"[selftest] platform={'win' if IS_WIN else 'mac'} raised={raised} "
          f"expect={marker!r} got={got[:60]!r} -> {'PASS' if ok else 'FAIL'}")
    if not ok:
        print("  → 排查：目标编辑器是否真在前台（被遮挡/最小化会失败）、"
              "macOS 是否给了终端 辅助功能 权限、Windows 是否在受控桌面/远程会话里")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest-paste" in sys.argv:
        sys.exit(selftest_paste())
    print("tl_engine 是库，不是命令。用法：python3 create_listing.py <facts.json>"
          "；自检 OS 粘贴原语：python3 tl_engine.py --selftest-paste")
    sys.exit(0)


def os_type(sel, text):
    """真实 OS 级输入：Draft 的 AutoBuild 标题（以及任何拒绝 CDP 注入的控件）只能这么写。

    依赖：Chrome 窗口必须能前台化（Agent 窗口）；会短暂抢占用户焦点。
    支持多段文本（\n → Return），这是 bsk fill 做不到的。
    """
    info = _js(f"""(()=>{{const el=document.querySelector('{sel}');if(!el) return null;
el.scrollIntoView({{block:'center'}}); const r=el.getBoundingClientRect();
return {{cx:Math.round(r.left+r.width/2), cy:Math.round(r.top+r.height/2),
 chromeH:window.outerHeight-window.innerHeight, winX:window.screenX, winY:window.screenY, vis:(r.top>=0&&r.bottom<=window.innerHeight)}};}})()""")
    if not isinstance(info, dict):
        raise StepError(f"os_type: element not found {sel}")
    if not info.get("vis"):
        raise StepError(f"os_type: element not in viewport {sel}")
    _raise_window(info["winX"], info["winY"])
    focused = False
    for attempt in range(3):
        focused = _js(f"""(()=>{{const el=document.querySelector('{sel}');if(!el) return false; el.focus();
return document.activeElement===el || el.contains(document.activeElement);}})()""")
        if focused:
            break
        _raise_window(info["winX"], info["winY"])
    if not focused:
        active = _js("""(()=>{const a=document.activeElement;return a? (a.tagName+'.'+(a.className||'').slice(0,20)) : 'none';})()""")
        raise StepError(f"os_type: could not focus {sel} (active={active})")
    if IS_WIN:
        # Windows：清空 → 整段粘贴（比逐字 keybd_event 稳，天然支持多段/中文/特殊字符）
        _key("select_all")
        time.sleep(0.2)
        _key("delete")
        time.sleep(0.3)
        _clip_set(text)
        time.sleep(0.3)
        _key("paste")
        time.sleep(1.2)
        got_w = _js(f"""(()=>{{const el=document.querySelector('{sel}');return el?el.innerText:'';}})()""") or ""
        if re.sub(r"\s+", " ", got_w).strip() != re.sub(r"\s+", " ", text).strip():
            raise StepError(f"os_type(win) mismatch: wanted {len(text)} got {len(got_w)} chars")
        return True
    _osa('tell application "System Events" to keystroke "a" using command down')
    time.sleep(0.2)
    _osa('tell application "System Events" to key code 51')  # delete selection
    time.sleep(0.3)
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line:
            esc = line.replace("\\", "\\\\").replace('"', '\\"')
            _osa(f'tell application "System Events" to keystroke "{esc}"')
        if i < len(lines) - 1:
            _osa('tell application "System Events" to key code 36')  # Return
        time.sleep(0.15)
    time.sleep(1.0)
    got = _js(f"""(()=>{{const el=document.querySelector('{sel}');return el?el.innerText:'';}})()""")
    norm = lambda s: re.sub(r"\s+", " ", (s or "")).strip()

    def blocks():
        raw = _js(f"""(()=>{{const el=document.querySelector('{sel}');return el?el.innerText:'';}})()""") or ""
        return [b for b in raw.split("\n")]

    def send(chunk):
        esc = chunk.replace("\\", "\\\\").replace('"', '\\"')
        _osa(f'tell application "System Events" to keystroke "{esc}"')

    def clear_all():
        _osa('tell application "System Events" to keystroke "a" using command down')
        time.sleep(0.15)
        _osa('tell application "System Events" to key code 51')
        time.sleep(0.35)

    segs = text.split("\n")
    for si, seg in enumerate(segs):
        want_seg = seg.strip()
        ok = False
        for attempt in range(8):
            bl = blocks()
            cur = (bl[si] if si < len(bl) else "").strip()
            if cur == want_seg:
                ok = True
                break
            if not want_seg.startswith(cur):
                for _ in range(3):
                    clear_all()
                    bl2 = blocks()
                    if not (bl2[si] if si < len(bl2) else "").strip():
                        break
                cur = ""
            rest = want_seg[len(cur):]
            for j in range(0, len(rest), 4):
                send(rest[j:j + 4])
                time.sleep(0.2)
            time.sleep(0.6)
        if not ok:
            raise StepError(f"os_type segment {si+1}/{len(segs)} not matched: "
                            f"wanted {len(want_seg)} got {len((blocks()[si] if si < len(blocks()) else ''))}")
        if si < len(segs) - 1:
            _osa('tell application "System Events" to key code 36')
            time.sleep(0.35)
    if norm("\n".join(blocks())) != norm(text):
        raise StepError(f"os_type text mismatch: wanted {len(norm(text))} got {len(norm(chr(10).join(blocks())))}")
    return True


RICH_TRUTH_JS = r"""
(() => {
  const box = document.querySelector('[data-fieldid="%s"]');
  if (!box) return {found: false};
  const ed = box.querySelector('[contenteditable="true"]');
  if (!ed) return {found: false, err: 'no contenteditable'};
  const k = Object.keys(ed).find(x => x.startsWith('__reactFiber$'));
  let f = k ? ed[k] : null, n = 0;
  while (f && n++ < 80) {
    const p = f.memoizedProps;
    if (p && p.editorState) {
      const t = p.editorState.getCurrentContent().getPlainText();
      return {found: true, kind: 'draft', len: t.length, text: t};
    }
    f = f.return;
  }
  return {found: true, kind: 'dom', len: (ed.innerText || '').length, text: ed.innerText || ''};
})()
"""

RICH_INJECT_JS = r"""
(() => {
  const txt = __TL_TEXT__, fid = __TL_FID__;
  const box = document.querySelector('[data-fieldid="' + fid + '"]');
  if (!box) return {ok: false, err: 'no field box'};
  const ed = box.querySelector('[contenteditable="true"]') || box;
  const k = Object.keys(ed).find(x => x.startsWith('__reactFiber$'));
  let f = k ? ed[k] : null, n = 0, p = null;
  while (f && n++ < 80) {
    const m = f.memoizedProps;
    if (m && m.editorState && typeof m.onChange === 'function') { p = m; break; }
    f = f.return;
  }
  if (!p) return {ok: false, err: 'no editorState+onChange in fiber'};
  try {
    const cur = p.editorState.getCurrentContent();
    const ES = Object.getPrototypeOf(p.editorState).constructor;
    const CC = Object.getPrototypeOf(cur).constructor;
    const next = ES.createWithContent(CC.createFromText(txt));
    p.onChange(next);
    return {ok: true, len: next.getCurrentContent().getPlainText().length};
  } catch (e) { return {ok: false, err: String(e).slice(0, 300)}; }
})()
"""


def _rich_truth(fieldid):
    """富文本字段的**真值**：优先读 Draft 编辑器内部状态。

    实测教训：`[data-fieldid="title"]` 容器里**含标签+提示文字**，按容器 innerText 读回
    会拿到 "Product Title / Include the most important attributes…"，于是写没写成功全判错。
    """
    return _js_json(RICH_TRUTH_JS % fieldid) or {}


def _rich_inject(fieldid, text):
    """React fiber 注入：拿到 Draft 的 editorState + onChange 直接换内容。

    **富文本写入的首选路径**——不依赖 OS 键盘/剪贴板，所以能无人值守（定时任务）。
    实测：injected=4 → 编辑器状态 len 0→4、DOM 同步显示 'AB12'。
    """
    # 注意：`_js` 会把表达式包成 JSON.stringify(<expr>)，所以只能给**表达式**（多语句会语法错），
    # 而且文本必须用 JSON 字面量内联进去（JSON 字符串同时也是合法 JS 字符串）。
    js = RICH_INJECT_JS.replace("__TL_TEXT__", json.dumps(text)).replace("__TL_FID__", json.dumps(fieldid))
    return _js_json(js) or {}


def _norm(s):
    return re.sub(r"\s+", " ", (s or "")).strip()


def _bsk_type(fieldid, value):
    """纯 bsk 逐字打字（**默认富文本写手**）。

    实测（2026-09-26，草稿编辑页）：
      · `bsk press <键> --selector <字段>` 能让 Draft **真正接受**输入：状态 0→7（"BSKTEST"
        精确 7/7）、0→23；88 字样本（大小写/空格/破折号/引号/冒号/括号/斜杠/#/换行）只差末尾
        1 个字符——那正是已知的**尾字符延迟**，不是"打不出来"。
      · 吞吐 **152 ms/字**（每字一次 CLI 调用 + CDP 往返）→ 475 字描述 ≈ 72 秒。
      · 不需要任何额外扩展、不碰 OS 键盘/剪贴板 → 定时任务无人值守可用。
    """
    sel = _rich_sel(fieldid)
    _reveal(sel)
    B.bsk("focus", sel)
    for ch in value:
        B.bsk("press", _KEYMAP.get(ch, ch), "--selector", sel)
    return {"ok": True, "writer": "bsk-press"}


def _bsk_keys(fieldid, key="Backspace", count=1):
    """可信按键（默认写手下用它删掉多写的尾巴）——`bsk press Backspace --selector <字段>`。"""
    sel = _rich_sel(fieldid)
    _reveal(sel)
    B.bsk("focus", sel)
    for _ in range(count):
        B.bsk("press", key, "--selector", sel)
    return {"ok": True, "writer": "bsk-press-key", "key": key, "count": count}


def _rich_sel(fieldid):
    return f'[data-fieldid="{fieldid}"] .public-DraftEditor-content'


_KEYMAP = {" ": "Space", "\n": "Enter", "\t": "Tab"}


def _clear_rich(fieldid):
    """清空富文本字段：**选中全部 + 真实 Delete**（实测有效）。

    实测（2026-09-26，同一字段连续验四轮）：`bsk press Backspace --selector` **无效**
    （状态不变）；而"JS 选中全部 → `bsk press Delete`"能清空 ✓，且清空后打字是**替换**语义。
    """
    sel = _rich_sel(fieldid)
    _reveal(sel)
    _js("""(()=>{const ed=document.querySelector('%s'); if(!ed) return false;
      ed.focus(); const r=document.createRange(); r.selectNodeContents(ed);
      const s=document.getSelection(); s.removeAllRanges(); s.addRange(r); return true;})()""" % sel)
    time.sleep(0.4)
    B.bsk("press", "Delete", "--selector", sel)
    time.sleep(1.2)


def _finish_rich(fieldid, value, retype_left=1):
    """真实按键打完后的收尾（每一步都是实测有效的手段，不做无效循环）：

    · **缺尾 → 补尾**：追加打字实测有效（`ABCDEFG` 精确命中）；但**先要等够**——
      实测"缺 1 字"多数是**延迟落值**而非丢字：抢着补尾会变成 +1（58→57→补→59）。
    · **多写 → 清空重打**：`Backspace` 实测无效，所以不能"删"；改成"选中全部 + Delete + 重打"，
      最多重打 1 次。
    · 都不成立就**老实返回失败**（交给下一条写入路 / 上层报错），绝不"差不多就算过"。
    """
    deadline = time.time() + 30.0                      # ① 耐心等状态落定（延迟落值很常见）
    while time.time() < deadline:
        raw = (_rich_truth(fieldid) or {}).get("text") or ""
        if raw == value:
            return True
        if raw and not value.startswith(raw):
            break                                      # 已经不是"短一截"的样子了 → 别再干等
        time.sleep(2.0)
    raw = (_rich_truth(fieldid) or {}).get("text") or ""
    if raw == value:
        return True
    if raw and value.startswith(raw) and 1 <= len(value) - len(raw) <= 40:
        short = len(value) - len(raw)
        if short <= 2:
            # 实测（5552977）：读回短 1–2 字**几乎总是落值滞后**而不是丢字 —— 补尾会把
            # 本来正确的文本变成 +1（facts 705 → 服务端 706，末尾多出一个句号）。
            # 这类**不补**，交给上层如实告警，最终以 verify_persisted 的服务端回读为准。
            log(f"{fieldid}: 读回短 {short} 字（疑似落值滞后）→ **不补尾**（补了会变 +1；以服务端回读为准）")
            return False
        tail = value[len(raw):]
        log(f"{fieldid}: 缺 {len(tail)} 字 → 补尾 {tail!r}")
        _bsk_type(fieldid, tail)
        time.sleep(4.0)
        return ((_rich_truth(fieldid) or {}).get("text") or "") == value
    if raw and raw.startswith(value) and retype_left > 0:
        log(f"{fieldid}: 多出 {len(raw) - len(value)} 字 → 清空重打（Backspace 无效）")
        _clear_rich(fieldid)
        _bsk_type(fieldid, value)
        time.sleep(4.0)
        if ((_rich_truth(fieldid) or {}).get("text") or "") == value:
            return True
        return _finish_rich(fieldid, value, retype_left - 1)
    return False


def fill_rich(fieldid, value, attempts=3):
    """富文本字段（Draft.js）写入。

    **唯一写手 = 纯 bsk 逐字真实按键**（`bsk press`，实测 152 ms/字、477/477 精确），
    不依赖任何浏览器扩展。曾经评估过的 CDP 加速件（8ms/字）**已下线**：功能等效但多一个部件的
    失效面（隔离世界、改代码要重载、调试器冲突），不值得进交付。
    这条路是"浏览器真实产生的按键" → 会走应用 onChange → 才可能落库；不碰 OS 键盘/剪贴板 → 无人值守可用。

    **判据（血泪教训）**：页面状态和 DOM 都不代表存进去了，而**草稿也从不落富文本**——
    唯一可信的验收是「提交后用 `verify_persisted.py` 读服务端」。
    """
    sel = f'[data-fieldid="{fieldid}"] .public-DraftEditor-content'
    want = _norm(value)

    def truth_norm():
        return _norm((_rich_truth(fieldid) or {}).get("text"))

    def wait_exact(timeout):
        """写入是**异步**的（实测：+1s 还可能读成空，稍后才落值/双写）→ 必须轮询。"""
        t0 = time.time()
        while time.time() - t0 < timeout:
            if truth_norm() == want:
                return True
            time.sleep(0.4)
        return truth_norm() == want

    # 实测三条硬结论（都是 2026-09-26 同一台机器上跑出来的）：
    #   ① **空字段上写入可靠**（`bsk fill` 37/37、51/51 两次精确命中）；替换/清空不可靠
    #      （Cmd+A+Delete 无效、JS 选全文再 fill 也不覆盖）。
    #   ② 写入是**异步**的：+1s 读回可能是空，接着第二轮再写就变 **双份**（实测 950=475×2）。
    #   ③ 所以：**只在空字段上写一次，然后轮询等它落值**；绝不盲目重写；发现双写用 fiber
    #      （整体替换语义）纠正一次。
    for att in range(1, attempts + 1):
        cur = truth_norm()
        if cur == want:
            return "already"

        # ⓪ 真实按键写入（**唯一写手 = 纯 bsk 逐字真实按键**，无任何扩展依赖）
        #    只在空字段上写（先聚焦，空字段最稳）。
        #    实测坑：末尾字符会**延迟落值**（title 66→65、description 475→474）→ 判成败前先等状态落定；
        #    缺了补尾、多了"全选 + Delete"清空重打；末尾 ±2 字差**如实告警**接受（`Backspace` 实测无效，
        #    做不了减法）——绝不"差不多就算过"。
        #    为什么不用别的路：**只有浏览器真实产生的键盘输入**才走应用 onChange → 才可能落库；
        #    fiber 注入 / `bsk fill` / `insertText` / 合成事件都只改页面状态（实测服务端为空）。
        if not cur:
            r = _bsk_type(fieldid, value)
            if not r.get("ok"):
                log(f"{fieldid}: bsk-press 不可用（{r.get('err')}）")
            else:
                if wait_exact(8.0):
                    return "bsk-press" if att == 1 else f"bsk-press·第{att}轮"
                if _finish_rich(fieldid, value):
                    return "bsk-press+收尾" if att == 1 else f"bsk-press+收尾·第{att}轮"
                log(f"{fieldid}: bsk-press + 收尾后仍 "
                    f"{len((_rich_truth(fieldid) or {}).get('text') or '')} 不符（期望 {len(value)}）")
                # 早停（省掉后面几条慢路，实测省 3–5 分钟）：末尾 ±2 字以内且其它逐字一致 → 如实接受
                _best, _core = truth_norm(), max(0, len(want) - 2)
                if _best and _best[:_core] == want[:_core] and abs(len(_best) - len(want)) <= 2:
                    log(f"{fieldid}: ⚠ 近似命中 {len(_best)}/{len(want)}（末尾 ±2 字内；平台最后一次"
                        f"输入事件总落后一步、Backspace 又无效 → 无法做减法；如实接受，提交后复核服务端）")
                    return f"近似{len(_best)}/{len(want)}"

        # ① fiber 注入（替换语义，偶发不粘）
        r = _rich_inject(fieldid, value)
        if r.get("ok"):
            if wait_exact(5.0):
                return "fiber" if att == 1 else f"fiber(第{att}轮)"
            log(f"{fieldid}: fiber 注入后真身 {len(truth_norm())} 不符（期望 {len(want)}）")
        else:
            log(f"{fieldid}: fiber 注入不可用（{r.get('err')}）")

        cur = truth_norm()
        # ② bsk fill —— **只在字段空着的时候**用（非空时会追加成两份）
        if not cur:
            try:
                _reveal(sel)
                B.bsk("focus", sel)
                B.bsk("fill", sel, "--value", value)
                if wait_exact(20.0):
                    # 实测：bsk fill 落值**慢**（>8s），所以这里给足 20s；
                    # 短了会导致「以为没写」→ 下一轮再写一份 → 双份（实测 950=475×2）。
                    return "bsk" if att == 1 else f"bsk(第{att}轮)"
                log(f"{fieldid}: bsk fill 后真身 {len(truth_norm())} 不符 → 下一条路")
            except Exception as e:
                log(f"{fieldid}: bsk fill 失败（{str(e)[:70]}）→ 下一条路")
        elif want and want in cur:
            # 双写/多写：fiber 是整体替换语义，用它纠正
            log(f"{fieldid}: 内容重复（{len(cur)}）→ 用 fiber 替换纠正")
            _rich_inject(fieldid, value)
            if wait_exact(10.0):
                return f"fiber(去重,第{att}轮)"

        # ③ OS 级真实粘贴（只试空字段；环境好时能成）
        if not truth_norm():
            try:
                os_paste(sel, value)
                if wait_exact(10.0):
                    return "os-paste" if att == 1 else f"os-paste(第{att}轮)"
                log(f"{fieldid}: OS 粘贴后真身 {len(truth_norm())} 不符")
            except StepError as e:
                log(f"{fieldid}: OS 粘贴不成（{str(e)[:60]}）")

        if att < attempts:
            log(f"{fieldid}: 第 {att} 轮没成（当前真身 {len(truth_norm())}）→ 停 2s 再来")

    # 富文本闸门（2026-09-26 定版口径）：**末尾差 ≤2 字算通过，但要留证据**。
    # 实测：本机平台上 Draft 的**最后一个输入事件总是落后一步**（打完 543 字读到 542；
    # 补尾又会撞上迟到的那次落值变成 544；Backspace 无效 → 无法做"减一"）。
    # 这一字之差**不影响提交**（服务端存 542 字，描述照样成立），所以不许因为 1 个字
    # 把整条 listing 卡死；但必须**如实记下来**，不许伪装成精确命中。
    best = truth_norm()
    core = max(0, len(want) - 2)                      # 除末 2 字外必须**逐字一致**
    if best and best[:core] == want[:core] and abs(len(best) - len(want)) <= 2:
        log(f"{fieldid}: ⚠ 富文本近似命中 {len(best)}/{len(want)}（末尾 ±2 字内；"
            f"平台最后一次输入事件总落后一步、且 Backspace 无效 → 无法做减法；"
            f"已如实接受，提交后请用 verify_persisted.py 复核服务端内容）")
        return f"近似{len(best)}/{len(want)}"
    raise StepError(f"rich fill {fieldid}: fiber / os-paste / bsk 三条路都没写进去"
                    f"（当前真身 {len(best)}/{len(want)}）")


def _option_expr(option_text):
    """选项元素：**精确匹配优先**，其次包含匹配，都取 innerText 最短的那个。

    只认**可见**元素（实测教训：全文档按文本找会命中页面上别处的同名文字，
    点下去等于点了别的东西——于是字段读回是空的）。option_text 为空时返回 null。
    """
    return ('(()=>{const w=%s;if(!w)return null;let ex=null,exl=1e9,inc=null,incl=1e9;'
            'const vis=e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0;};'
            'for(const e of document.querySelectorAll(\'[role="option"],li,div[role="button"],button,span,div\')){'
            'const t=(e.innerText||"").trim();if(!t||t.length>80||!vis(e))continue;const lt=t.toLowerCase();'
            'if(lt===w){if(t.length<exl){exl=t.length;ex=e;}}'
            'else if(lt.includes(w)&&t.length<incl){incl=t.length;inc=e;}}'
            'return ex||inc;})()') % json.dumps((option_text or "").strip().lower())


def _opt_vis(option_text):
    """「这个选项现在在页面上吗」——开下拉的就绪判据（实测选项不是 role=option，用不了那套）。"""
    return f"(()=>{{return !!({_option_expr(option_text)});}})()"


def _field_text(fieldid):
    """字段当前"显示的值"（读回断言用）。

    坑：`innerText` **不包含表单控件的值** —— 下拉/多选的已选值往往在 `input.value` 里，
    只看 innerText 会得到假阴性（明明选上了，却判成空）。
    """
    return (_js(f'''(()=>{{const e=document.querySelector('[data-fieldid="{fieldid}"]');if(!e)return "";
const parts=[e.innerText||""];
for(const i of e.querySelectorAll("input,textarea,select")){{parts.push(i.value||"");
  if(i.tagName==="SELECT"){{const o=i.selectedOptions&&i.selectedOptions[0];if(o)parts.push(o.textContent||"");}}}}
return parts.join(" ");}})()''') or "").strip()


def _click_option(option_text, verify=None):
    """点下拉/多选的选项：JS 原生 click 快，失败退 observe→ref 真点击。

    verify=(fieldid, 期望文本) 时**必须读回断言**：写没写进去不能假设（实测踩到：
    JS 点到了页面上别处的同名文字，看着点了、字段其实是空的）。
    """
    def good():
        return True if not verify else (verify[1].strip().lower() in _field_text(verify[0]).lower())

    if _js_click(_option_expr(option_text), None, 0.4):
        if good():
            log(f"option·js {option_text}")
            return True
        log(f"option·js {option_text} 点了但字段没落值 → 换真点击")
    for line in B.observe().split("\n"):
        if f'option "{option_text}"' in line:
            m = re.search(r"@e\d+", line)
            if m:
                _click_ref(m.group(0), f"option {option_text}")
                if good():
                    log(f"option·bsk {option_text}")
                    return True
    return False


def list_dropdown_options(fieldid, close=True):
    """**点开**某个下拉，列出它当前真实可选的选项文本（尽力而为，用于守门/报错）。

    为什么需要：下拉的选项列表**不在类目字段清单里**（实测 `fields_*.json` 的 options 是空的），
    只有点开才拿得到。B 场景最常见的失败就是「facts 里的值平台根本没有」
    （曾报 `option 'USB Type-C Cable' not found`，而当时没人知道平台到底有哪些值）。
    所以：① check_facts.py --live 用它做校验；② pick_dropdown 失败时用它把可用值打出来。
    """
    box = f'[data-fieldid="{fieldid}"]'
    opened = _js(f"""(()=>{{const e=document.querySelector('{box}');if(!e)return 'no-field';
      const s=e.querySelector('.ZorkInput__input-selector');if(!s)return 'no-selector';
      s.click();return 'clicked';}})()""")
    if opened in ("no-field", "no-selector"):
        return [], opened
    time.sleep(1.2)
    best, sel = [], ""
    for cand in ("[role=listbox] [role=option]", "[role=option]", ".ZorkAriaSelect__popover",
                 "[class*=Select] [class*=option]", "[class*=Popover]", "[class*=Menu]"):
        txt = _js(f"""(()=>{{const els=[...document.querySelectorAll('{cand}')]
          .filter(e=>{{const r=e.getBoundingClientRect();return r.width>0&&r.height>0;}})
          .map(e=>(e.innerText||'').trim().split('\\n')[0]).filter(t=>t&&t.length<60);
          return JSON.stringify([...new Set(els)].slice(0,40));}})()""")
        try:
            vals = json.loads(txt) if isinstance(txt, str) else (txt or [])
        except Exception:
            vals = []
        if len(vals) > len(best):
            best, sel = vals, cand
    if close:
        _js(f"""(()=>{{const e=document.querySelector('{box}');if(e){{const s=e.querySelector('.ZorkInput__input-selector');s&&s.click();}}}})()""")
        time.sleep(0.3)
    if best:
        log(f"dropdown {fieldid}: 真实选项 {len(best)} 个（选择器 {sel}）")
    return best, sel


def pick_combobox(fieldid, option_text):
    """**可搜索 combobox**（react-aria `ZorkAriaSelect` + `INPUT[role=combobox]`）：真键盘打开 → 过滤 → 点选项。

    实测（2026-09-26，Cellphone Cables / `Attribute.cable_type`）——三条路逐一排除：
      · ❌ JS 原生 click（点外层 `.ZorkInput__input-selector`、点 `input` 都试过）→ `[role=option]` 始终 0，打不开；
      · ❌ OS 级点击 → bsk 的整页 overlay 会吃掉（见 `_reveal` 的教训）；
      · ❌ "读选项列表"当判据 → 没打开时会读出假的 `(Optional)`（假阴性，曾据此误判"平台没有这个值"）；
      · ✅ **正解**：`_reveal` 滚到可见 → JS `focus()` → **`bsk press ArrowDown`（真实按键）** → 30 个选项出现
        → 打前缀过滤（"USB" → 4 个：USB Cable / USB Type-C Cable / Micro USB Cable / Mini USB Cable）
        → **JS 点该选项**（此时已打开，点得中）→ 读回断言。
      · ⚠️ `Enter` **不提交**（实测按了字段还是空）→ 必须真的点到选项。
    """
    sel = f'[data-fieldid="{fieldid}"]'
    inp = sel + ' input[role=combobox]'
    if not _js(f"!!document.querySelector('{inp}')"):
        raise StepError(f"combobox {fieldid}: 没有 input[role=combobox]")

    def n_opts():
        return int(_js("""(()=>[...document.querySelectorAll('[role=option]')]
          .filter(e=>e.getBoundingClientRect().width>0).length)()""") or 0)

    _reveal(sel)
    for _attempt in range(3):
        _js(f"""(()=>{{const i=document.querySelector('{inp}');if(i){{i.focus();i.click();}}}})()""")
        time.sleep(0.4)
        if n_opts() == 0:
            B.bsk("press", "ArrowDown", "--selector", inp)   # 真实按键：唯一能把它打开的方式
        time.sleep(0.9)
        if n_opts() > 0:
            break
    if n_opts() == 0:
        raise StepError(f"combobox {fieldid}: 打不开（focus + ArrowDown 都没出选项）")

    if _click_option(option_text, verify=(fieldid, option_text)):
        log(f"combobox {fieldid}: 直接点中 {option_text}")
        return True
    B.bsk("fill", inp, "--value", option_text[:4])           # 打前缀过滤（普通 input，fill 可用）
    time.sleep(0.9)
    if _click_option(option_text, verify=(fieldid, option_text)):
        log(f"combobox {fieldid}: 过滤后点中 {option_text}")
        return True
    avail = _js("""(()=>{const o=[...document.querySelectorAll('[role=option]')]
      .filter(e=>e.getBoundingClientRect().width>0).map(e=>(e.innerText||'').trim()).filter(Boolean);
      return JSON.stringify([...new Set(o)].slice(0,20));})()""")
    raise StepError(f"combobox {fieldid}: 选不中 '{option_text}'；打开后的选项={avail}")


def pick_dropdown(fieldid, option_text):
    """普通下拉：点开→选项出现就点。可搜索下拉（如 Laptop Compatibility 品牌表）：先输入前缀过滤。

    开下拉也走快路（JS click；就绪信号=选项列表出现），失败退回 bsk 真点击。
    **若该字段是 `INPUT[role=combobox]`（可搜索 combobox）→ 交给 `pick_combobox`**（JS click 打不开它），
    失败再退回本函数的老路（保底不回归）。
    """
    sel = f'[data-fieldid="{fieldid}"]'
    if _js(f"""!!document.querySelector('{sel} input[role=combobox]')""") is True:
        try:
            return pick_combobox(fieldid, option_text)
        except StepError as e:
            if "选不中" in str(e):
                raise   # 下拉已打开、选项列表是真的 → 平台确实没这个值，别再退老路白跑 30s
            log(f"combobox 路失败（{str(e)[:80]}）→ 退回普通下拉老路")
    # 实测（2026-09-26，Memory Cards 类目）：这个平台的下拉是 react-aria 的 `ZorkAriaSelect`，
    # **JS 点容器 DIV 不展开**（于是每字段白等 10s 退回 bsk 真点击）；点里面的
    # `.ZorkInput__input-selector` 一下就开 → 快路可用，省 ~10s/字段。
    open_expr = f"document.querySelector('{sel} .ZorkInput__input-selector') || document.querySelector('{sel}')"
    for attempt in range(3):
        # 开下拉快路：JS click → 等「这个选项出现在页面上」；没出现才退回 bsk 真点击（~10s/次）
        _fast_click(open_expr, f"open {fieldid}",
                    ready=_opt_vis(option_text), timeout=12)
        if attempt == 0 and _click_option(option_text, verify=(fieldid, option_text)):
            return True
        if _js(f"!!document.querySelector('{sel} input')"):
            B.bsk("fill", f'{sel} input', "--value", option_text[:4])
            time.sleep(0.8)
            if _click_option(option_text, verify=(fieldid, option_text)):
                return True
        if attempt and _click_option(option_text, verify=(fieldid, option_text)):
            return True
    avail, _sel = list_dropdown_options(fieldid)
    hint = ("；平台可选：" + " / ".join(avail[:14])) if avail else "（读不到选项列表，人工看一眼页面）"
    raise StepError(f"dropdown {fieldid}: option '{option_text}' not found{hint}")


def pick_multi(fieldid, text, option_text=None):
    """可搜索多选（如 Material）：先 fill 过滤，再点选项（选项点击走 _click_option 的快路）。"""
    option_text = option_text or text
    inp = f'[data-fieldid="{fieldid}"] input'
    _fast_click(f'document.querySelector(\'{inp}\')', f"open multi {fieldid}",
                ready=_opt_vis(option_text), timeout=8)
    B.bsk("fill", inp, "--value", text)
    time.sleep(0.8)
    if _click_option(option_text, verify=(fieldid, option_text)):
        return True
    raise StepError(f"multi {fieldid}: option '{option_text}' not found（读回断言失败）")


def pick_warranty(type_text, period_text):
    """Warranty 是容器内两个下拉：类型 + 有效期。"""
    fillid = "Attribute.warranty"
    pick_dropdown(fillid, type_text)
    js = """(()=>{const c=document.querySelector('[data-fieldid="%s"]');
const boxes=[...c.querySelectorAll('[role="combobox"],input')].filter(e=>e.offsetParent);
if(boxes.length<2) return JSON.stringify({n:boxes.length});
boxes[1].id='bsk_warranty_period'; return JSON.stringify({n:boxes.length});})()""" % fillid
    out = B.bsk("evaluate", js)
    if '"n":2' not in out.replace(" ", ""):
        raise StepError(f"warranty period control not found: {out.strip()[-120:]}")
    for attempt in (1, 2):
        B.bsk("click", "#bsk_warranty_period")
        time.sleep(1.2)
        for line in B.observe().split("\n"):
            if f'option "{period_text}"' in line:
                m = re.search(r"@e\d+", line)
                if m:
                    _click_ref(m.group(0), f"warranty period={period_text}")
                    return True
    raise StepError(f"warranty period option '{period_text}' not found")


# ---------------------------------------------------------------- images
_CORS = {}


def _free_port(start=8899, end=8925):
    import socket
    for p in range(start, end):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise StepError("no free port for image server")


def _start_cors(directory):
    if _CORS.get("proc") and _CORS["proc"].poll() is None and _CORS.get("dir") == directory:
        return _CORS
    here = os.path.dirname(os.path.abspath(__file__))
    import urllib.request
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 本机探测必须绕过系统代理
    marker = sorted(os.listdir(directory))[0]
    errs = []
    # 起因：8899 常被别人占着，占位者也回 200 —— 页内 fetch 会把别人的 HTML 当图片塞进
    # DataTransfer，平台静默丢弃（现象：'dropped:N' 但 0 张进图集）。
    # 所以自选空端口 + 起完必须确认「它真的在服务这个目录」；端口抢占/进程秒退则换端口重试。
    for _ in range(3):
        port = _free_port()
        proc = subprocess.Popen([sys.executable, os.path.join(here, "cors_http.py"), directory, str(port)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ok = False
        for _ in range(20):
            time.sleep(0.3)
            if proc.poll() is not None:
                errs.append(f"port {port}: server exited rc={proc.returncode}")
                break
            try:
                with opener.open(f"http://127.0.0.1:{port}/{urllib.parse.quote(marker)}", timeout=1) as r:
                    body = r.read()
                if len(body) > 2000:
                    ok = True
                    break
                errs.append(f"port {port}: only {len(body)} bytes")
            except Exception as e:
                errs.append(f"port {port}: {str(e)[:50]}")
        if ok:
            _CORS.update(proc=proc, dir=directory, port=port)
            log(f"image server http://127.0.0.1:{port} -> {directory}")
            return _CORS
        try:
            proc.kill()
            proc.wait(timeout=3)
        except Exception:
            pass
    raise StepError(f"local image server failed for {directory}: {errs[-3:]}")


def stop_cors():
    p = _CORS.get("proc")
    if p and p.poll() is None:
        p.terminate()
    _CORS.clear()


def _jpeg_size(path):
    """纯 stdlib 读 JPEG 宽高（不依赖 Pillow，引擎跑在系统 python3 上）。"""
    with open(path, "rb") as f:
        data = f.read()
    i = 2
    while i < len(data) - 9:
        if data[i] != 0xFF:
            i += 1
            continue
        m = data[i + 1]
        if m in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB):
            h = int.from_bytes(data[i + 5:i + 7], "big")
            w = int.from_bytes(data[i + 7:i + 9], "big")
            return w, h
        if m in (0xD8, 0xD9) or 0xD0 <= m <= 0xD7:
            i += 2
            continue
        i += 2 + int.from_bytes(data[i + 2:i + 4], "big")
    return None


# Takealot 图床的尺寸档：s-xlpreview=280 / s-pdpxl=459（都低于 600 门槛）/ s-zoom=1200
VARIANTS = ["s-zoom", "s-pdpxl", "s-xlpreview"]


def download_images(urls, out_dir, min_px=600):
    """下载源 listing 的图并落成本地文件。

    坑：`s-pdpxl` 只有 459×459，平台要求 ≥600×600，图太小会导致提交按钮一直 disabled
    （页面上不报错，只在 Product Images 说明里写着 Min 600 x 600 px）。所以要换 s-zoom 档。
    """
    os.makedirs(out_dir, exist_ok=True)
    files = []
    for i, u in enumerate(urls, 1):
        # 复用已下载的本地文件（实测：8 张从中国出口下载要 400s+，重跑就别再下一遍）
        cached = os.path.join(out_dir, f"img{i:02d}.jpg")
        if os.path.exists(cached) and os.path.getsize(cached) > 2000:
            sz = _jpeg_size(cached)
            if sz and min(sz) >= min_px:
                log(f"image {i}: 复用本地 {sz}")
                files.append(cached)
                continue
        best = None
        for v in VARIANTS:
            cand = re.sub(r"/(s-[a-z]+)\.file$", f"/{v}.file", u)
            path = os.path.join(out_dir, f"img{i:02d}.jpg")
            r = subprocess.run(["curl", "-sSL", "-m", "30", "-o", path, cand], capture_output=True, text=True)
            if r.returncode != 0 or not os.path.exists(path) or os.path.getsize(path) < 2000:
                continue
            size = _jpeg_size(path)
            if size and min(size) >= min_px:
                best = (path, v, size)
                break
            best = best or (path, v, size)
        if not best:
            raise StepError(f"download failed for {u}")
        if best[2] and min(best[2]) < min_px:
            raise StepError(f"source image too small for Takealot ({best[1]} {best[2]}): {u}")
        log(f"image {i}: {best[1]} {best[2]}")
        files.append(best[0])
    log(f"downloaded {len(files)} images -> {out_dir}")
    return files


def _png_size(path):
    with open(path, "rb") as f:
        head = f.read(26)
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")
    return None


def _check_images(files, min_px=600):
    """本地图也要先量尺寸：<600 会被平台静默拖着（提交按钮 disabled 且不报错）。"""
    for p in files:
        size = _jpeg_size(p) if p.lower().endswith((".jpg", ".jpeg")) else _png_size(p)
        if size and min(size) < min_px:
            raise StepError(f"image below Takealot minimum ({size[0]}x{size[1]} < {min_px}): {p}")
    return True


def _image_count():
    """图片分区里真实渲染出来的 <img> 数量（URL 直塞与拖入都用它当判据）。"""
    return int(_js("""(()=>{const s=[...document.querySelectorAll('[data-sectionname]')]
      .find(x=>/Images/i.test(x.getAttribute('data-sectionname')||''));
      return s ? [...s.querySelectorAll('img')].length : 0;})()""") or 0)


def add_images_by_link(urls, per_timeout=60.0):
    """**URL 直塞**（2026-09-26 端到端真跑复核过，别只信探针）：把图片 URL 交给平台，让它自己抓取入库。

    实测结论（2026-09-26；两轮直接计时 + 一轮端到端真跑）：
      · **每张 ≈3.8s**（`s-zoom` 100KB/1200px，两次直接计时都是 3.8s）vs 拖入 **≈28s/张**
        → 8 张 ≈30s vs ≈225s，**省 ≈190s/条**；再叠加**零本地下载**（拆解重塑的图从中国出口下 8 张要 400s+）
        → 首次跑一条总共省 ≈600s。
      · ⚠️ 一度误判成"跟拖入持平"：因为引擎的"图片全部上传"计时器把**富文本打字**也框住了（786 字 ≈120s+）
        → 已加独立计时器 `富文本完成`。**教训：计时器跨两步会得出完全相反的结论。**
      · ⚠️ 必换 ≥600px 档（`/(s-[a-z]+)\\.file$/` → `/s-zoom.file`）：探针喂 459px 小图 3–11s 很快，
        但 <600px 会被平台**静默禁用 Submit**。
      · ⚠️ 同一草稿里**已经有的图**再喂会被**静默忽略**（计数不长）→ 别急着当失败，先看是不是重复。
      · 真入库：平台把 URL 抓下来**重新托管**成 `media.takealot.com/covers_images/<新id>/…`；存草稿重开后还在。

    判据：每喂一张都要看到 `_image_count()` 增长（不看"按钮点了"）；超时就报错，由上层退回拖入。
    """
    if not urls:
        raise StepError("add_images_by_link: 没有 URL")
    if _js("""(()=>{const s=[...document.querySelectorAll('[data-sectionname]')]
        .find(x=>/Images/i.test(x.getAttribute('data-sectionname')||''));
        const b=s&&[...s.querySelectorAll('button')].find(x=>/^Add Image Link$/i.test((x.innerText||'').trim()));
        return b?'yes':'no';})()""") != "yes":
        raise StepError("images: 找不到 Add Image Link 按钮（分区还没渲染？）")
    _js("""(()=>{const s=[...document.querySelectorAll('[data-sectionname]')]
      .find(x=>/Images/i.test(x.getAttribute('data-sectionname')||''));
      const b=[...s.querySelectorAll('button')].find(x=>/^Add Image Link$/i.test((x.innerText||'').trim()));
      if(b) b.click();})()""")
    ok = 0
    for i in range(8):                     # 等 URL 模式面板挂载出 link-input
        time.sleep(1.0)
        if _js("""!!document.querySelector('input.link-input')""") is True:
            break
    else:
        raise StepError("images: 点了 Add Image Link 但 link-input 没出现")
    for idx, u in enumerate(urls, 1):
        before = _image_count()
        # ⚠️ 必须换成 ≥600px 的档位：源图 URL 常是 `s-pdpxl`(459px)，平台图太小时**不报错**，
        #    只是把预览页的 Submit 永久 disabled（实测坑）。这里跟 `download_images` 用同一个档。
        u = re.sub(r"/(s-[a-z]+)\.file$", "/s-zoom.file", u)
        B.bsk("fill", "input.link-input", "--value", u)
        time.sleep(0.4)
        _js("""(()=>{const s=[...document.querySelectorAll('[data-sectionname]')]
          .find(x=>/Images/i.test(x.getAttribute('data-sectionname')||''));
          const b=[...s.querySelectorAll('button')].find(x=>/^Add Image$/i.test((x.innerText||'').trim()));
          if(b) b.click();})()""")
        t0 = time.time()
        while time.time() - t0 < per_timeout:
            time.sleep(2.0)
            if _image_count() > before:
                ok += 1
                break
        else:
            raise StepError(f"images: URL 直塞第 {idx} 张超时（{u[:70]}）"
                            "——若这张图本就在这个草稿里，平台会**静默忽略**（不是故障）")
    log(f"images via link: {ok}/{len(urls)}")
    return ok


def add_images(files):
    """把本地图片注入页面的 React onDrop 区（免扩展 file:// 权限）。"""
    directory = os.path.dirname(os.path.abspath(files[0]))
    _check_images(files)
    _start_cors(directory)
    names = [os.path.basename(f) for f in files]
    js = """(() => {
  const names=%s;
  const inp=document.querySelector('input[type=file]');
  if(!inp) return 'no-input';
  let el=inp, target=null;
  while(el && el!==document.body){const k=Object.keys(el).find(x=>x.startsWith('__reactProps$'));
    if(k && el[k] && el[k].onDrop){target=el;break;} el=el.parentElement;}
  if(!target) return 'no-drop-target';
  const   dt=new DataTransfer();
 for(const n of names){
   const x=new XMLHttpRequest();
   x.open('GET','http://127.0.0.1:%d/'+encodeURIComponent(n),false);
   x.overrideMimeType('text/plain; charset=x-user-defined'); x.send();
   if(x.status!==200) return 'fetch-fail:'+n+':'+x.status;
   const raw=x.responseText, b=new Uint8Array(raw.length);
   for(let i=0;i<raw.length;i++) b[i]=raw.charCodeAt(i)&0xff;
   if(b.length<2000) return 'fetch-tiny:'+n+':'+b.length;
   dt.items.add(new File([b],n,{type:'image/jpeg'}));
 }
 for(const t of ['dragenter','dragover','drop']) target.dispatchEvent(new DragEvent(t,{bubbles:true,cancelable:true,dataTransfer:dt}));
 return 'dropped:'+dt.items.length;
 })()""" % (json.dumps(names), _CORS.get("port") or IMG_PORT)
    out = B.bsk("evaluate", js)
    if "dropped:" not in out:
        raise StepError(f"image drop failed: {out.strip()[-160:]}")
    # 计数口径：图集里的 <img> 上传期间是 blob:/临时 URL，不是 covers_images；
    # 分区标题里的 "N Images" 才是稳定真值（先前用 covers_images 计数得到假阴性 0）。
    count_js = ("(()=>{const s=[...document.querySelectorAll('[data-sectionname]')].find(s=>/Images/.test(s.getAttribute('data-sectionname')));"
                "if(!s) return 0; const m=/(\\d+)\\s+Images?/i.exec(s.innerText||''); if(m) return parseInt(m[1],10);"
                "return [...s.querySelectorAll('img')].filter(i=>/covers_images|blob:/.test(i.src||'')).length;})()")
    n = 0
    for _ in range(15):
        time.sleep(3)
        n = int(_js(count_js) or 0)
        if n >= len(files):
            break
    if n < len(files):
        raise StepError(f"images not attached: {n} visible of {len(files)}")
    log(f"images attached: {n}")
    stop_cors()
    return n


# ---------------------------------------------------------------- validate / submit
IGNORE_EMPTY = {"Attribute.materials", "ProductID.Value"}  # Material 落值是 chip；条码可留给平台生成


def outstanding():
    """返回 (空着的必填, 被标错的必填, 页面上的错误文案)。

    `data-error` 是平台自己的判定，才是真信号；空值检查只用来兜底我们该填没填的字段。
    富文本（title/description）没有 input，要读 contenteditable 的 innerText。
    """
    rows = _js_json("""(()=>[...document.querySelectorAll('[data-isrequired="true"]')].map(e=>{
const fid=e.getAttribute('data-fieldid');
const inp=e.querySelector('input,textarea');
const ce=e.querySelector('[contenteditable="true"]');
let val = inp ? inp.value : (ce ? ce.innerText : null);
if (ce) { const k=Object.keys(ce).find(x=>x.startsWith('__reactFiber$')); let f=k?ce[k]:null,n=0;
  while(f&&n++<80){const p=f.memoizedProps; if(p&&p.editorState){val=p.editorState.getCurrentContent().getPlainText();break;} f=f.return;} }
return {fid:fid, err:e.getAttribute('data-error')==='true', hasInput:!!inp, valLen: val===null?-1:String(val).trim().length};}))()""")
    texts = _js_json("""(()=>[...new Set([...document.querySelectorAll('[class*=ZorkFieldContainer__error]')].map(e=>e.innerText.trim()))])()""")
    empty = [r["fid"] for r in rows if r["valLen"] == 0 and r["fid"] not in IGNORE_EMPTY]
    errs = [r["fid"] for r in rows if r["err"]]
    return {"empty": empty, "errs": errs, "texts": texts}


def assert_clean(context=""):
    out = outstanding()
    if out["errs"] or out["texts"] or out["empty"]:
        raise StepError(f"validation not clean {context}: flagged={out['errs']} messages={out['texts']} empty={out['empty']}")
    log(f"assert clean {context}")


def click_section_next(ctx_substr):
    try:
        ref = _find_ref(lambda l: 'button "Next"' in l and ctx_substr in l, f"Next[{ctx_substr}]")
        _click_ref(ref, f"Next[{ctx_substr}]")
        return "observe"
    except StepError:
        out = B.bsk("evaluate", """(()=>{const sec=[...document.querySelectorAll('[data-sectionname]')].find(s=>/%s/i.test(s.getAttribute('data-sectionname')));
const b=sec&&[...sec.querySelectorAll('button')].find(x=>/^Next$/i.test(x.textContent.trim()));
if(!b) return 'no-next'; b.click(); return 'clicked';})()""" % ctx_substr)
        if "clicked" not in out:
            raise StepError(f"section Next [{ctx_substr}] not found")
        time.sleep(1.6)
        return "js"


def commit_sections(order=("Product Details", "Product Images", "Product Identifiers")):
    for name in order:
        how = click_section_next(name)
        log(f"section Next [{name}] via {how}")


def continue_to_preview():
    ref = _find_ref(lambda l: "Continue to Preview" in l and "button" in l, "Continue to Preview")
    _click_ref(ref, "Continue to Preview")
    time.sleep(4)


def click_button(pattern, scope="document", timeout=8, require_enabled=True):
    """按文本正则点按钮（JS click，避开 overlay/固定底栏的坐标坑）。"""
    js = ("(()=>{const re=new RegExp(%s,'i');const b=[...%s.querySelectorAll('button')]"
          ".find(x=>re.test((x.textContent||'').trim()));if(!b) return 'missing';"
          "if(b.disabled) return 'disabled';b.click();return 'clicked';})()" % (json.dumps(pattern), scope))
    end = time.time() + timeout
    out = ""
    while time.time() < end:
        out = _js(js) or ""
        if out == "clicked":
            return out
        time.sleep(1.2)
    return out


def submit_button_state():
    return _js("""(()=>{const b=[...document.querySelectorAll('button')].find(x=>/^Submit$/i.test(x.textContent.trim()));
if(!b) return 'missing';return b.disabled?'disabled':'enabled';})()""") or "missing"


def save_and_reopen(rich_fields=None):
    """预览页 Submit 点不动时的兜底：先 Save and Close 把草稿持久化，再从 submissions 列表重开。

    为什么：预览页的 Submit 会被平台 disabled，而页面**不报任何错**；
    实测这种情况下 `[data-submissionid]` 还是占位值 "123"（草稿没落库，
    浏览器关了就没有）。落库后再从列表打开，提交按钮才会亮。

    **重开后必须重写富文本**：实测草稿的 Save and Close **不落富文本**（重开后 title/description
    都是 0，验过两次）→ 不重写的话，提交出去的就是空描述（假成功）。
    """
    log("submit disabled → Save and Close 持久化草稿，再从列表重开")
    click_button(r"^Save and Close$", timeout=10)
    time.sleep(5)
    goto(SUBMISSIONS_URL)
    time.sleep(3)
    # 实测（2026-09-26）：列表行里的入口是**提交名链接**（不是 Edit/Continue 按钮）——
    # 只找按钮会得到 'no-open'（这就是兜底一直失效的原因）。
    first = _js("""(()=>{const a=[...document.querySelectorAll('table tr a, table a')]
        .find(x=>(x.innerText||'').trim().length>4 && !/^\\s*(All|Archive)/i.test(x.innerText||''));
        if(!a) return 'no-open'; a.click(); return 'opened:'+a.innerText.trim().slice(0,40);})()""")
    log(f"reopen draft: {first}")
    time.sleep(6)
    # 打开后可能直接落在预览页/表单页；两种都处理
    if not _js("document.querySelectorAll('[data-fieldid]').length"):
        _js("""(()=>{const b=[...document.querySelectorAll('button')].find(x=>x.innerText.trim()==='Edit');
            if(b)b.click(); return true;})()""")
        for _ in range(20):
            time.sleep(1.5)
            if _js("document.querySelectorAll('[data-fieldid]').length"):
                break
    if rich_fields:
        for fid, val in rich_fields.items():
            try:
                how = fill_rich(fid, val)
                log(f"重开后重写富文本 {fid} via {how}")
            except StepError as e:
                log(f"重开后重写富文本 {fid} 失败（{str(e)[:60]}）")
    if _js("""/Continue to Preview/i.test((document.body.innerText||''))"""):
        click_button(r"Continue to Preview", timeout=10)
        time.sleep(5)
    return first


def set_submission_name(name):
    """预览页改「Submission Name」（铅笔按钮）—— 同名提交会被平台静默挡住 Submit。"""
    if not _js("""(()=>{const p=document.querySelector('.ZorkPreviewHeader__pencil');if(!p)return false;p.click();return true;})()"""):
        return "no-pencil"
    time.sleep(1.5)
    sel = ".ZorkPreviewHeader input"
    if not _js(f"!!document.querySelector('{sel}')"):
        return "no-input"
    B.bsk("focus", sel)
    B.bsk("fill", sel, "--value", name)
    time.sleep(0.6)
    _js("""(()=>{const i=document.querySelector('.ZorkPreviewHeader input');if(!i)return 0;
i.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));i.blur();return 1;})()""")
    time.sleep(2)
    log(f"submission name -> {name}")
    return "renamed"


def submit(wait_enabled=45, rich_fields=None):
    """提交（带兜底链）：等按钮可点 → 点 Submit → 弹窗确认 → 读 submissions 表核对。

    验证口径见 first_submission_row()：新行 = 提交成功的唯一证据。
    """
    end = time.time() + wait_enabled
    state = submit_button_state()
    while state != "enabled" and time.time() < end:
        time.sleep(3)
        state = submit_button_state()
    if state != "enabled":
        # 兜底 1：改个唯一的 submission name（同名会被平台静默挡住）
        set_submission_name("Cables %s" % time.strftime("%d %b %Y %H%M"))
        time.sleep(3)
        state = submit_button_state()
    if state != "enabled":
        # 兜底 2：Save and Close 落库 → 从列表重开（重开后才有真实 submission id）。
        # 注意：草稿不落富文本 → 重开后**必须重写**，否则提交的是空描述（假成功）。
        save_and_reopen(rich_fields=rich_fields)
        end = time.time() + wait_enabled
        state = submit_button_state()
        while state != "enabled" and time.time() < end:
            time.sleep(3)
            state = submit_button_state()
    if state != "enabled":
        # 取证：把预览页上一切可能的"为什么禁用"都打出来（别再靠猜）
        log("submit 取证 —— URL: %s" % _js("location.href"))
        for ln in (_js("document.body.innerText") or "").split("\n"):
            ln = ln.strip()
            if ln and len(ln) < 200 and re.search(
                    r"(?i)error|invalid|required|missing|must |cannot|not (allowed|available)|fix|"
                    r"complete|minimum|at least|select|provide", ln):
                log(f"   · {ln}")
        log("submit 取证 —— 报错字段: %s" % (_js("""(()=>{const o=[];
            document.querySelectorAll('[data-error="true"],.ZorkInput--hasError,[aria-invalid="true"]').forEach(el=>{
            const box=el.closest('[data-fieldid]')||el;
            o.push((box.getAttribute('data-fieldid')||'?')+': '+(el.innerText||'').trim().slice(0,70));});
            return JSON.stringify(o.slice(0,12));})()""") or "[]"))
        raise StepError(f"Submit 按钮不可用（{state}）：平台没给原因，草稿可能未落库")
    log("Submit enabled → 点击")
    click_button(r"^Submit$", timeout=8)
    time.sleep(4)
    # 确认弹窗标签容错
    for _ in range(6):
        got = click_button(r"Confirm Submission|Confirm|Yes, submit", timeout=0.5)
        if got == "clicked":
            log("confirm dialog clicked")
            break
        time.sleep(2)
    time.sleep(6)
    goto(SUBMISSIONS_URL)
    row = first_submission_row()
    row["submission_id"] = first_submission_id(row)   # 干净的 SID（验收/报告用）
    log(f"submitted: {row}")
    return row


def first_submission_id(row=None):
    """从 submissions 列表首行挑出 submission id（6 位以上纯数字），并给出可直接打开的 URL。

    为什么单独抽：`row` 是一张表的 cells 列表，**人和 agent 都不该去猜哪一格是 SID**。
    实测（2026-09-26）：报告里没有干净 SID → 手工正则失败 → `verify_persisted.py` 收到空参数，
    去验了一条无关的旧草稿并报 FAIL（假警报）。**验收命令必须是复制粘贴级的。**
    """
    row = row or first_submission_row()
    for c in (row.get("cells") or []):
        c = (c or "").strip()
        if c.isdigit() and len(c) >= 6:
            return {"id": c, "url": f"{NEW_LISTING_URL}/{c}"}
    return {}


def first_submission_row():
    return _js_json("""(()=>{const tr=document.querySelector('table tbody tr');
if(!tr) return {none:true};
return {cells:[...tr.querySelectorAll('td')].map(td=>td.innerText.replace(/\\s+/g,' ').trim())};})()""")


# ---------------------------------------------------------------- high level
def _t(label, reset=False):
    """带耗时的进度日志（找瓶颈用；不改变逻辑）。reset=True 重置计时基准。"""
    global _TPREV
    now = time.time()
    if reset:
        _TPREV = now
        return 0.0
    dt = now - _TPREV
    _TPREV = now
    log(f"TIMER {label}: +{dt:.1f}s (总 {now - _T0:.1f}s)")
    return dt


def create_listing(facts, submit_it=True):
    """facts: dict — 见 create_listing.py 的示例。返回结果摘要。"""
    report = {"name": facts.get("name"), "steps": []}
    _t(None, reset=True)
    open_new_listing()
    _t("新建页就绪")
    report["steps"].append("new-listing page")
    pick_category(facts["category"])
    _t("类目+变体提交")
    ensure_attributes(facts)      # 字段没出来 = 会话退化 → 自动重启会话重做（实测有效）

    optional = set(facts.get("optional") or [])
    times = {}

    def _run(step_fn, fid, label, retries=1):
        """跑一步；失败重试一次（实测属性步偶发读回空：`dimensions.width read back empty`
        ——同一字段上一轮还好、这一轮就空，属渲染/时序抖动，重试即可，不该让整条流程挂掉）。"""
        t0 = time.time()
        try:
            for attempt in range(retries + 1):
                try:
                    return step_fn()
                except StepError as e:
                    if fid in optional:
                        log(f"optional {fid} skipped ({label}): {e}")
                        return None
                    if attempt < retries:
                        log(f"{fid} 第{attempt + 1}次失败（{str(e)[:70]}）→ 停 2s 重试")
                        time.sleep(2)
                        continue
                    raise
        finally:
            times[label] = times.get(label, 0.0) + (time.time() - t0)

    for fid, val in (facts.get("text_fields") or {}).items():
        _run(lambda fid=fid, val=val: fill_text(fid, val), fid, "text")
    for fid, val in (facts.get("dropdowns") or {}).items():
        _run(lambda fid=fid, val=val: pick_dropdown(fid, val), fid, "dropdown")
    for fid, val in (facts.get("multi_selects") or {}).items():
        pick_multi(fid, val, (facts.get("multi_labels") or {}).get(fid))
    if facts.get("warranty"):
        pick_warranty(facts["warranty"]["type"], facts["warranty"]["period"])
    log("attributes filled")
    _t(f"属性全部完成（分组耗时 {', '.join(f'{k}={v:.1f}s' for k, v in sorted(times.items(), key=lambda x: -x[1]))}）")

    # 富文本放在属性之后：title 是 AutoBuild 字段，属性没落值时它可能不可写
    for fid, val in (facts.get("rich_fields") or {}).items():
        try:
            how = fill_rich(fid, val)
            log(f"rich field {fid} via {how}")
        except StepError as e:
            if fid in optional:
                # 实测（2026-09-26）：title 是平台的 AutoBuild 字段（data-fieldtype="Title"，
                # 平台按属性自己生成标题；对照组 5551654 提交成功、服务端 title 读回 0）→
                # 写它是"加分项"，写不进去不该挡整条流程（description 才是必须的）。
                log(f"optional rich {fid} 跳过（{str(e)[:70]}）")
                continue
            # description 是**必须**的：写不进去就保存草稿 + 打印待粘文本，让人工补一下再提交。
            log(f"富文本 {fid} 写入失败：{e}")
            log("→ 人工补救（草稿已保存）：在浏览器里把下面这段粘进对应字段")
            print(f"\n[需人工粘贴 · {fid}]\n{val}\n", flush=True)
            try:
                click_button(r"^Save and Close$", timeout=8)
                log("已 Save and Close，草稿保留")
            except Exception:
                pass
            raise StepError(f"rich field {fid} 未写入（草稿已保存，按上方文本人工粘贴后提交）")

    _t("富文本完成（打字是单条 listing 的最大单项：152 ms/字，786 字 ≈ 120s）")

    # 图片来源：① 本地文件（A 场景）② **URL 直塞**（默认；≈3.8s/张 vs 拖入 ≈28s/张，且零本地下载）
    #           ③ 兜底：本地下载 → 合成 DataTransfer 拖入（`TL_IMG_MODE=drop` 可强制走老路）
    files = facts.get("images") or []
    urls = facts.get("image_urls") or []
    mode = (os.environ.get("TL_IMG_MODE") or "link").lower()
    if urls and mode != "drop":
        try:
            report["images"] = add_images_by_link(urls)
            report["image_mode"] = "link"
        except StepError as e:
            log(f"URL 直塞不可用（{str(e)[:90]}）→ 退回本地下载 + 拖入")
    if report.get("image_mode") != "link":
        if urls:
            out_dir = os.path.join(WORKDIR, "assets", facts.get("name", "listing"))
            files = files + download_images(urls, out_dir)
            report["downloaded"] = len(files)
        report["images"] = add_images(files)
        report["image_mode"] = "drop"
    _t("图片全部上传")
    commit_sections()
    _t("分区提交")
    assert_clean(facts.get("name", ""))
    report["clean"] = True
    _t("断言干净")

    if submit_it:
        continue_to_preview()
        _t("进预览页")
        report["submission"] = submit(rich_fields=facts.get("rich_fields") or {})
        _t("提交完成")
    return report
