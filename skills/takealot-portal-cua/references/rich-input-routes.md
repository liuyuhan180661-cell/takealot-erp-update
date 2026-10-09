# 富文本写入：哪条路**真能持久**（title / description 的 Draft.js 编辑器）

> **结论先行**：**只有一条自动路 —— `bsk press` 逐字真实按键**（`bsk` CLI + **BrowserSkill 官方浏览器扩展**是本技能唯一依赖；
> 扩展是**必须**的，缺它 `bsk` 什么都做不了；除它之外**不需要任何额外扩展**）。
> 判据永远只有一个：**「提交后回读服务端」**（`scripts/verify_persisted.py <submission_id>`）——
> 页面状态（Draft 的 `editorState`）和 DOM 都**不算**：JS 可以把它们改得一切正常，而服务端仍是空的。

## 1. 实测对照（Intel Mac + Chrome + bsk 0.3.1，2026-09-26）

| 路 | 怎么触发 | 编辑器状态 | 服务端持久 | 吞吐 | 额外依赖 |
|---|---|---|---|---|---|
| ✅ **bsk 逐字真实按键（唯一真路）** | `bsk press <键> --selector '[data-fieldid="description"] .public-DraftEditor-content'` | ✅ 精确（实测 477/477；标点/大小写/换行/破折号全过） | ✅ 已提交 listing 回读 **544 字** | **152 ms/字**（477 字 ≈ 104s） | 无（只要 bsk 本身） |
| ❌ fiber 注入 `EditorState`+`onChange` | JS 直接改 React 状态 | 有的能改、有的不动 | ❌ **不持久** | — | 无 |
| ❌ `bsk fill` | CLI 一次填 | 对 title 常写不进 | ❌ 不持久 | — | 无 |
| ❌ `document.execCommand('insertText')` / 合成 `beforeinput`+`paste` | 页面内造事件 | 有时能改状态 | ❌ 不持久 | — | 无 |
| ❌ CDP `Input.insertText` | CDP 直插（IME 式） | 只改 DOM | ❌ 不持久 | — | 需自带扩展（**我们不再交付扩展**） |
| ❌ OS 级 ⌘V 粘贴 | pbcopy + 系统按键 | 本机 3/3 轮 **0 字符**（Chrome 吞掉） | ❌ | — | — |

**为什么只有"真实按键"持久**：只有浏览器**自己产生的键盘输入事件**才会走应用自己的 `onChange` → 才会发到服务端；
JS 造的事件、直接改状态、CDP 的 IME 式插入，都绕过了这一层。

> 曾经评估过一条 CDP 加速件（自带扩展 + `Input.dispatchKeyEvent`，8 ms/字，功能等效）——
> **已下线、不再交付**：省下的时间换不来多一个部件的失效面（隔离世界读不到主世界变量、改代码要重载扩展、
> 与调试器冲突、客户机上没人替你排扩展兼容问题）。**要不要再引入它：不要。**

## 2. 收尾规程（不做就会得到"看起来对"的假结果）

打完字**不要立刻判成败** —— Draft 的**最后一次输入事件总落后一步**（实测：打完 543 读到 542）：

| 现象 | 正确动作 | 禁止动作 |
|---|---|---|
| 短 1~40 字 | 轮询等状态落定（最多 30s）→ 仍缺则**逐字补尾**（追加实测有效） | 别立刻"再打一遍整段"（会变重复） |
| 多出 1~N 字 | **全选 + `bsk press Delete` 清空后重打**（最多 1 次） | ❌ `bsk press Backspace` **实测无效**（状态不变），拿它做减法只会空转 |
| 末尾 ±2 字差 | 引擎**如实打警告并接受**（不伪装精确）→ 提交后必须跑 `verify_persisted.py` 复核 | 别为了 1 个字把整条 listing 卡死 |

## 3. 开工前的自检（谁跑、什么依据，都留痕）

```sh
bsk --version          # 命令在
bsk doctor             # 守护进程 + 扩展已连（有 fail/warn 先修）
python3 scripts/preflight.py   # 会话 / 登录态 / 新建页 / 图片服务逐项 PASS
```

判据（写死，**不许猜**）：
- **bsk 不可用 → 先修依赖**（见 `bsk-setup.md`），**不要**去找替代输入路（上面那张表已经说明它们都不持久）。
- 引擎日志里出现 `bsk-press 不可用` = 环境层问题（会话掉了 / 页面变了），先 `preflight.py` 定位。

## 4. 环境速查

| 客户机情况 | 正确动作 |
|---|---|
| 只装了 bsk 官方 CLI + 扩展 | **就是它，直接跑**（交付默认，唯一依赖） |
| 没窗口 / `bsk status` 里没有浏览器 | 先修环境：见 `pitfalls.md` G4/G5（残留 headless 实例会 handoff 掉 `open -a`） |
| 页面被踢回 `/login` | 人工登录一次（引擎不碰账号密码）；`preflight.py` 会先报出来 |

## 5. 更新的路（2026-10-09）：无扩展 · 裸 CDP 原始按键

上表是 **bsk 时代**的口径（`bsk press` 仍是引擎现用的真路）。后来实测发现**第二条真路**：
不装任何扩展、用 CDP 直连（Hermes 自带浏览器 / 裸 CDP）时，**原始 `Input.dispatchKeyEvent`（keyDown+keyUp，带 key/code/vk）**
能精确写入同一字段，**762 字 0.6–5.6 ms/字**（vs bsk 152 ms/字）；而 agent-browser 的高层 `keyboard type`
**只发 beforeinput/input、不发 keydown/keypress → 字会乱序**。
细节、登录态怎么来、已验证/未验证清单见 **`cdp-no-extension.md`**。
> 口径：编辑器状态已验证精确；**服务端落库仍未端到端验证** → 判据依旧是本节第 1 条的 `verify_persisted.py`。
