---
name: takealot-portal-cua
description: Use when 要在 Takealot 卖家后台建/改 listing（新建、拆解重塑、上传图片、类目向导）。首选无扩展 CDP 驱动（Hermes browser/裸 CDP），bsk 官方扩展为降级兜底；断言式验证 + 使用/退步/自愈/自学四份手册。
version: 1.9.0
author: Hermes Agent (OpenListing)
license: proprietary
platforms: [macos, windows]
metadata:
  hermes:
    tags: [takealot, seller-portal, listing, browser-automation, bsk, cua, self-healing]
    related_skills: [browser-skill, openlisting-repricing]
---

# 卖家后台「模拟真人点击」（Takealot Portal CUA）

> 用途：API 没有的能力（**图片上传**、类目向导、批量改内容）只能走界面。
> API 能做的（改价/改库存/建 offer/读订单）**永远优先走 API** —— 界面点击只用于补 API 的缺口。
> 目的：把卖家后台「新建 listing」做成**参数化脚本**（一次调用跑完一条），并在客户机上可远程交付、可自愈、可自我学习。

## When to Use（触发场景）

**用这个技能**：
- 在 Takealot 卖家后台**新建 listing**：用户给事实（品类/尺寸/材质/卖点/本地图）→ 生成文案 → 建草稿 → 提交。
- **拆解重塑 listing**：用户丢 1..N 条 takealot listing → 抽结构 → 重写文案 → 复用图 → 新建（图可复用，文案必须重写）。
- 任何 **API 做不到**的后台操作：图片上传、类目向导、属性面板、富文本字段、批量改内容。
- 用户说「上架」「建 listing」「把这个链接重新上」「搬过来改文案」「上一批货」这类话时。

**不要用**：
- 改价 / 改库存 / 读订单 / 建 offer —— 走 API。
- 登录、2FA、验证码、付款与权限设置 —— **交人**（本技能不碰凭据）。
- 删除 / 下架 / 权限类操作 —— 不在此技能范围。

## 交付前置（客户机第一步）

```sh
cd <技能目录>/scripts
# ① 推荐路（无扩展）：起一个带调试端口的浏览器（独立 profile，不碰你日常的 Chrome）
python3 cdp_browser.py --start          # 首次：弹出的窗口里登录一次卖家后台（登录态长期复用）
python3 cdp_browser.py --status         # 看：端口通不通 / 当前页面 / 登录态 / 页面是否可见
# ② 兜底路（官方扩展）：装好 bsk CLI + 扩展后
python3 preflight.py                    # 6 项 PASS 才能开工
```
驱动选择在**一个入口**里自动完成：`run_listing.py`（`--driver auto|cdp|bsk`，默认 auto = 先 CDP，连不上才退 bsk）。
无扩展那套的实测口径/坑见 `references/cdp-no-extension.md`；bsk 安装与降级路径见 `references/bsk-setup.md`。
**bsk 不需要塞进技能包**：扩展必须人工装、官方会升级 —— 包里放自检命令，客户跑出 PASS 即可（现在它是**兜底**，不是首选）。

## 文件地图（四条手册 + 脚本，按需读，别一次全读）

| 要做什么 | 读/跑这个 |
|---|---|
| **怎么用**：一条 listing 的完整流程、facts 字段、参数开关 | 本文档下面「两个使用场景」+ `templates/facts_*.json` |
| **怎么退步**：跑坏了 / 环境崩了 / 版本回滚 / 什么必须交人 | `references/rollback.md` |
| **怎么自愈**：症状 → 取证 → 判据 → 处置（按症状查表） | `references/self-healing.md` |
| **怎么自我学习**：新坑 / 平台改版 / 新类目 → 实测 → 写回哪里 | `references/self-learning.md` |
| **富文本走哪条路**（唯一真路 + 判据 + 收尾） | `references/rich-input-routes.md` |
| **无扩展路线**（Hermes/裸 CDP 驱动、登录态怎么来、已验证/未验证清单） | `references/cdp-no-extension.md` |
| **B 复刻/改编怎么跑**（四步链路 + 守门 + 两个未闭环缺口） | `references/replicate-playbook.md`（配套 `scripts/replicate_facts.py`、`scripts/check_facts.py`） |
| 查历史坑（按 A–H 分区） | `references/pitfalls.md` |
| **一条命令跑完（优选 CDP，自动退 bsk）** | `scripts/run_listing.py facts_X.json [--no-submit]` / `--verify <sid> facts_X.json` / `--check` |
| **给客户机起带调试端口的浏览器**（无扩展路的第一步） | `scripts/cdp_browser.py --start [--headless]` / `--status` |
| **CDP 驱动层**（把引擎的 bsk 原语换成裸 CDP） | `scripts/tl_cdp.py`（`import tl_cdp; tl_cdp.install()`）；口径见 `references/cdp-no-extension.md` |
| 开工前环境自检（bsk 兜底路用） | `scripts/preflight.py`（bsk / 会话 / 登录态 / 图片服务逐项 PASS） |

**驱动分层（2026-10-09 定版）：**
- **首选 = 无扩展 CDP 路**（`tl_cdp.py` + `cdp_browser.py` + `run_listing.py`）：不需要任何浏览器扩展，实测两条真站提交
  端到端 **109.7s / 118.1s**、服务端 `verify_persisted` **逐字 PASS**；Windows 上不受中文输入法影响。
  硬约束一条：**页面必须可见**（窗口被遮挡/最小化时 Chrome 丢键盘事件，表现为"只有打字静默 0 字"），无人值守用 `--headless`。
