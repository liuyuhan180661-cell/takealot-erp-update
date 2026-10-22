# Takealot ERP 更新手册（Agent 专用）

## 一句话规则

**只用一个固定通道：gh-proxy。禁止逐个通道试。**
检查通过后只执行 `--check` 和 `update` 两条命令；失败就停下报告，不要换 URL、不要手工下载 zip、不要删 `state/`。

固定通道（注意结尾的 `/`）：

```
https://gh-proxy.com/https://raw.githubusercontent.com/liuyuhan180661-cell/takealot-erp-update/main/
```

---

## 0. 先定位 ERP 命令

Windows：

```powershell
$ERP_HOME = Join-Path $env:LOCALAPPDATA "TakealotERP"
$ERP = Join-Path $ERP_HOME "cli\erp.cmd"
```

macOS：

```bash
ERP_HOME="$HOME/.takealot-erp"
ERP="$ERP_HOME/cli/erp"
```

如果本机没有 `erp update`，说明还是很老的 v2；直接跳到本文最后的「v2 引导」。

---

## 1. 检查更新（固定通道）

Windows PowerShell：

```powershell
$channel = "https://gh-proxy.com/https://raw.githubusercontent.com/liuyuhan180661-cell/takealot-erp-update/main/"
& $ERP update --check --channel $channel
```

macOS：

```bash
CHANNEL="https://gh-proxy.com/https://raw.githubusercontent.com/liuyuhan180661-cell/takealot-erp-update/main/"
"$ERP" update --check --channel "$CHANNEL"
```

- 输出「已是最新」：结束，不要重装。
- 输出「可更新」：继续第 2 步。
- 输出网络错误：**停止并报告原始错误**，不要换 jsDelivr / raw / ghfast 逐个试。

---

## 2. 升级前备份用户数据（建议）

`state/` 不会被安装器覆盖；备份只是保险。

Windows：

```powershell
$stamp = Get-Date -Format "yyyyMMddHHmmss"
Copy-Item (Join-Path $ERP_HOME "state") (Join-Path $ERP_HOME "state.bak-$stamp") -Recurse
```

macOS：

```bash
cp -a "$ERP_HOME/state" "$ERP_HOME/state.bak-$(date +%Y%m%d%H%M%S)"
```

---

## 3. 执行升级

Windows：

```powershell
& $ERP update --channel $channel
```

macOS：

```bash
"$ERP" update --channel "$CHANNEL"
```

要求：

- **不要加 `--force`**，除非用户明确说“同版本也要重装”。
- 升级会覆盖：服务端、UI、Agent 技能、CLI。
- 升级不会覆盖：`ERP_HOME/state/`（店铺、草稿、采集箱、凭证、权限等）。
- 升级完成会自动重启服务；先告诉用户界面会短暂中断。
- 成功输出必须包含：`已更新：... → ...` 且 `RESULT 13/13 PASS`。

---

## 4. 升级后验收

```bash
erp status
erp update --check --channel "<固定通道>"
```

再检查：

- `http://127.0.0.1:18791/` 能打开，标题是 `Takealot ERP · v2`。
- `/legacy` 仍能打开旧界面（回滚入口）。
- 店铺、草稿、采集箱数量还在。
- 界面无 console error。
- MCP 工具数仍为 31（`hermes mcp test takealot-erp` 或宿主工具表）。

对用户汇报三件事：旧版本 → 新版本、`13/13`、数据是否保留。

---

## 5. 失败处理（重要）

出现以下任一情况，**立即停止，不自行修复、不换通道、不删数据**，把原始输出和日志尾部交给用户/开发：

- 下载超时或 TLS/SSL 错误。
- sha256 校验不过。
- 安装后自检不是 `13/13 PASS`。
- 服务起不来，或首页不是 v2。

日志位置：

- Windows：`%LOCALAPPDATA%\TakealotERP\logs\`
- macOS：`~/.takealot-erp/logs/`

不要尝试第二个、第三个更新通道；这正是要避免的“一个个试”。

---

## v2 引导（没有 `erp update` 的老机器）

只走 gh-proxy，不要试 raw/jsDelivr。

Windows PowerShell：

```powershell
$url = "https://gh-proxy.com/https://raw.githubusercontent.com/liuyuhan180661-cell/takealot-erp-update/main/update.ps1"
curl.exe -fsSL --max-time 90 -o "$env:TEMP\update.ps1" $url
powershell -ExecutionPolicy Bypass -File "$env:TEMP\update.ps1"
```

macOS：

```bash
curl -fsSL --max-time 90 -o /tmp/update.sh \
  "https://gh-proxy.com/https://raw.githubusercontent.com/liuyuhan180661-cell/takealot-erp-update/main/update.sh"
sh /tmp/update.sh
```

安装完成后再按第 1～4 步验收。

---

## 绝对不要做

- 不要逐个尝试 `jsDelivr`、`raw.githubusercontent.com`、`ghfast`、`gh-proxy`。
- 不要手工下载 `Takealot-ERP-update-*.zip` 覆盖安装。
- 不要删除或移动 `ERP_HOME/state/`。
- 不要为了让版本号变化而反复 `--force`。
- 不要在用户正在改价/上架时静默重启；先说明再升级。
