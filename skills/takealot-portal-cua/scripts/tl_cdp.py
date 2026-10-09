#!/usr/bin/env python3
"""tl_engine 的 CDP 驱动层：把引擎里的 bsk 原语换成裸 CDP（无扩展）。

用法（在 tl_engine 之外）：
    import tl_cdp; eng = tl_cdp.install()      # 返回 tl_engine 模块，已注入 CDP shim
    eng.create_listing(facts, submit_it=True)

实测依据（见技能 takealot-portal-cua/references/cdp-no-extension.md）：
  · 富文本必须逐字发 **keydown+keyup** 的 `Input.dispatchKeyEvent`（agent-browser 的 keyboard type
    只发 beforeinput/input → 字会乱序）；本 shim 的 press 就是这么发的。
  · 本地图片走 `DOM.setFileInputFiles`（隐藏 input 也能喂，不需要 cors_http / 拖入合成）。
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.expanduser(os.environ.get("TL_TOOLS") or "~/.hermes/tools"))
sys.path.insert(0, os.path.expanduser("~/.hermes/cache/scratch/pylibs"))
try:
    import websocket  # noqa: E402
except ImportError:                                     # noqa: BLE001
    raise SystemExit(
        "缺依赖 websocket-client（CDP 驱动必须）。装一次即可：\n"
        "  python3 -m pip install websocket-client\n"
        "  国内网络慢的话走镜像：\n"
        "  python3 -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple websocket-client\n"
        "装不上/不想装 → 用兜底路：run_listing.py --driver bsk（走 BrowserSkill 官方扩展）")

# 本机 CDP 必须绕开代理：Clash TUN 等全局代理下 urllib/websocket-client 会把 127.0.0.1 也走代理
# → 502 / 连接被丢（实测）。
for _v in ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
    os.environ.pop(_v, None)
os.environ["no_proxy"] = os.environ["NO_PROXY"] = "127.0.0.1,localhost,::1"

CDP_PORT = int(os.environ.get("TL_CDP_PORT") or 9222)
URL_MATCH = os.environ.get("TL_CDP_URL_MATCH") or "takealot"
# 节奏：CDP 比 bsk 快 ~100 倍，反而会跟平台自己的重渲染赛跑（实测：类目第 3 列迟迟不渲染）。
# 给每个原语后面加一点静默，模拟 bsk 的"慢"带来的 settle。
PACE = float(os.environ.get("TL_CDP_PACE") or 0.12)

_KEYCODES = {
    "Enter": ("Enter", "Enter", 13), "\n": ("Enter", "Enter", 13),
    "Tab": ("Tab", "Tab", 9), "Escape": ("Escape", "Escape", 27), "\t": ("Tab", "Tab", 9),
    "Space": ("Space", " ", 32), " ": ("Space", " ", 32),
    "Backspace": ("Backspace", "Backspace", 8), "Delete": ("Delete", "Delete", 46),
    "ArrowDown": ("ArrowDown", "ArrowDown", 40), "ArrowUp": ("ArrowUp", "ArrowUp", 38),
    "ArrowLeft": ("ArrowLeft", "ArrowLeft", 37), "ArrowRight": ("ArrowRight", "ArrowRight", 39),
    "Home": ("Home", "Home", 36), "End": ("End", "End", 35),
}


def _key_spec(key):
    """key spec → (code, key, vk). 单字符按 KeyX/DigitN 推。"""
    if key in _KEYCODES:
        return _KEYCODES[key]
    if len(key) == 1:
        if key.isalpha():
            return "Key" + key.upper(), key, ord(key.upper())
        if key.isdigit():
            return "Digit" + key, key, ord(key)
        return None, key, 0            # 标点：只给 text
    return None, key, 0


def _loopback_json(url, timeout=10):
    """本机 CDP HTTP 端点：**必须绕开系统代理**（Clash TUN 下 urllib 走代理会 502）。"""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=timeout) as r:
        return json.load(r)


class CDP:
    def __init__(self, port=CDP_PORT, url_match=URL_MATCH):
        ver = _loopback_json(f"http://127.0.0.1:{port}/json/version")
        self.ws = websocket.create_connection(ver["webSocketDebuggerUrl"], timeout=60,
                                              suppress_origin=True)
        self.i = 0
        page = None
        for t in _loopback_json(f"http://127.0.0.1:{port}/json/list"):
            if t.get("type") == "page" and url_match in t.get("url", ""):
                page = t
                break
        if page is None:
            r = self.call("Target.createTarget", {"url": "about:blank"})
            tid = r["result"]["targetId"]
            page = {"id": tid}
        r = self.call("Target.attachToTarget", {"targetId": page["id"], "flatten": True})
        self.session = r["result"]["sessionId"]
        # ⚠️ 不要 Page./Runtime.enable：它们会让 Chrome 持续推送事件（这个后台的日志很多），
        # 客户端一边打字一边解析事件 → 打字被拖慢到 ~40 ms/字（实测）。DOM.enable 只在需要时开。
        # 但下面两件必须做：页面一旦 hidden（窗口被遮挡/最小化），Chrome **直接丢键盘事件**
        # ——实测血案：类目/填值/图片全正常，只有打字静默 0 字，折腾半天。
        self.call("Page.bringToFront")
        try:
            self.call("Emulation.setFocusEmulationEnabled", {"enabled": True})
        except Exception:
            pass
        self._refs = {}

    # --- plumbing -----------------------------------------------------------
    def call(self, method, params=None, timeout=60):
        self.i += 1
        mid = self.i
        self.ws.send(json.dumps({"id": mid, "method": method,
                                 "params": params or {},
                                 **({"sessionId": self.session} if getattr(self, "session", None) else {})}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg
        raise TimeoutError(method)

    def post(self, method, params=None):
        """发出但不等待回复（打字用：实测**快速连发**才不会被应用自己的重渲染打断）。"""
        self.i += 1
        self.ws.send(json.dumps({"id": self.i, "method": method, "params": params or {},
                                 **({"sessionId": self.session} if getattr(self, "session", None) else {})}))

    def drain(self, quiet=0.25):
        """把不等待的回复读干净。"""
        self.ws.settimeout(quiet)
        try:
            while True:
                self.ws.recv()
        except Exception:
            pass
        finally:
            self.ws.settimeout(60)

    def evaluate(self, expr, await_promise=True):
        r = self.call("Runtime.evaluate", {"expression": expr, "returnByValue": True,
                                           "awaitPromise": await_promise, "userGesture": True})
        res = r.get("result", {}).get("result", {})
        if "exceptionDetails" in r.get("result", {}):
            return "ERR:" + json.dumps(r["result"]["exceptionDetails"])[:200]
        return res.get("value")

    def js(self, expr):
        """表达式 → JSON 文本（兼容引擎 _js/_candidates 的解析口径）。"""
        v = self.evaluate(f"JSON.stringify({expr})")
        return v if isinstance(v, str) else json.dumps(v)

    def _rect(self, selector):
        return self.evaluate("""(()=>{const e=document.querySelector(%s);
          if(!e) return null; e.scrollIntoView({block:'center'}); const r=e.getBoundingClientRect();
          return {x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2), w:Math.round(r.width), h:Math.round(r.height)};})()"""
                             % json.dumps(selector))

    def real_click(self, selector):
        # 先归零下拉状态：react-aria 的 selector 是"切换"语义，已展开时再点会**关掉**它
        # （实测：引擎重试路径因此拿到一个已关的列表 → 找不到选项）。
        was_open = self.evaluate("""(()=>{const e=document.querySelector(%s);
          if(!e) return false; const t=e.closest('[aria-expanded]')||e;
          return t.getAttribute('aria-expanded')==='true';})()""" % json.dumps(selector))
        if was_open:
            self.call("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Escape", "code": "Escape",
                                                 "windowsVirtualKeyCode": 27, "nativeVirtualKeyCode": 27})
            self.call("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Escape", "code": "Escape",
                                                 "windowsVirtualKeyCode": 27, "nativeVirtualKeyCode": 27})
            time.sleep(0.3)
        try:
            rc = self._rect(selector)
        except Exception:
            rc = None
        if not rc or rc["w"] == 0 or rc["h"] == 0:
            # 视口外/不可见 → 退化为 JS 原生 click（实测对按钮/选项有效；对 react-aria 下拉无效，
            # 那种情况会由上层断言暴露出来）
            ok = self.evaluate("(()=>{const e=document.querySelector(%s); if(!e) return false; e.click(); return true;})()"
                               % json.dumps(selector))
            if not ok:
                raise RuntimeError(f"click: no element for {selector}")
            return "ok(js)"
        for t in ("mouseMoved", "mousePressed", "mouseReleased"):
            p = {"type": t, "x": rc["x"], "y": rc["y"], "button": "left", "clickCount": 1,
                 "buttons": 1 if t == "mousePressed" else 0}
            self.call("Input.dispatchMouseEvent", p)
        return "ok"

    def assert_visible(self):
        """打字前必须确认页面可见：hidden 时 Chrome 丢键盘事件（实测静默 0 字）。"""
        vis = self.evaluate("document.visibilityState")
        if vis != "visible":
            self.call("Page.bringToFront")
            time.sleep(0.4)
            vis = self.evaluate("document.visibilityState")
        if vis != "visible":
            raise RuntimeError(
                f"浏览器窗口不可见（visibilityState={vis}）——CDP 键盘事件会被丢弃。"
                "把 Chrome 窗口切到前台（或改用 --headless=new）后重试。")
        return True

    def _key_params(self, spec):
        """键位参数（带 text，否则 Chrome 只发 keydown 不产生字符 —— 实测会丢字）。"""
        code, key, vk = _key_spec(spec)
        p = {"key": key, "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk}
        if code:
            p["code"] = code
        if spec in ("\n", "Enter"):
            p.update({"key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13, "text": "\r"})
        elif spec in ("\t", "Tab"):
            p.update({"key": "Tab", "code": "Tab", "windowsVirtualKeyCode": 9, "text": "\t"})
        elif spec in (" ", "Space"):
            p.update({"key": " ", "code": "Space", "windowsVirtualKeyCode": 32, "text": " ",
                      "unmodifiedText": " "})
        elif len(spec) == 1:
            p["text"] = spec
            p["unmodifiedText"] = spec
        return p

    def type_text(self, text, delay=0.0):
        for ch in text:
            p = self._key_params(ch)
            self.call("Input.dispatchKeyEvent", dict(p, type="keyDown"))
            self.call("Input.dispatchKeyEvent", {k: v for k, v in p.items()
                                                if k not in ("text", "unmodifiedText")} | {"type": "keyUp"})
            if delay:
                time.sleep(delay)
        return len(text)

    # --- bsk-compatible surface --------------------------------------------
    def bsk(self, *args):
        a = [str(x) for x in args]
        cmd = a[0]
        try:
            return self._dispatch(a)
        finally:
            if cmd in ("evaluate", "click", "fill", "focus", "navigate") and PACE:
                time.sleep(PACE)

    def _dispatch(self, a):
        cmd = a[0]
        if cmd == "evaluate":
            v = self.evaluate(a[1])          # 引擎传进来的表达式已经自带 JSON.stringify 包装
            return v if isinstance(v, str) else json.dumps(v)
        if cmd == "click":
            tgt = a[1]
            if tgt.startswith("@"):
                sel = f'[data-tl-ref="{tgt.lstrip("@")}"]'
            else:
                sel = tgt
            self.real_click(sel)
            time.sleep(0.8)
            return "ok"
        if cmd == "focus":
            self.evaluate("(()=>{const e=document.querySelector(%s); if(e) e.focus(); return !!e;})()"
                          % json.dumps(a[1]))
            return "ok"
        if cmd == "fill":
            sel, val = a[1], a[a.index("--value") + 1]
            for attempt in range(3):
                self.evaluate("(()=>{const e=document.querySelector(%s); if(e){e.focus(); e.select&&e.select();} return !!e;})()" % json.dumps(sel))
                if attempt % 2 == 0:
                    self.call("Input.insertText", {"text": val})     # 普通 input/textarea：一次插入
                else:
                    self.type_text(val)                              # 兜底：逐字真实按键
                got = self.evaluate("(()=>{const e=document.querySelector(%s);"
                                    "return e ? (e.value!==undefined ? e.value : (e.innerText||'')) : null;})()"
                                    % json.dumps(sel))
                if got is not None and str(got).strip() != "":
                    return "ok"
                time.sleep(0.4)
            return "ok"                                              # 交给引擎的读回断言判（它比自己重试更严格）
        if cmd == "press":
            self.assert_visible()
            sel = a[a.index("--selector") + 1] if "--selector" in a else None
            key = a[1]
            if sel:
                self.evaluate("(()=>{const e=document.querySelector(%s); if(e) e.focus(); return !!e;})()" % json.dumps(sel))
            p = self._key_params(key)
            self.call("Input.dispatchKeyEvent", dict(p, type="keyDown"))
            self.call("Input.dispatchKeyEvent", {k: v for k, v in p.items()
                                                if k not in ("text", "unmodifiedText")} | {"type": "keyUp"})
            return "ok"
        if cmd == "navigate":
            self.call("Page.navigate", {"url": a[1]})
            return "ok"
        if cmd == "wait-ms":
            time.sleep(float(a[1]) / 1000.0)
            return "ok"
        if cmd == "window":
            w, h = int(a[a.index("--width") + 1]), int(a[a.index("--height") + 1])
            self.call("Emulation.setDeviceMetricsOverride",
                      {"width": w, "height": h, "deviceScaleFactor": 1, "mobile": False})
            return "ok"
        if cmd in ("session", "blur", "scroll-to", "select", "get-html", "snapshot", "upload", "wait-for-navigation"):
            if cmd == "upload":
                sel = a[1]
                f = a[a.index("--file") + 1]
                return self.set_files(sel, [f])
            return "ok"
        raise RuntimeError(f"tl_cdp: unsupported bsk command {cmd!r}")

    def observe(self):
        """合成 ARIA 快照（带 @eN + 所在分区名），满足引擎 _find_ref 的谓词。"""
        lines = self.evaluate("""(()=>{
          const out=[]; let n=0;
          const secOf=(el)=>{let p=el; while(p&&p!==document.body){const s=p.getAttribute&&p.getAttribute('data-sectionname');
            if(s) return s; p=p.parentElement;} return '';};
          const name=(el)=>((el.getAttribute('aria-label')||el.getAttribute('placeholder')||el.innerText||el.value||'')+'').trim().replace(/\\s+/g,' ').slice(0,70);
          const role=(el)=>{const t=el.tagName.toLowerCase();
            if(t==='button') return 'button';
            if(t==='input') return (el.type==='checkbox'?'checkbox':(el.type==='radio'?'radio':'textbox'));
            if(t==='textarea') return 'textbox';
            if(t==='a') return 'link';
            if(t==='select') return 'combobox';
            return el.getAttribute('role')||'generic';};
          for(const el of document.querySelectorAll('button,input,textarea,a[href],[role="option"],[role="button"],[role="combobox"],[contenteditable="true"]')){
            const r=el.getBoundingClientRect(); if(r.width<1||r.height<1) continue;   // portal 里的浮层是 fixed → offsetParent 为 null，不能用它判可见
            n++; const ref='e'+n; el.setAttribute('data-tl-ref', ref);
            out.push('@'+ref+' '+role(el)+' "'+name(el)+'" section='+secOf(el));
          }
          return out.join('\\n');})()""")
        return lines or ""

    def set_files(self, selector, files):
        self.call("DOM.enable")
        doc = self.call("DOM.getDocument", {"depth": -1})["result"]["root"]["nodeId"]
        node = self.call("DOM.querySelector", {"nodeId": doc, "selector": selector})["result"]["nodeId"]
        if not node:
            raise RuntimeError(f"set_files: no node for {selector}")
        self.call("DOM.setFileInputFiles", {"files": files, "nodeId": node})
        return f"uploaded:{len(files)}"


# ------------------------------------------------------------------ install
def install(port=CDP_PORT):
    import tl_engine as E

    cdp = CDP(port)
    E.B = type("B", (), {"bsk": staticmethod(cdp.bsk), "observe": staticmethod(cdp.observe)})()
    E.start_session = lambda *a, **k: "cdp"
    E.stop_cors = lambda *a, **k: None
    E.goto = _goto_factory(cdp)
    E.add_images = lambda files, *a, **k: cdp_add_images(E, cdp, files)
    E.add_images_by_link = lambda urls, *a, **k: cdp_add_images_by_link(E, cdp, urls)
    E._bsk_type = lambda fieldid, value: cdp_type_burst(E, cdp, fieldid, value)
    E.pick_warranty = lambda t, p: cdp_pick_warranty(E, cdp, t, p)
    E._reveal = _reveal_factory(E, cdp)
    E.click_section_next = lambda ctx: cdp_click_section_next(E, cdp, ctx)
    _orig_fill_rich = E.fill_rich
    E.fill_rich = lambda fid, val, attempts=3: (
        _ensure_details_active(E, cdp) or True, _orig_fill_rich(fid, val, attempts))[1]
    E._cdp = cdp
    return E


def _section_btn_marker(cdp, section_substr, text="Next"):
    """在该分区里找到文本为 Next 的按钮并打标记；返回 True/False。"""
    js = """(()=>{const ctx=%s; const t=%s;
      const s=[...document.querySelectorAll('[data-sectionname]')].find(x=>new RegExp(ctx,'i').test(x.getAttribute('data-sectionname')||''));
      if(!s) return false;
      const b=[...s.querySelectorAll('button')].find(x=>new RegExp('^'+t+'$','i').test((x.textContent||'').trim()));
      if(!b) return false; b.setAttribute('data-tl-secnext','1'); return true;})()"""
    return bool(cdp.evaluate(js % (json.dumps(section_substr), json.dumps(text))))


def _section_disabled(cdp, section_substr):
    return cdp.evaluate("""(()=>{const s=[...document.querySelectorAll('[data-sectionname]')]
      .find(x=>new RegExp(%s,'i').test(x.getAttribute('data-sectionname')||''));
      return s ? s.getAttribute('data-sectionisdisabled')==='true' : null;})()""" % json.dumps(section_substr))


def _ensure_details_active(E, cdp, timeout=20.0):
    """详情区（富文本所在）在属性区提交前是 disabled —— 那时打字会被应用回滚（实测真身 0）。

    必须用**真鼠标**点属性区的 Next（JS .click() 实测无效）→ 详情区解锁。
    """
    if _section_disabled(cdp, "Product Details") is False:
        return True
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _section_btn_marker(cdp, "Product Attributes"):
            try:
                cdp.real_click('[data-tl-secnext="1"]')
            except Exception:
                pass
            cdp.evaluate("document.querySelectorAll('[data-tl-secnext]').forEach(e=>e.removeAttribute('data-tl-secnext'))")
            time.sleep(1.5)
            if _section_disabled(cdp, "Product Details") is False:
                return True
        else:
            time.sleep(1.0)
    return _section_disabled(cdp, "Product Details") is False


def cdp_click_section_next(E, cdp, ctx_substr):
    """分区 Next：一律**真鼠标点击**（实测 JS .click() 对这种 react-aria 按钮无效）。"""
    if _section_btn_marker(cdp, ctx_substr):
        try:
            cdp.real_click('[data-tl-secnext="1"]')
            time.sleep(1.6)
            return "real"
        finally:
            cdp.evaluate("document.querySelectorAll('[data-tl-secnext]').forEach(e=>e.removeAttribute('data-tl-secnext'))")
    out = cdp.evaluate("""(()=>{const s=[...document.querySelectorAll('[data-sectionname]')]
      .find(x=>new RegExp(%s,'i').test(x.getAttribute('data-sectionname')||''));
      const b=s&&[...s.querySelectorAll('button')].find(x=>/^Next$/i.test((x.textContent||'').trim()));
      if(!b) return 'no-next'; b.click(); return 'clicked';})()""" % json.dumps(ctx_substr))
    if "clicked" not in str(out):
        raise E.StepError(f"section Next [{ctx_substr}] not found")
    time.sleep(1.6)
    return "js"


def _reveal_factory(E, cdp):
    """等元素出现再滚动到视口（引擎原版是一查不到就报错）。

    实测：属性区里选完 Warranty 之后，详情区的富文本容器会**重新渲染**——那一瞬间
    `[data-fieldid="title"] .public-DraftEditor-content` 不存在（实测 dom=null、页面只剩 2 个
    编辑器），于是引擎报 `element not found`，之后连发全丢 → 真身 0。等 0.5–2s 就回来了。
    """
    def _reveal(sel, timeout=20.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            ok = cdp.evaluate("""(()=>{const e=document.querySelector(%s); if(!e) return false;
              e.scrollIntoView({block:'center'}); return true;})()""" % json.dumps(sel))
            if ok:
                return True
            time.sleep(0.5)
        raise E.StepError(f"element not found: {sel}（等了 {timeout:.0f}s）")
    return _reveal


def cdp_pick_warranty(E, cdp, type_text, period_text):
    """Warranty = 容器内两个 react-aria 下拉（类型 / 有效期）。

    引擎原版依赖页面内打 id 标记 + observe 找 ref，在 CDP 下不稳；这里改成：
    JS 点 selector 索引 → 选项出现就点；没出现再用真鼠标点同一个 selector。
    """
    fid = "Attribute.warranty"
    for idx, text in ((0, type_text), (1, period_text)):
        opened = False
        for how in ("js", "real"):
            if how == "js":
                opened = cdp.evaluate(
                    """(()=>{const w=document.querySelector('[data-fieldid="%s"]');
                       const s=[...w.querySelectorAll('.ZorkInput__input-selector')];
                       if(!s[%d]) return false; if(s[%d].getAttribute('aria-expanded')==='true') return true;
                       s[%d].click(); return true;})()""" % (fid, idx, idx, idx))
            else:
                tag = "tlw%d" % idx
                cdp.evaluate("""(()=>{const w=document.querySelector('[data-fieldid="%s"]');
                  const s=[...w.querySelectorAll('.ZorkInput__input-selector')];
                  if(s[%d]) s[%d].setAttribute('data-tl-tag','%s'); return true;})()""" % (fid, idx, idx, tag))
                try:
                    cdp.real_click('[data-tl-tag="%s"]' % tag)
                    opened = True
                except Exception:
                    opened = False
            time.sleep(1.2)
            n = cdp.evaluate("""[...document.querySelectorAll('[role="option"]')]
                .filter(e=>e.getBoundingClientRect().width>0).length""") or 0
            if n:
                break
        if not opened or not n:
            raise E.StepError(f"warranty[{idx}] 下拉打不开（{text}）")
        if not E._click_option(text, verify=(fid, text)):
            raise E.StepError(f"warranty[{idx}] 选项 '{text}' 点了没落值")
        time.sleep(0.8)
    return True


def _goto_factory(cdp):
    """导航并**等到文档就绪 + 页面安静**（实测：不等就点，SPA 的表格/向导还没挂好 →
    例如"从列表重开草稿"找不到链接）。"""
    def _goto(url, *a, **k):
        cdp.call("Page.navigate", {"url": url})
        for _ in range(80):
            time.sleep(0.5)
            try:
                if cdp.evaluate("document.readyState === 'complete'"):
                    break
            except Exception:
                pass
        time.sleep(2.0)
        return "ok"
    return _goto


def cdp_type_burst(E, cdp, fieldid, value):
    """富文本写手（CDP 版）：**一次连发整串按键，不等回复**。

    实测依据（真站 762 字）：连发 = 精确命中（0.6–1.8 ms/字）；逐字等回复（60 ms/字）反而会被
    应用自己的重渲染打断（实测 776 字 → 849 字）。所以这里绝不加节流。

    ⚠️ 但连发**必须先确认真焦点在编辑器里**（实测：属性区下拉刚交互完时焦点会飘，连发就全丢 →
    真身 0）。所以这里 focus 后校验 activeElement，失败重试；仍失败退回逐字慢路。
    """
    sel = E._rich_sel(fieldid)
    cdp.assert_visible()
    focus_js = ("""(()=>{const e=document.querySelector(%s); if(!e) return false; e.focus();
      const a=document.activeElement; return !!(a && (a===e || e.contains(a)));})()""" % json.dumps(sel))
    # ① 等编辑器"稳定"：给它打个标记，0.8s 后标记还在同一个节点上 → React 这次重挂载结束了。
    #    实测：属性区交互完，详情区的富文本容器会整段重挂载，这时打字全丢（DOM 有字、真身 0）。
    def stable(timeout=15.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            E._reveal(sel)
            cdp.evaluate("""(()=>{const e=document.querySelector(%s); if(e) e.setAttribute('data-tl-stable','1'); return true;})()"""
                         % json.dumps(sel))
            time.sleep(0.8)
            if cdp.evaluate("""!!document.querySelector(%s + '[data-tl-stable="1"]')""" % json.dumps(sel)):
                return True
        return False

    for attempt in range(4):
        stable()
        if not cdp.evaluate(focus_js):
            time.sleep(0.6)
            continue
        t0 = time.time()
        for ch in value:
            p = cdp._key_params(E._KEYMAP.get(ch, ch))
            cdp.post("Input.dispatchKeyEvent", dict(p, type="keyDown"))
            cdp.post("Input.dispatchKeyEvent", {k: v for k, v in p.items()
                                                if k not in ("text", "unmodifiedText")} | {"type": "keyUp"})
        cdp.drain()
        dt = time.time() - t0
        time.sleep(0.8)
        n = cdp.evaluate("(()=>{const e=document.querySelector(%s); return e?(e.innerText||'').length:0;})()"
                         % json.dumps(sel)) or 0
        if n:
            return {"ok": True, "writer": "cdp-burst", "chars": len(value),
                    "seconds": round(dt, 2), "attempt": attempt + 1}
    return {"ok": False, "err": "burst 落不进编辑器（节点一直在重挂载？）"}


def cdp_add_images_by_link(E, cdp, urls, per_timeout=90.0):
    """URL 直塞（CDP 版）：平台自己去抓 URL 并重新托管 → 零本地下载、≈3.8s/张（bsk 时代实测）。

    与引擎版的差别只有一个：那两个按钮（`Add Image Link` tab / `Add Image`）必须**真鼠标点**
    —— 实测这类 react-aria 按钮 JS `.click()` 无效。其余（link-input 填值、计数判据）照旧。
    """
    import re as _re

    def click_btn(pattern):
        ok = cdp.evaluate("""(()=>{const s=[...document.querySelectorAll('[data-sectionname]')]
          .find(x=>/Images/i.test(x.getAttribute('data-sectionname')||''));
          const b=s&&[...s.querySelectorAll('button')].find(x=>new RegExp(%s,'i').test((x.innerText||'').trim()));
          if(!b) return false; b.setAttribute('data-tl-imgbtn','1'); return true;})()""" % json.dumps(pattern))
        if not ok:
            return False
        try:
            cdp.real_click('[data-tl-imgbtn="1"]')
        finally:
            cdp.evaluate("document.querySelectorAll('[data-tl-imgbtn]').forEach(e=>e.removeAttribute('data-tl-imgbtn'))")
        return True

    if not urls:
        raise E.StepError("add_images_by_link: 没有 URL")
    for _ in range(30):                     # 图片分区懒加载
        if cdp.evaluate("""(()=>{const s=[...document.querySelectorAll('[data-sectionname]')]
            .find(x=>/Images/i.test(x.getAttribute('data-sectionname')||''));
            return !!(s&&[...s.querySelectorAll('button')].find(x=>/^Add Image Link$/i.test((x.innerText||'').trim())));})()"""):
            break
        time.sleep(0.5)
    # 打开 URL 面板：真身是 radio `#upload-link`（实测：JS click 就有效，**disabled 分区里也能开**；
    # 引擎版去点文本为 "Add Image Link" 的按钮 —— 那是 tab 标签，点它不会挂载 link-input）。
    if not cdp.evaluate("!!document.querySelector('input.link-input')"):
        cdp.evaluate("""(()=>{const r=document.querySelector('#upload-link'); if(!r) return false;
          (r.closest('label')||r).click(); r.click(); return true;})()""")
        for _ in range(12):
            time.sleep(0.8)
            if cdp.evaluate("!!document.querySelector('input.link-input')"):
                break
        else:
            raise E.StepError("images: 切到 Add Image Link 面板失败（link-input 没出现）")

    def click_add_image():
        ok = cdp.evaluate("""(()=>{const s=[...document.querySelectorAll('[data-sectionname]')]
          .find(x=>/Images/i.test(x.getAttribute('data-sectionname')||''));
          const b=s&&[...s.querySelectorAll('button')].find(x=>/^Add Image$/i.test((x.innerText||'').trim()));
          if(!b) return false; if(b.disabled) return 'disabled'; b.click(); return true;})()""")
        if ok is not True:
            # 备选：真鼠标点（有些按钮 JS click 不触发）
            tagged = cdp.evaluate("""(()=>{const s=[...document.querySelectorAll('[data-sectionname]')]
              .find(x=>/Images/i.test(x.getAttribute('data-sectionname')||''));
              const b=s&&[...s.querySelectorAll('button')].find(x=>/^Add Image$/i.test((x.innerText||'').trim()));
              if(!b) return false; b.setAttribute('data-tl-imgbtn','1'); return true;})()""")
            if tagged:
                try:
                    cdp.real_click('[data-tl-imgbtn="1"]')
                finally:
                    cdp.evaluate("document.querySelectorAll('[data-tl-imgbtn]').forEach(e=>e.removeAttribute('data-tl-imgbtn'))")
        return ok

    ok = 0
    for idx, u in enumerate(urls, 1):
        before = E._image_count()
        u = _re.sub(r"/(s-[a-z]+)\.file$", "/s-zoom.file", u)   # 必须 ≥600px 档，否则平台静默禁用 Submit
        cdp.bsk("fill", "input.link-input", "--value", u)
        time.sleep(0.4)
        click_add_image()
        t0 = time.time()
        while time.time() - t0 < per_timeout:
            time.sleep(1.5)
            if E._image_count() > before:
                ok += 1
                break
        else:
            raise E.StepError(f"images: URL 直塞第 {idx} 张超时（{u[:70]}）")
    print(f"images via link(CDP): {ok}/{len(urls)}", flush=True)
    return ok


def cdp_add_images(E, cdp, files):
    """CDP 版图片注入：隐藏 input 也能喂，不需要 cors_http。"""
    E._check_images(files)
    for _ in range(40):                      # 图片分区是懒加载的
        if cdp.evaluate("!!document.querySelector('[data-sectionname*=Images] input[type=file]')"):
            break
        time.sleep(0.5)
    else:
        raise E.StepError("images section / file input never appeared")
    abs_files = [os.path.abspath(f) for f in files]
    print(cdp.set_files("[data-sectionname*=Images] input[type=file]", abs_files), flush=True)
    count_js = ("(()=>{const s=[...document.querySelectorAll('[data-sectionname]')].find(s=>/Images/.test(s.getAttribute('data-sectionname')));"
                "if(!s) return 0; const m=/(\\d+)\\s+Images?/i.exec(s.innerText||''); if(m) return parseInt(m[1],10);"
                "return [...s.querySelectorAll('img')].filter(i=>/covers_images|blob:/.test(i.src||'')).length;})()")
    n = 0
    for _ in range(20):
        time.sleep(2)
        n = int(cdp.evaluate(count_js) or 0)
        if n >= len(files):
            break
    if n < len(files):
        raise E.StepError(f"images not attached: {n} of {len(files)}")
    print(f"images attached: {n}", flush=True)
    return n