- **兜底 = BrowserSkill（官方扩展）**：CDP 端口起不来 / 客户机没有 Chromium / 排障时用；`bsk` CLI + 扩展（官方仓库 **https://github.com/Tencent/BrowserSkill**）。
- 两条路共用同一份 `tl_engine.py`，切换只靠 `run_listing.py --driver`（默认 auto：先 CDP，失败自动退 bsk）。
- **本技能不交付任何自制扩展**、**也不打包 bsk 本体**（第三方工具由官方升级）。
**写富文本（Draft.js）优先走 CDP 连发**：`Input.dispatchKeyEvent`（keyDown+keyUp 带 text，一次连发整串，**不等回复**）
——实测 762 字 0.6–1.8 ms/字、逐字精确；**必须**先确认页面 `visibilityState === 'visible'`（hidden 时 Chrome 丢键盘事件）。
兜底写手仍是 `bsk press` 逐字真实按键（152 ms/字）。**逐字等回复的批量输入不要用**（60 ms/字且会被应用自己的重渲染打断）。
**一句话规则**：只有浏览器**真实产生的输入事件**才走应用 onChange → 才可能落库；fiber 注入 / `bsk fill` / `insertText` / 合成事件实测**都只改页面状态**。
安装、验收、失效恢复全在 **`references/bsk-setup.md`**（含官方三平台安装命令 + 让 agent 自己装的一句话 + `bsk install-skill --harness hermes`）。




## 遇到问题先查这两份（不要重新摸索）

- `references/pitfalls.md` —— **坑总表**（A 定位 / B 属性 / C 富文本 / D 图片 / E 分区提交 / F 环境），每条都是「症状 → 真因 → 处置」。
- `references/self-healing.md` —— **自愈手册**：突发状况取证与处置、换类目/改版的重学流程、经验写回哪里、什么时候必须停下交人。

## 铁律（违反任何一条宁可停下）

> 下面 5 条是**定版铁律**。本技能**不用像素 / 坐标 / 锚点**：卖家后台每个控件都带 `data-fieldid`，
> **DOM + 真实按键就够了**。早期那版"模拟鼠标"的像素方案已废弃，不要再引入。

1. **DOM 优先，绝不猜坐标。** 定位一律用 `[data-fieldid]` / `[data-sectionname]` / 可见文本；
   `data-fieldid` 也拿不到 → **报错停下**（不退回像素：慢一个数量级、无法无人值守、且各客户机缩放不同）。
2. **每步都要断言。** 写完必须回读（字段值 / `data-error` / Draft 真身），点完必须看到预期的新状态。
   任一步不成立 → 停，报「未完成」（`assert_clean` 就是这条规则的实现）。
3. **写入只走"浏览器真实输入"，而且只在空字段上写。** 富文本 = `bsk press` 逐字真实按键；
   页面状态 ≠ 服务端状态，**保存草稿也不落富文本** → 唯一验收是**提交后回读服务端**
   （`python3 verify_persisted.py <submission_id>`）。**绝不"差不多就算过"。**
4. **证据在平台侧，不在 agent 自述。** 结论只能是「submissions 表里多了一行 / 回读到描述」，
   不是"我点完了"。过程日志与截图只是过程证据。
5. **收尾只做加法、不盲目重试。** 状态是异步的：写完先轮询等服务端状态落定（≤30s）→ 缺尾就**补尾**；
   补完仍不符或写多了 → **全选 + `Delete` 清空重打**（≤1 次）。`bsk press Backspace` 实测对本平台**无效**
   → 不做减法；末尾 ±2 字差**如实告警**。同类失败 2–3 次就停，把证据交人。

## 安全边界（硬性）

