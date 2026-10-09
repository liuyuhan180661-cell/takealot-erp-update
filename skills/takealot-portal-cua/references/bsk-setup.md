# 依赖：BrowserSkill（本技能唯一的外部依赖）

> **一句话**：本技能**只依赖 BrowserSkill**（`bsk` CLI + 浏览器扩展）驱动浏览器；
> **技能包不打包 bsk 本体、也不交付任何自制扩展** —— 第三方工具由官方维护升级，我们只依赖它、并在现场验证它。

| 项 | 值 |
|---|---|
| 官方仓库 | **https://github.com/Tencent/BrowserSkill** |
| 作用 | 让 agent 通过本地 CLI 驱动**用户已登录的真实 Chrome/Edge**（读 DOM、发真实按键、上传文件），不用截图猜坐标 |
| 为什么只有它 | 实测所有"页面内注入"路线（fiber 注入 / `insertText` / 合成事件）**都不落库**；只有浏览器**真实产生的输入事件**才可能持久 → `bsk press` 逐字是唯一自动可用路（见 `rich-input-routes.md`） |
| 交付方负责 | 扩展由**人**在浏览器里装好（商店一键）；CLI 与 PATH 装好 |
| 本技能负责 | 开工前**自检**（`bsk doctor` / `preflight.py`）+ 不可用时**明确报错**，不静默降级 |

## 一、装 CLI（官方命令，三平台）

**macOS / Linux**：

```sh
curl -fsSL https://raw.githubusercontent.com/Tencent/BrowserSkill/main/install.sh | sh
export PATH="${BSK_INSTALL_DIR:-$HOME/.local/bin}:$PATH"
```

**Windows PowerShell**：

```powershell
irm https://raw.githubusercontent.com/Tencent/BrowserSkill/main/install.ps1 | iex
```

默认装在 `~/.local/bin`。装完**在真正会用它的那个终端 / agent 环境里**确认：

```sh
bsk --version
```

> 已在跑的 agent 找不到 `bsk` → **重启该 agent 会话**让 PATH 生效，或改用二进制绝对路径。

## 二、让 agent 自己装（推荐口径：客户零操作）

客户端不需要我们发脚本/安装器。把下面这句**原话**交给客户的 agent，它照官方文档装完并自检：

```
Set up browser-skill on this machine by following
https://raw.githubusercontent.com/Tencent/BrowserSkill/main/AGENT_INSTALL.md
```

符合交付原则：**官方文档是唯一真源**，我们只负责"装没装好"的判定。

## 三、装浏览器扩展（必须人工：交付方或客户自己装）

- Chrome：[Chrome Web Store](https://chromewebstore.google.com/detail/hhcmgoofomhgciiibhipgmgkgnoenaoi)
- Edge：[Edge Add-ons](https://microsoftedge.microsoft.com/addons/detail/browserskill/emacgiaaaiojkkpkddmmdfhmokgmnikg)

装好后**打开扩展弹窗 → 启用本地连接**，再启 CLI，然后看状态。要求浏览器 **Chromium 125+**（Chrome / Edge 均可）。

## 四、给 agent 装 bsk 自己的 skill（一条命令）

```sh
bsk install-skill --harness hermes --json     # 幂等：已装会跳过，要覆盖加 --force
bsk install-skill --list                      # 看支持的 harness 与目标路径
```

Hermes 的目标路径是 `$HERMES_HOME/skills`（本机 `~/.hermes/skills`）。它也认 Codex / Claude Code / Cursor / OpenClaw / WorkBuddy 等；`--all` 一把装全。非交互环境装完**重启 agent 会话**。

## 五、验收（客户机可自证）

```sh
bsk doctor                     # 期望：守护进程 + 扩展全部 ok（有 fail/warn 按提示修）
bsk --version                  # 期望：打印版本（本机基线 0.3.1）
python3 scripts/preflight.py   # 期望：逐项 PASS
```

`preflight.py` 会**先**检查 bsk 与登录态：没装 bsk → 直接指向本文档；没登录 → 明确报 `未登录（当前 <url>）`；
**绝不让流程带着半死的环境往下跑**。

## 六、常见失效与恢复

| 症状 | 真因 | 恢复 |
|---|---|---|
| `bsk: command not found` | 安装后没重启会话 → PATH 没生效 | 重启会话；或 `export PATH="$HOME/.local/bin:$PATH"` |
| `bsk doctor` 报扩展未连 | 扩展没启用 / 浏览器没开 | 打开 Chrome → 扩展弹窗确认已连 → 重跑 `bsk doctor` |
| 页面只剩空壳、字段全渲染成 `Unknown field` | bsk 会话退化（**注意**：多数时候真因是类目没点中） | `bsk session stop --all` 后重跑；仍不行看 `rollback.md` |
| 引擎报 `bsk-press 不可用` | 会话掉了 / 页面变了 | 先 `preflight.py` 定位是 bsk 层还是登录层 |
| 装不上扩展 / 装不上 CLI | 环境本身不满足（Chromium <125、企业策略禁扩展等） | **必须先解决这个依赖**：不要退回像素方案（慢一个数量级且易错、无法无人值守） |

## 七、会话约定（引擎已内置，客户不需要记）

- `bsk session start` 默认对着**唯一连上的浏览器**起会话；客户机通常不需要 instance id。
- 引擎把 SID 写进 `$BSK_SID_FILE`（默认 `/tmp/bsk_sid`），`bskhelp.py` 从那里读。
- 多浏览器时才需要 `--browser <INSTANCE>`（用 `bsk browsers` 取）。

## 八、平台备忘（交付前看）

- `tl_engine.py` 已按 `sys.platform` / `IS_WIN` 分支（macOS + Windows），**不需要管理员权限**。
- **Windows 路径尚未在真机实测**（开发机是 Intel Mac，Mac 上只验到结构层：用假 `windll` 验过按键调用序列与 VK 码）。客户桌面首次跑请跑两条自证：
  1. `python3 preflight.py` → 「兜底原语」一项会报 `keybd_event 可解析` 与剪贴板走 `tkinter` 还是 `powershell`（不弹 GUI、不按键，远程也能跑）。
  2. `python3 tl_engine.py --selftest-paste` → 打印 `PASS` 才是真可用（会开记事本/TextEdit 粘贴比对，完事自动关窗还原剪贴板）。
- Windows 上必须在**交互桌面会话**里跑（SSH / Session 0 / 计划任务 / 服务里提不起前台窗口，按键会空放）。
- **富文本走 `bsk press` 不需要窗口在最前**（按键由扩展送进页面）；只有走"OS 粘贴"兜底路径时才需要前台窗口，所以主路径能真无人值守。
- 卖家后台登录态**不可脚本代填**：未登录时新建页会跳 `/login`，`preflight.py` 会报出来（引擎不碰账号密码）。
