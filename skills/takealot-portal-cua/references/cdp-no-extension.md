# 无扩展路线：Hermes 自带浏览器 / 裸 CDP 驱动卖家后台（2026-10-09 实测）

> 目的：判断**能不能不要 BrowserSkill 扩展**（扩展要人工装、官方升级、隔离世界一堆坑）。
> 结论：**能驱动**，但**只有一条富文本写法正确**，且**服务端落库尚未端到端验证**。

## 1. 富文本：唯一正确的 CDP 写法（真站实测）

**必须用原始 `Input.dispatchKeyEvent`（`keyDown` + `keyUp`，带 `key` / `code` / `windowsVirtualKeyCode`）**。
**同一串文本、同一台机、真站 762 字描述：**

| 路 | ms/字 | 结果 |
|---|---|---|
| `bsk press` 逐字（现方案） | 152 | ✅ 精确（末字落后） |
| agent-browser `keyboard type` 整串 | 33–155 | ❌ **乱序**（局部颠倒/打乱，长度也会翻几倍） |
| agent-browser 逐字 `press`（每次一进程） | 322 | ✅ 精确（末字落后） |
| **裸 CDP `dispatchKeyEvent` 整串** | **0.6–5.6** | ✅ 精确（762 字 → 761/762，只差最后一个字符） |

「末字落后」= Draft 的既定行为（本技能早就记录，bsk 也一样），用现有收尾逻辑（轮询 → 补尾）处理。

## 2. 根因：keydown 的有无（页面埋探针实测，`isTrusted` 全 true）

| 路 | 产生的输入事件（每字） |
|---|---|
| `bsk press` | `keydown` + `keypress` + `beforeinput` + `input` |
| 裸 CDP `dispatchKeyEvent` | `keydown` + `keypress` + `beforeinput` + `input` |
| **agent-browser `keyboard type`** | **只有 `beforeinput` + `input`（没有 keydown/keypress）** ← 乱序根因 |
| 负对照 | 页内合成事件 = untrusted；CDP `insertText` = 整串只有 1 个 beforeinput |

⇒ 规则：**这个平台的 Draft 编辑器要 keydown/keypress 才会把字按顺序落进编辑器状态**。
凡是「只发 beforeinput/input」的批量输入工具（含 agent-browser 的 `keyboard type`、`fill`）**不要用来写富文本**。

## 3. 登录态：无扩展怎么拿到

- Chrome ≥136 **禁止默认 profile + `--remote-debugging-port`** → 必须用**非默认 user-data-dir**。
- 两条路：
  1. **快照**：完全退出 Chrome → 拷 profile（Hermes 的 `browser.use_real_profile` 就是这条）。
  2. **热拷贝**（Chrome 不用退，实测可行）：拷 `Local State` + `Default/{Cookies, Preferences, Local Storage, IndexedDB, Session Storage, Service Worker}` 到新目录 → 用**真 Chrome 二进制**起：
     `"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --user-data-dir=<copy> --remote-debugging-port=9222 --no-first-run --no-default-browser-check`
     ⚠️ 第一次拷 `Local Storage` 可能拿到不一致的 leveldb（登录态丢失，页面 302 `/login`）→ **重拷一次即恢复**（实测）。
- **卖家后台的凭据有一半在 localStorage**：`usr_st_auth` / `usr_st_usr` / `usr_st_slr`，另加 `taid`(JWT) cookie。**少任何一半都登录不上**（只拷 Cookies 会 302 到 `/login`）。
- ⚠️ **Chrome for Testing 装不了拷来的登录态**：Keychain 服务名不同（`Chromium Safe Storage` ≠ `Chrome Safe Storage`）。要拷贝就必须用**真 Chrome 二进制**；要零拷贝就**一次性在 Hermes 的 Chromium 里人工登录**（登录态自己续）。
- ⚠️ **绝不把 cookie/token 值读进日志或对话**（只读键名）。

## 4. 闭环结果（2026-10-09，无扩展，真站提交）

**端到端跑通并服务端回读 PASS（两条）**：

| 场景 | 提交 | 服务端回读 | 耗时 |
|---|---|---|---|
| A 自建（本地图 8 张，描述 776 字） | 5623618 In Review | description 776 ✅ | **109.7s** |
| B 拆解（复用源 listing 5 张，文案重写 856 字） | 5623878 In Review | description 856 ✅ | **118.9s** |

（bsk 口径 283.6–340.7s → **快 2.3–3.1×**。）B 的图走了「下载到本地 → `setFileInputFiles`」= 33.3s；
若换成 **URL 直塞**（`Add Image Link` tab）可再省 20–25s（-- 引擎的 `add_images` 在本端口里统一走文件上传，
要省这一步得单独实现 URL 路）。