- **动作白名单**：仅限「新建 listing / 编辑内容 / 上传图片 / 类目向导」流程内的点击、输入、滚动。
- **黑名单（永不点击）**：支付与账单、删除/下架、权限与账号设置、API Key 页、任何弹窗里的「Allow / 授权 / 确认付款」；不输密码/API Key/验证码；密码类一律交给用户或 vault 工具。
- **急停**：动作前检查"鼠标是否被甩到屏幕左上角（0–80px 区域）"或用户按了 Esc → 立即中止本轮。
- **预算**：单轮动作上限 40 次、单轮最长 10 分钟；超出即停并汇报。
- **每一步留痕**：点击前后各存一张截图到 `state\portal_cua\runs\<时间戳>\`，步骤日志写 `steps.jsonl`（步号/目标/定位方式/坐标/确认文本/验证结果/耗时）。
- **不做凭证与风控对抗**：不伪造设备指纹、不注入脚本绕验证码；遇到验证码/滑块 → 停，交给人。

## 定位与验证（定版）

**DOM 优先**：控件一律用 `[data-fieldid]` / `[data-sectionname]` / `[data-isrequired]` / `[data-error]` 定位；
读值用 JS（`_js` / `_js_json`），写值用 `bsk press`（真实按键）或 `bsk fill`（普通 input）。
**不用像素、不用坐标、不做锚点校准**（早期方案已废弃）。

```sh
bsk get-html --session <id>    # 要看整页结构时：字段清单从 DOM 抠，不靠截图目测
bsk observe --session <id>     # 可访问树（带 @eN）：点击/选择类动作用
```

**纪律（实测踩到）**：写值后 DOM 会重渲染 → **旧 `@eN` 立刻失效**（曾拿旧 ref 点到别的页面）。
规则：**每次点击/选择前重新 `observe`**；批量只限"同一次 observe 拿到的 ref 且中间无写入"；`fill` 完先复核落值再继续。

**验证**：写完回读（`data-error` / 落值状态 / `_rich_truth`）；**结论只认平台侧**（`verify_persisted.py`）。

## 平台注意

- **Windows 客户机**：必须在**客户自己登录的交互桌面**里跑（SSH / Session 0 / 计划任务没有交互桌面，前台窗口抬不起来、按键会空放）。
- **Chrome 里要单独登录**卖家后台（其它浏览器登录态不共享；未登录时打开 `/single-product` 会 302 到 `/login`，`preflight.py` 会报出来）。
- 多窗口 / 多标签会干扰 bsk 的页面绑定 → 跑前把其它 Chrome 窗口关掉。
- **不需要锁缩放、不需要校准**（全程 DOM 定位；早期那套像素/缩放指纹方案已废弃）。

## 页面异常处置（实跑踩到）

- **下拉框（react-aria `ZorkAriaSelect`）**：必须点 **`.ZorkInput__input-selector`** 才展开 —— 点外层容器 DIV **不展开**，
  每字段白等 10s（实测）。展开后选 `div.ZorkMillerColumns__item` / 选项文本 → **回读落值**（chip / 深色文字）。
  （日常不用手点：引擎 `tl_engine.py` 已内置这条开法。）
- **下拉筛选**：要过滤时**用真实按键打字**（不要用 OS 剪贴板粘贴：中文输入法候选窗会吃掉内容；也别用 `Esc` 关候选窗 —— 实测会把过滤词一起清掉、列表复原）。
- **软性必填（硬规则）**：属性面板全绿、`assert_clean` 也过，预览页 Submit 仍可能一直 `disabled` 且**零报错**。
  实测 `Attribute.whats_in_the_box` 在 DOM 里标**非必填**，不填 → Submit 持续 disabled，补填后立即 enabled 并提交成功。
  判据：**Submit 无故 disabled → 回去把这类字段补齐**（该类目实测清单里的 textarea 类先全填上）。引擎的 `submit()` 会打印**取证**（预览页 URL + 正文含 error/required 的行 + 错误字段清单）。
- **页面卡死**（鼠标还能动、地址栏能点，但页面点击/键盘全无响应、截图逐帧相同）→ **Cmd+R 重载**。
  代价：草稿不保留、回到第 1 步类目、界面语言可能由中文变英文。别在这上面反复试点。
- **语言陷阱**：中文界面是浏览器翻译扩展翻出来的（所以有「羊肉袋尺寸」= poly bag size 这种怪名）→
  **任何定位/断言都不能依赖界面语言**，一律 `data-fieldid` + 落值状态；跑之前建议关掉翻译扩展。

**`bsk` 操作纪律（实测踩到的坑）**：`fill` 之后 DOM 重渲染，**旧 `@eN` 会失效并在下一次点击时把人带到别的页面**（本轮就因拿旧的 `@e75` 去点下拉，直接跳到了「Add To Takealot's Catalogue」提交列表）。规则：**每次点击/选择前先重新 `observe` 拿新 ref**，批量操作只限「同一次 observe 里刚拿到的 ref，且中间无写入动作」；`fill` 完先 `observe` 复核落值再继续。

**必填/可选判定（本平台硬规则）**：字段名后**没有** `(Optional)/(可选)` 的就是必填；页面里 `REQUIRED` / `RECOMMENDED` 两个分组由 DOM 的 `heading` 标出。**校验失败时平台只把整个属性面板描红 + 弹一条 toast（"Please complete the outstanding information below" / 中文"某些所需属性不完整或具有无效值"），不逐字段标红** —— 所以报错后必须自己去 DOM 抠清单核对，见 `references/backpacks-required-attributes.md`。

**但 `data-isrequired` 不等于全部真相（实测）**：属性面板全绿、`assert_clean` 也过，**预览页 Submit 仍可能一直 disabled 且零报错**。
实测案例：Cellphone Cables 类目下 `Attribute.whats_in_the_box` 在 DOM 里标 **非必填**，不填它 → Submit 持续 disabled（诊断跑了 45s 仍 disabled、React props 只有 `disabled:true`）；补填后 Submit 立即 enabled 并提交成功。
判据：**预览页 Submit 无故 disabled = 回去把这类「软性必填」补齐再试**（该类目实测清单里的 textarea 类字段先全填上）。

**页面卡死（本轮实际踩到）**：症状 = 鼠标移动仍能触发重绘、浏览器地址栏能点开，但页面**点击/键盘全无响应**（连续截图逐帧相同，PgDn/Home/End 无效）。诊断：`cliclick c:<地址栏坐标>` 能弹出建议列表 → 事件没坏，是内容进程卡住。
处置 = **Cmd+R 重载**。代价：草稿不保留、回到第 1 步类目、界面语言可能由中文变英文。别在这上面反复试点。

**语言陷阱**：中文界面是浏览器翻译扩展翻出来的（所以才有「羊肉袋尺寸」=poly bag size、「从下往上选择」这类怪名）。**锚点/expect_text 不能依赖语言**，一律用「字段名+相对位置+落值状态」定位。

## bsk（Chrome/扩展）实操手册（实跑验证过，优先用这套）

**用 `data-fieldid` 定位，不要用 ref/坐标。** 卖家后台每个属性控件的外层 DIV 都带 `data-fieldid`（如 `Attribute.is_water_resistant`、`Attribute.merchant_packaged_dimensions.width`、`title`、`ProductID.Value`），且带 `data-isrequired` / `data-error` / `data-fieldtype` —— 这三个属性就是**必填清单与校验状态的唯一真相**。
```sh
# 文本/数字字段：data-fieldid 在包装 DIV 上，真正的输入框是它的后代
bsk fill '[data-fieldid="Attribute.merchant_packaged_dimensions.width"] input' --value 32 --session <id>
# 一次性列出所有必填 + 未填（比任何截图都快）
bsk evaluate '(()=>{const r=[...document.querySelectorAll("[data-isrequired=\\"true\\"]")];return JSON.stringify(r.filter(e=>{const i=e.querySelector("input,textarea");return i&&!i.value}).map(e=>e.getAttribute("data-fieldid")))})()' --session <id>
```
- **下拉**：`bsk click '[data-fieldid="X"]'` 点外层（有时要点两下才展开）→ observe 里会出现 `@eN option "No"` → `bsk click @eN`。可搜索的（Material）先 `fill '[data-fieldid="Attribute.materials"] input' --value Poly` 过滤，再点 `option "Polyester"`。多选落值是 **chip 标签**，此时内层 input 会清空 —— “input 空”不等于没填，别误判。
- **富文本字段（title / description）是 Draft.js** —— 写入只认**真实按键**（2026-09-26 定版实测）：
  - ✅ **`bsk press <键> --selector '[data-fieldid="title"] .public-DraftEditor-content'` 逐字打**（默认写手）。
    实测写满 477 字描述 **精确 477/477**、标点/大小写/换行/破折号/引号全过；吞吐 **152 ms/字**（477 字 ≈ 104s）。
    不需要任何额外扩展、不碰 OS 键盘/剪贴板 → **定时任务无人值守可用**。
    （注意：**BrowserSkill 自己的那个浏览器扩展是必须的**——没有它 `bsk` 什么都做不了、`bsk doctor` 会报扩展未连。
    这里说的"不需要额外扩展"指的是：**除了它之外**不用再装任何别的扩展。）
  - ⚠️ 收尾自愈（`_finish_rich`）：整条流程里最后一个字符会**延迟落值**（实测 543→542、475→474）→
    先轮询等服务端状态落定（≤30s）→ 缺尾就**补尾**；补完仍不符或写多了 → **全选 + `Delete` 清空重打**（≤1 次）。
    **`bsk press Backspace` 实测对本平台无效 → 不做减法**；末尾 ±2 字差**如实告警**接受，绝不假装精确。
  - ❌ `bsk fill`（对 title 常直接写不进）、`document.execCommand('insertText')`、合成 `beforeinput/paste`、
    CDP `Input.insertText`、fiber 注入（`EditorState`+`onChange`）：**都只改页面状态/DOM，编辑器真身不动或服务端不收**。
  - ❌ OS 级逐字 keystroke：会过中文输入法（空格被吃成候选词）→ 要敲也先切英文输入源；本机 ⌘V 还会被 Chrome 吞掉。
  - 规则：**description ≥ 200 字符**（实测 185 报错、255 通过）；**title ≤ 75 字符**。
  - **title 是平台的 AutoBuild 字段**（`data-fieldtype="Title"`）：平台按属性自己生成标题，
    所以我们写它只是"加分项"——写不进去不该挡流程（facts 里放进 `optional`）；**description 才必须写进去**。
- **文件上传**：`input[type=file]` 是隐藏的，`bsk upload` 会报 “no visible geometry” → 先用 evaluate 给它加 `id=bskfile` 并 `style.cssText='display:block;position:fixed;top:60px;left:60px;width:240px;height:36px'` 把它露出来，再 `bsk upload '#bskfile' --file <绝对路径>`。
  若报 `Not allowed`：那是 **BrowserSkill 扩展缺 “Allow access to file URLs” 权限**（chrome://extensions → 该扩展 → 打开“允许访问文件网址”），不是脚本问题。`--mode drop` 要求目标是最顶层元素，容易被浮层挡住而失败。
- **分区 Next**：每区自带 Next，按钮没有独立标识 → 用锚文本反推：evaluate 找到 `Learn about brands` 这类链接，向上 8 层找 `button` 文本为 `Next`/`下一步` 的点击。点完不报错 = 该区校验通过（但底部 `Continue to Preview` 要等全表完整才可用，别拿它当单位校验信号）。

## 全流程通关实录（实测一次提交成功 → In Review）

按这个顺序做，步步有断言信号，能从头跑到提交：

1. **类目**：右栏搜索 `backpack` → 选叶子类目 → 面板内 Next。
2. **属性**：全部用 `[data-fieldid]` 选择器写值（见下）；下拉点外层 DIV（有时两下）→ observe 出 `@eN option "X"` 再点；多选（Material）先 fill 过滤再点选项；选完的 `data-error` 应为 false。
3. **每个分区都要点它自己的 Next**（属性 / 详情 / 图片 / 标识符）——“Continue to Preview”在**所有分区都点过 Next 之前一直是 disabled**，别拿它当单个分区的校验信号。Product Identifiers 的 Next 在 `[data-sectionname*="Identifiers"]` 容器**内部**，observe 的 ctx 经常带不到 → 用 evaluate 找容器内文本为 Next 的 button 点。
4. **富文本字段（title / description）是 Draft.js —— 定版走 `bsk press` 逐字真实按键**（2026-09-26 实测）：
   - ✅ `bsk press <键> --selector '[data-fieldid="description"] .public-DraftEditorContent'`（引擎里是 `_bsk_type`）：477 字描述 **精确 477/477**，152ms/字。
   - 写完必须**等**（轮询 ≤30s 等服务端状态落定）再判，然后交给 `_finish_rich` 收尾（缺尾补尾 / 写多了"全选 + `Delete`"清空重打；**`Backspace` 实测无效，不做减法**）——**不要**自己写"再试一次"。
   - ⚠️ OS 级 ⌘V 粘贴这条路**本机已废**（Chrome 吞掉合成按键，`os_paste mismatch: wanted N got 0`）；TextEdit 自证 PASS 也没用 → 别再走。
   - ⚠️ 152 ms/字 已是"浏览器真实按键"的物理下限（每字一次 CLI + 往返）；**不要再引入任何扩展去加速** ——
     曾评估的 CDP 加速件已下线（功能等效，但多一个部件的失效面：隔离世界 / 改代码要重载 / 调试器冲突）。
     真要省时间只能**少打字**（精简文案）或把富文本拆到更少的字段上。
   - ❌ 一律别用：`bsk fill`、`execCommand('insertText')`、合成 paste/beforeinput、CDP `Input.insertText`、fiber 注入 —— 页面看着写进去了，**服务端不收**。
   - **判据只有一条**：提交后 `python3 verify_persisted.py <submission_id>` 与 facts **逐字比**（可自动反查 facts，或加第二个参数给路径）。
     它现在会打印首个差异位置 + 上下文；末尾 ±2 字内才标 `PASS(近似)` —— 找不到 facts 时它只会说"弱判据"，别当验收结论。
     （草稿不落富文本，验草稿会得到假阴性。）
5. **图片上传**：**首选 URL 直塞**（2026-09-26 实测定版，比拖入快 4–5 倍，且**省掉本地下载**）——
   图片分区里的 `BUTTON: Add Image Link` **不是动作键，是 picker 的一个 tab**（另一个 tab 是 `Upload Images`）；
   点开后才挂载 `INPUT.link-input[placeholder="Enter image link"]` + 真正的确认键 **`BUTTON: Add Image`**。
   点 tab → 填 URL → 点 Add Image，三步。注意**分区是懒加载的**：跳页后要轮询到 `[data-sectionname*=Images]` 出现再动手。
   引擎里是 `add_images_by_link()`；`TL_IMG_MODE=drop` 可强制走老路。
   - **判据**：每喂一张都要看到**图片分区内 `<img>` 数量增长**（`[data-sectionname*=Images]` 里数）；只看"按钮点了"会得到假成功。
   - ⚠️ **喂进去的 URL 必须换 ≥600px 档**（`/(s-[a-z]+)\.file$/ → /s-zoom.file`）：源 listing 的 URL 常是 `s-pdpxl`(459px)，
     平台对太小的图**不报错**，只是预览页 Submit **永久 disabled**（最难查的坑）。
   - 实测（**每张 ≈3.8s**，两次直接计时都一致；对比拖入 **≈28s/张**）：8 张 ≈30s vs ≈225s，**省 ≈190s/条**；
     再叠加**零本地下载**（拆解重塑的源图从中国出口下 8 张要 400s+）→ **首次跑一条约省 600s**。
   - ⚠️ 别被计时器骗：引擎原先的"图片全部上传"计时器把**富文本打字**也框进去了（786 字 ≈120s+），
     一度让结论变成"跟拖入持平"；现已加独立计时器 `富文本完成`。**计时器跨两步会得出完全相反的结论。**
   - 它确实**真入库**：平台把 URL 抓下来**重新托管**成 `media.takealot.com/covers_images/<新id>/…`，存草稿重开后图还在。
   - 兜底（直塞失败自动退回）：本地下载 + 合成 DataTransfer 拖入 —— 本地起一个带 CORS 的 HTTP 服务（`~/.hermes/tools/cors_http.py`），页内 fetch 出文件 → 造 `File` → 合成 `DataTransfer` → 在 **React `onDrop` 元素**上派发 `dragenter/dragover/drop`：
   ```js
   let el=document.querySelector('input[type=file]'), target=null;
   while (el && el!==document.body){ const k=Object.keys(el).find(x=>x.startsWith('__reactProps$'));
     if (k && el[k].onDrop){ target=el; break; } el=el.parentElement; }
   const dt=new DataTransfer();
   for (const n of names){ const x=new XMLHttpRequest(); x.open('GET','http://127.0.0.1:8899/'+encodeURIComponent(n),false);
     x.overrideMimeType('text/plain; charset=x-user-defined'); x.send();
     const raw=x.responseText,b=new Uint8Array(raw.length); for(let i=0;i<raw.length;i++) b[i]=raw.charCodeAt(i)&0xff;
     dt.items.add(new File([b],n,{type:'image/jpeg'})); }
   for (const t of ['dragenter','dragover','drop']) target.dispatchEvent(new DragEvent(t,{bubbles:true,cancelable:true,dataTransfer:dt}));
   ```
   实测落点在 `DIV.ZorkImageDropZone`。**图片硬门槛：≥600×600 px**（分区说明写着 Min 600 x 600 px / Max 5000 px / 10MB / 20 张）。
   - **图太小平台不报错，只是「提交」按钮永远 disabled** —— 这是最难查的坑。复用源图时注意图床尺寸档：`s-xlpreview`=280、`s-pdpxl`=459（**都不合格**）、**`s-zoom`=1200**（合格）。
   - 计数验证：数**分区内 `<img>`**（拖入时是 `blob:`、URL 直塞时是 `covers_images`，两种都数得到）。**不要**用 `img[src*=covers_images]` 过滤（拖入时得假阴性 0）；也**不要**读分区标题里的 “N Images”——实测读到过 `20` 这种跟我们无关的数字，不可靠。
   - 本地 CORS 服务**端口要自选空端口**（8899 常被别人占着，占位者也回 200 → 页内 fetch 拿到别人的 HTML 当图片 → 平台静默丢弃，现象是 `dropped:N` 但 0 张进图集）。起完必须**回读一个真实文件确认它在服务这个目录**。
   - **本机探测 127.0.0.1 必须绕过系统代理**：Clash TUN 下 `urllib` 走代理会得到 `HTTP Error 502: Bad Gateway`（要用 `ProxyHandler({})` 的 opener）。
    - `bsk upload` 是第三条路，但需要 Chrome 给扩展开「允许访问文件网址」权限，否则报 `Not allowed`；`input[type=file]` 隐藏时还会报 `no visible geometry`（先给它加 id + `display:block;position:fixed` 露出来）。**优先级：① URL 直塞 → ② 本地下载 + drop → ③ `bsk upload`（要文件权限，不推荐）**。
6. **提交**：**预览页的 Submit 会先 disabled**（服务端在落库/校验），必须**轮询到 enabled 再点**。
   踩过的坑：点太快 → 点击落在 disabled 按钮上什么都不发生 → 报 “Confirm Submission not found”（看着像弹窗找不到，实际是根本没触发提交）。实测启用需等几十秒。
   等不到才走兜底链：① 改个唯一 Submission Name（预览页铅笔按钮；同名会被静默挡住）② Save and Close 落库 → 从 `/catalogue/submissions` 打开草稿 → 再 Continue to Preview → Submit。
   弹窗按钮文案容错：`Confirm Submission|Confirm|Yes, submit`。
   **验收断言 = 表格新增一行：状态 `In Review`、Submission Name、Submission ID、Products=1**（实测 A=5551496 / B=5551654）。不要拿弹窗消失当成功。
   - 诊断手法：拿不到原因时扒 React fiber 看 `__reactProps$`（实测 Submit 的 `disabled:true`、容器 `data-submissionid="123"` 是占位值，平台**不报任何错也不给 reason**）→ 别在页面上找原因，直接走等待/兜底。
   - **引擎自带取证**（2026-09-26）：`submit()` 判不出启用时会把预览页 URL、正文里所有含
     `error/invalid/required/missing/...` 的行、以及 `[data-error="true"] / .ZorkInput--hasError /
     [aria-invalid="true"]` 的字段清单全打进日志（前缀 `submit 取证`）——**先看取证，再谈兜底**。
   - ⚠️ **别把页面上的 `Duplicate` 当判重提示**（2026-09-26 纠正）：草稿/预览页上有一个正常的操作按钮就叫 **`Duplicate`**（旁边是 `Edit` / `Delete` / `Add Another Product`）——扫正文关键词会把**普通按钮**误判成平台判重。**真正的禁用原因**见下一条取证。

## 两个使用场景（必须当两件事做，共用一套写值内核）

> **现状口径（2026-09-26 定版，别对外说成"两个都全自动了"）：**
> - **A 完全自建 = 已闭环，可挂定时任务**。实测三条端到端（5552834 / 5552890 / 5552933），
>   每次都 `verify_persisted.py` 回读服务端 description 与参数**逐字一致**；一条 ≈5.5 分钟。
> - **B 复刻/改编 = 链路已闭合、可挂定时任务**（细节见 `references/replicate-playbook.md`，端到端证据见下）：
>   抽取 ✅（`extract_listing.py`）→ 结构脚手架 ✅（`replicate_facts.py`：字段名/图片 `s-zoom`/条码位由脚本保证，内容留给模型）
>   → **文案由模型写** ✅（用户口径：模型生成，用户只给差异参数，没给就按源重塑）→ 守门 ✅（`check_facts.py`：离线 + `--live` 真选一遍）
>   → 写值 ✅ → `verify_persisted.py` 回读服务端。
>   **端到端证据**：**5552980**（Cellphone Cables / `USB Type-C Cable` / 20 张图 URL 直塞 / description **服务端 705 字逐字一致** / 358s）；
>   反例对照 **5552977** = 修复前（服务端 706，末尾被"补尾"多打一个句号 → 见 `pitfalls.md` G9）。
>   · **物流属性（包装长/宽/高/重）买家页没有**（卖家侧属性）→ `config/spec_defaults.json` 按类目配一次；
>     没配则由模型估值并在 facts 标 `_logistics_source="model-estimate"`（守门降级为提醒，不拦）。
>   · **可搜索 combobox 已打通**（`pick_combobox()`：`focus` + `bsk press ArrowDown` 开 → 过滤 → 点 `[role=option]`；⚠️ `Enter` 不提交）。
>   · **判重 / 自创自拥有不是我们的标准**（用户口径）：我们只负责"能不能自动化"。
>
> 挂定时任务前必读的前置条件：**登录态过期只能靠人重登**（`preflight.py` 先报，cron 要当停机告警）、
> **只能串行**（单浏览器，N 条 = N × 5.5 分钟）、**别在同一个标签页上人工操作**、
> facts 不完整会 **fail-fast 停下**（必须接告警，否则静默失败）、
> 「图片复用不算判重」仍是**推断未证**（批量复刻同一供应商的图文有被判重风险）。

**A. 自编辑新建**：用户给“事实”（品类、尺寸、材质、卖点、本地图片）→ 生成标题/描述/属性映射 → 建草稿 → 断言 → 提交。文案是**生成**，图**本地文件上传**。
**B. 拆解重塑**：用户给 1..N 条 listing → 抽取（标题/描述/属性值/图片 URL/类目路径）→ **重写文案** → 新建（图用 `Add Image Link` 直塞 URL）→ 断言 → 提交（可批量）。文案是**改写**，事实字段（尺寸/材质/属性值）不动。

两者的差异全在参数上：数据来源、文案来源（生成 vs 改写）、图片来源（文件 vs URL）、条码策略、单条 vs 批量。**不要合成一条流水线。**

### 条码策略（业务开关，不是“必填/必换”）
- 卖家很多没 GS1 条码；**留空 → 平台生成 → 默认允许他人跟卖**；填自有 GS1 → 独享（不能跟）。这是客户要拍板的商业决定，脚本里做成参数，不要硬填。
- **实测结论（2026-09-26）**：条码**留空可以提交成功** —— 预览页显示 “Barcode(s) Not Supplied”，提交后状态 `In Review`（Submission ID 5551496）。要独享就把自造合法校验位 EAN-13（如 6901234567892）当参数填进去。

### 判重信号（决定场景 B 的 KPI）
- **图直接搬不是判重复的主因，标题 + 详情描述才是**。所以 B 的核心动作是：文案必须重写（关键短语不重叠、标题结构换序、卖点重排），图片可以照搬（自家媒体资源随便用；竞品图风险低但非零）。
- 文案护栏写成规则：与源描述不得整句相同、关键短语不重复、属性/尺寸等事实不动。

## 参数化引擎（A/B 共用，脚本化 —— 优先用这套，别再一次次手点）

全部随技能发布在 `scripts/`（工作目录可用 `TL_WORKDIR` 改，默认 `~/.hermes/portal_cua`；客户机拷技能目录即可）：

| 脚本 | 用法 |
|---|---|
| `discover_fields.py "类目1" "类目2" "叶子"` | 打开新建页选到类目 → dump 该类**字段清单**（`data-fieldid` / 必填 / 控件类型 / 标签）→ `~/.hermes/portal_cua/manifests/fields_*.json`。**换类目先跑这个**：不同类目必填完全不同（Backpacks 10 项 ≠ Cellphone Cables 另一套） |
| `create_listing.py facts_X.json [--no-submit]` | 喂 facts JSON 跑完整条：类目 → 属性 → 文案 → 图片 → 分区 Next → 断言 → 提交（Submit 轮询 enabled + 改名单/落库重开兜底）→ 读 submissions 表核对 |
| `diag_preview.py facts_X.json` | 诊断：跑到预览页并 dump「Submit 为什么 disabled」（React fiber props + 页面提示） |
| `extract_listing.py <pdp_url> [name]` | B1：抽源 listing（标题/品牌/图 URL/规格/面包屑）→ manifest |
| `tl_engine.py` | 内核：`data-fieldid` 写值、`os_paste`、图片下载+免权限 drop、分区 Next、`assert_clean`、`submit` |

纪律：**断言式，失败即停**（`data-error` 全 false、错误文案为空、该填的必填都非空才提交）；每次运行落 `~/.hermes/portal_cua/runs/<name>.report.json`。
`facts` 支持 `"optional": ["Attribute.whats_in_the_box"]` —— 类目不同字段不同，声明为可选的字段缺失时只警告、不中断。
两场景均已实测端到端跑通提交（2026-09-26）：A 自编辑（Backpacks，本地图，Submission 5551496）、B 拆解重塑（Cellphone Cables，复用源图 8 张 s-zoom，Submission 5551654，In Review）。
类目名用卖家后台的树：后台**没有** “Cellphones & Wearables”，手机线在 `Consumer Electronics > Electronic Accessories > Mobile Phone Accessories -> Cellphone Cables`（叶子名可只给尾部关键词，匹配用包含）。

## 学习 / 重学 / 自愈 / 自我进化（一页版，细节见 `references/self-healing.md`）

**学一个动作**：只认锚点不信像素 → 先用 DOM/AX 定位（`[data-fieldid]`、`[data-sectionname]`）→ 确认预期文本在 → 执行 → **验证落到平台数据**（`data-error` / submissions 表）。没验证的步骤不算学会。

**换类目 / 平台改版（重学）**：重跑 `discover_fields.py` 拿真字段清单 → 对比上次 `manifests/fields_*.json` → 改 facts → 先 `--no-submit` 跑到 `clean: true` → 再提交 → 新类目清单落 `manifests/`、新坑落 `references/pitfalls.md`。参考成本：新类目首读 1 次发现 + 1 次无提交验证（5-10 分钟），同类型再来一条直接跑（6-8 分钟）。

**自愈优先级**（异常时按顺序做，不要“再试一次”掩盖）：
1. **等**：状态类问题先等（预览页 Submit 最多轮询 45s）。
2. **重读**：重新 `observe`/`evaluate` 拿真相，禁用旧 ref。
3. **降级**：富文本 → OS 粘贴；文件上传 → 本地服务 + drop；源图 → s-zoom 档。
4. **兜底链**：提交不动 → 换唯一 Submission Name → Save and Close 落库 → 从 submissions 重开再交。
5. **停**：同类失败 2-3 次、登录/风控/权限类 → 停，把证据（URL + 页面信号 + 报告 JSON）交人。

**自我进化（做完必落一处）**：新坑 → `references/pitfalls.md`（带实测证据）；新类目字段 → `manifests/`（脚本自落）；可复用 facts → `templates/`；引擎改良 → `scripts/tl_engine.py`（注释写清源自哪个坑）；平台机制结论（如“条码留空=平台生成”）→ 本文件对应章节一句话 + 证据。
**不写**：账号/操作者身份、凭据、客户商品数据、一次性调试路径、过程叙事。

## 实测耗时与端到端结果（2026-09-26 定版，纯 bsk）

**端到端跑通的那一条（换个类目、真实提交）**：`Memory Cards -> Memory Cards`，25 字段 + 543 字描述 + 8 张图
→ 提交 **5552834**（In Review），`verify_persisted.py 5552834` 回读**服务端 description = 544 字 ✅**
（title 服务端 0 = AutoBuild 正常）。

**定版复跑（2026-09-26 23:43，拆掉 CDP 桥接代码后）**：换全新文案（582 字描述、标题 56 字），同样 8 张图 →
**SID 5552890**，引擎日志 `description via bsk-press`（精确、无近似告警）→ `verify_persisted.py 5552890`
回读**服务端 description = 582 字 ✅**，总耗时 **283.6s**。这一跑就是"拆代码没拆坏"的验收证据。

**URL 直塞端到端（2026-09-26 深夜）**：全新文案（786 字描述）+ 同样 8 张图、但图片改走 **URL 直塞** →
**SID 5552933**，报告里 `image_mode=link`、`images=8`、`downloaded=None`（**零下载**）→
`verify_persisted.py 5552933` 回读**服务端 description = 786 字 ✅**（与参数逐字一致），总耗时 335.1s（含一次 16.9s 硬重置）。

| 阶段 | C 跑（首次、图未缓存） | D 跑（拆桥后、图已入过库） | E 跑（URL 直塞、786 字文案） | 说明 |
|---|---|---|---|---|
| 开新建页（含硬重置） | 12.5s | 8.3s | 28.8s | E 那次有 16.9s 硬重置（上一跑残留状态） |
| 选类目 + 变体（JS 快路） | 13.7s | 10.8s | 12.0s | 老路 91–140s，已废弃 |
| 填 25 个属性 | 42.6s | 39.6s | 42.0s | 分组并行：dropdown / text |
| 富文本打字 | ~110s | ~140s | ~176s（推算） | **152 ms/字**、唯一自动路；打字是单条最大单项 |
| 图片 | ~227s | ~35s | **≈30s（8 × 3.8s，零下载）** | 直塞 **3.8s/张**（直接计时两次一致）vs 拖入 ≈28s/张 |
| 分区 Next ×3 + `assert_clean` | 7.8s | 7.4s | 7.7s | |
| 进预览页 | 6.4s | 6.5s | 6.4s | |
| Submit（含确认弹窗 + 表格核对） | 29.3s | 36.0s | 31.5s | |
| **合计** | **340.7s ≈ 5 分 41 秒** | **283.6s ≈ 4 分 44 秒** | **335.1s ≈ 5 分 35 秒** | 定时任务按"≤6 分钟/条"排产留余量 |

> ⚠️ **旧版这张表把"富文本 + 图片"算成同一个计时块**（引擎当时没有富文本计时器）→ D/E 的图片成本被富文本时间掩盖，
> 一度得出"URL 直塞没有收益"的**反结论**。现已拆成两行，引擎也加了 `富文本完成` 计时器。
> **实测结论：直塞 ≈3.8s/张 vs 拖入 ≈28s/张**（两次直接计时一致）；拆解重塑的源图还要额外下载 400s+/8 张，
> 直塞把这笔也省掉 → **首次跑一条 ≈省 600s**。
> **教训：计时器跨两步会得出完全相反的结论。**
> 引擎已把 `submission_id` 放进报告（`submission.submission_id.id` / `.url`），验收就是复制粘贴一条命令。

**已知的质量瑕疵（不挡提交，但要如实报）**：Draft 的最后一次输入事件在本机平台总**落后一步**，
所以富文本真身/服务端可能比预期**多 1 个字**（本次服务端 544 vs 预期 543）。当前无法做"减法"
（`Backspace` 实测无效）→ 引擎按"末尾 ±2 字 + 其余逐字一致"接受并**打警告**，不许伪装成精确命中。

## 收工要说的话（给用户）

- 这次做了什么（哪几步）、平台侧证据（API 回读结果）、留痕位置（`state\portal_cua\runs\<时间戳>\`）。
- 如果没做成：卡在第几步、截图在哪、下次要不要人工先手动走一遍再学。