**分段（A 那次）**：新建页+硬重置 13.4s / 类目+变体 11.9s / 属性(含 Warranty 两下拉) 19.4s / 富文本 ≈2s /
图片 8 张 29.6s / 分区提交 4.9s / 断言 0.3s / 进预览 6.1s / 提交 23.9s。

## 4b. 三个必踩的坑（都实测，按重要性排）

1. **页面必须可见！** Chrome 在 `document.visibilityState != 'visible'`（窗口被遮挡/最小化）时
   **直接丢弃键盘事件** —— 现象是「类目/填值/图片全正常，只有打字静默 0 字」，能骗你查一整天。
   处置：连上后 `Page.bringToFront()` + `Emulation.setFocusEmulationEnabled{enabled:true}`，
   **并且打字前断言 `document.visibilityState === 'visible'`**（不可见就报明确错误，不要静默继续）。
   无人值守场景用 `--headless=new`（页面恒为 visible）。
2. **分区 Next 必须真鼠标点**：`data-sectionname` 里的 Next 用 JS `.click()` **无效**
   （按钮看着正常、也不报错，但向导不推进）；必须用 `Input.dispatchMouseEvent` 在按钮中心按下/抬起。
   同理属性区的 Next 不点 → 详情区一直 `data-sectionisdisabled=true`；
3. **富文本写手 = 一次连发整串**（`Input.dispatchKeyEvent` 带 `text`，keyDown+keyUp，**不等回复**）。
   逐字等回复（60 ms/字）反而被应用自己的重渲染打断（实测 776 字 → 849 字）。
   连发前先确认真焦点在编辑器里、且节点稳定（打标记 0.8s 后还在同一节点）。

## 4c. 未验证 / 未做

| 能力 | 状态 |
|---|---|
| 下拉 / react-aria combobox、图片 URL 直塞、分区提交链 | ✅ 已跑通（见上） |
| Windows 侧 | ✅ 已验证：Edge 154 + 微软拼音激活下，CDP 连发 53 字（含 `$ ( ) [ ] : ;`）逐字精确；
  CDP 往返 1.15–1.59 ms、打字 9.1–9.7 ms/字（对照页）、**不受输入法影响** |
| 场景 B（拆解重塑） | ⬜ 未跑 |

## 5. 已验证 / 未验证（别过度声称）

| 能力 | 状态 |
|---|---|
| 类目三级选择 + 分区 Next（JS `el.click()`）→ 27 字段渲染 | ✅ 真站实测 |
| 普通 `<input>` 填值、`[data-fieldid]` 定位 | ✅ 真站实测 |
| Draft 富文本写入（title/subtitle/description）**编辑器状态**精确 | ✅ 真站实测（762 字仅末字落后） |
| **服务端落库** | ❌ **未验证**（草稿不落富文本 → 判据仍是提交后 `verify_persisted.py`） |
| 下拉 / react-aria combobox、图片 URL 直塞、分区提交链 | ⬜ 未在 CDP 路跑通（bsk 时代已跑通，逻辑同构） |
| `tl_engine.py` 移植（现在是 bsk：`_js` / `press` / `_click_ref`） | ⬜ 未做 |

## 5. 环境坑（会让人误判成「路不通」）

- **Clash fake-ip**：域名解析成 `198.18.x`，Hermes 的 URL 策略判成「内网地址」→ **自带浏览器拒绝导航任何站点**。`browser.allow_private_urls` 是**进程内缓存**，改完要**重启 Hermes**。裸 CDP 不走这层，不受影响。
- 直连 9222：CDP WebSocket 会被 Origin 检查挡（403）→ 起 Chrome 加 `--remote-allow-origins=*`，或握手时**不发 Origin**（websocket-client：`suppress_origin=True`）。
- `agent-browser click <selector>` 对**视口外**元素不可靠（实测点到了侧栏导航，页面跳走）。富文本字段用 `focus`（`agent-browser focus <sel>` 有效，`activeElement` 会落到该字段），不要用 click。
- Hermes 自带 browser 的 `keyboard type` 走 agent-browser；要精确富文本必须绕过它、直接发 CDP（`cdp('Input.dispatchKeyEvent', ...)`）。

## 6. 复现脚本（本机实测用过的，都在 `~/.hermes/cache/scratch/`）

`portal_probe.py`（类目→字段）· `portal_cdp_scale.py`（762 字精确+计时）· `portal_cdp_pace.py`（节奏对比）·
`portal_perchar2.py`（逐字 press）· `event_compare.py`（keydown 有无对比）· `drafttest/`（本地 Draft 对照页）。
