# 坑总表（每一条都是实测踩出来的，按"症状 → 真因 → 处置"写）

> 用法：遇到问题时按症状搜这份表，不要重新摸索。新增坑时**必须带实测证据**（命令输出/页面信号），不写推测。

## A. 定位类

| # | 症状 | 真因 | 处置 |
|---|---|---|---|
| A1 | `bsk observe` 里 grep 不到属性字段（StaticText 全空） | 属性控件是 React 自绘，不进 AX 树 | 改用 DOM：`[data-fieldid="..."]` 选择器一次拿全 |
| A2 | 用旧 `@eN` 点下去页面跑到别的地方（如跳「Add to Takealot's Catalogue」） | `bsk fill` 后 DOM 重渲染，旧 ref 失效 | 每次点击前重新 `observe`；写入动作之间不复用 ref |
| A3 | OS 级点击（cliclick/Peekaboo）打在空处或误点到底栏按钮 | bsk 注入的 `<browser-skill-overlay>` 盖住整页，吃掉真实鼠标事件 | **只用 JS/DOM 定位 + bsk 写值**：全程 DOM + JS 点击 / 真实按键，**不做 OS 级点击、不用像素**（引擎已如此） |
| A4 | 类目第一级点不到（如 "Cellphones & Wearables"） | 拿的是买家站（takealot.com）的类目名，卖家后台树不同 | 只用后台树；第一级先遍历 `bsk observe` 的按钮列表确认；变体用包含匹配（叶子名可只给尾部） |
| A5 | **紧接上一次运到再跑，报 "no element found for category level 1"** | `bsk navigate` 到**同一个 URL** 时 SPA 不重建，上一轮选好的类目还在 DOM 里 | `open_new_listing` 先判面板是否还在 `Please make a selection` 的干净起点，否则 `location.reload()`；`pick_category` 找不到按钮时再判一次"是否已选中"，是则跳过（已内置） |

## B. 属性写值类

| # | 症状 | 真因 | 处置 |
|---|---|---|---|
| B1 | 提交报「某些所需属性不完整或具有无效值」，页面不逐字段标红 | 平台只把整块面板描红 + toast | 用 `[data-isrequired="true"]` 一次读全 + `data-error` 判断，自己核清单 |
| B2 | 下拉点开了看不到选项 | 可搜索下拉（先输入才出选项）；或面板需点两下才展开 | 点外层 DIV（必要时两下）→ 无选项则 `fill` 输入框前 3-4 字过滤 → 再点 `@eN option "X"` |
| B3 | 多选（Material）明明选了却判为未填 | 多选落值是 **chip**，内层 input 会清空 | 判定看 chip 文本/`data-error`，别看 input.value |
| B4 | Warranty 只填了一个值就报错 | 它是「类型 + 有效期」两个下拉 | 两个都选（`pick_warranty(type, period)`） |

## C. 富文本类（title / description，Draft.js）—— 最耗时的坑区

| # | 症状 | 真因 | 处置 |
|---|---|---|---|
| C1 | `bsk fill` 返回 `could not verify the expected value`，DOM 里有字或没字，说不清 | 对 Draft 是**假阴性**；title（AutoBuild 字段）更是完全不接受 | **只用 OS 级真实粘贴**：pbcopy → JS `focus()`（确认 `document.activeElement===el`）→ 真实 ⌘A + ⌘V → 读回 innerText 断言 |
| C2 | 逐字敲进去的文本变形（`" Backpack"` 变 `"a'ckpack"`）、字符丢失 | 中文输入法把空格变成候选词；OS 键盘事件受输入源影响 | 别逐字敲；必须敲时先切英文输入源 |
| C3 | 合成 `ClipboardEvent('paste')` / `document.execCommand('insertText')` 写了字但校验仍报旧错 | 只改 DOM 没改 React state | 同上：真实 ⌘V |
| C4 | 描述 <200 字报 `must be at least 200 characters` | 平台硬门槛 | 描述 ≥200 字（实测 185 报错 / 236 通过）；标题 ≤75 字（占位符写着 `(75)`） |
| C5 | 多段文案想分行 | Draft 的 fill 路径进不去换行 | OS 粘贴支持多段（实测 477 字多段正常）；用 `fill` 时只能单段 |

## D. 图片类

| # | 症状 | 真因 | 处置 |
|---|---|---|---|
| D1 | **提交按钮一直 disabled、页面零报错** | 图 <600×600（平台只在分区说明里写 Min 600x600） | 源图换 `s-zoom` 档（1200px）；本地图先量尺寸（`tl_engine._check_images`） |
| D2 | 复用源 listing 图：`s-pdpxl`/`s-xlpreview` 下载回来偏小 | 图床档位：`s-xlpreview`=280、`s-pdpxl`=459、`s-zoom`=1200 | 按 `s-zoom → s-pdpxl → s-xlpreview` 降级下载，并断言 ≥600 |
| D3 | `bsk upload` 报 `Not allowed` | 扩展缺 Chrome「允许访问文件网址」权限 | 走免权限方案：本地 CORS 服务 + 页内 fetch 造 File + 合成 DataTransfer drop |
| D4 | drop 返回 `dropped:8` 但图集 0 张 | 8899 被别的服务占着且它也回 200 → 页内 fetch 拿到别人的 HTML 当图片 | 自选空端口 + 起完回读一个真实文件确认在服务该目录 |
| D5 | 数 `img[src*=covers_images]` 得 0，但图其实进去了 | 上传中 `<img>` 是 `blob:` | 数分区标题的 `N Images` 并轮询到齐 |
| D6 | 本机探测 127.0.0.1 报 `502 Bad Gateway` | 系统代理（Clash TUN）劫持了本机请求 | 探测用 `ProxyHandler({})` 的 opener |

## G. 会话 / 窗口类（客户机口径跑出来的，最容易被忽略）

| # | 症状 | 真因 | 处置 |
|---|---|---|---|
| G1 | 类目都点到了（日志全绿），但面板 Next 点不动 / 后面**0 字段** | 复跑时 SPA 残留，再点那一级 = **反选** | `open_new_listing` 已内置硬重置（about:blank → 新建页）；`pick_category` 找不到按钮时再判“是否已选中” |
| G2 | 干净起点也对、类目也点了，但表单就是不出现（0 字段） | **bsk 会话本身退化了**（今天反复起停/重载后出现） | `bsk session stop --all` → 新建会话 → 重跑（实测：字段从 0 回到 27） |
| G3 | 富文本（title/description）写不进去 / 看着写进去了但没存 | **判据只能用「已提交的 listing」**：草稿的 Save and Close **从不落富文本**（重开必是 0，实测多次）；页面状态 / DOM 更不可信 | 写入路实测（2026-09-26）：✅ **`bsk press` 逐字真实按键**（引擎 `_bsk_type`）—— 编辑器精确命中（103/103、117/117、477/477、64/64），不靠 OS 键盘/剪贴板；❌ fiber 注入、`bsk fill`、`Input.insertText`、JS 合成 paste/beforeinput —— 要么只改 DOM/状态，要么应用不收（这些只在草稿上验过，而草稿本来就不收富文本 → 别再用草稿当判据）；❌ OS ⌘V 在本机被 Chrome 吞掉 |
| G3b | 要无人值守（定时任务）写富文本 | OS 级 ⌘V 在部分环境被 Chrome 吞掉（TextEdit 自证 PASS、Secure Input=0、Chrome 前台、元素 activeElement、去掉 bsk 遮罩——全无效） | **只用 `bsk press <键> --selector <字段>` 逐字打**（实测 477/477 精确，标点/大小写/换行全过；**152 ms/字 → 477 字 ≈ 104s**；BrowserSkill **官方扩展是必须的**，但**除它之外不需要任何额外扩展**）。**不要再挂第三方扩展加速**：曾评估的 CDP 加速件已下线（功能等效，代价是多一个部件的失效面：隔离世界 / 改代码要重载 / 调试器冲突） |
| G3c | 打字偶发「少最后 1 字」/「多 1 字」 | 平台 Draft 的**最后一次输入事件总落后一步**：打完 543 字读到 542；这时去补尾，迟到的那次落值正好落地 → 变成 544 | **实测有效的原语只有三个**：①**逐字打字 = 追加**（`bsk press`，可补尾）②**全选 + `bsk press Delete` = 清空**（重打用）③`wait_exact` 轮询等落值。**`bsk press Backspace` 实测无效**（状态不变，别再拿它做"减法"）。收尾顺序：等 ≤30s → 缺就补尾 → 补完仍差/多 → 清空重打（最多 1 次） |
| G3d | 预览页 **Submit 灰着/点不动，控制台无报错** | 平台不给 reason（按钮 props 上只有 `disabled:true`，容器 `data-submissionid` 还是占位 `"123"`） | **别扫正文关键词 `Duplicate`**——那三个字其实是草稿页上一个**正常操作按钮**（`Edit` / `Duplicate` / `Delete` / `Add Another Product`），扫正文会误判成平台判重（2026-09-26 实测纠正：换类目重跑 **Submit 正常亮**、提交成功 5552834 → 之前"平台判重"的结论是错的）。正确动作：①**先看引擎取证**（`submit 取证` 打印正文里含 `error/required/missing/invalid` 的行 + `[data-error="true"]` 字段清单）②等 45s 重试 ③改唯一 Submission Name ④Save and Close 落库 → 从列表重开 → **重开后必须重走分区 Next 再提交**（否则按钮在表单页上必然是禁用）＋重写富文本 |
| G4 | Chrome **点不开 / 看不到任何窗口**，Dock 点了没反应；`bsk browsers` 显示 `(no browsers connected)` | 残留的 **headless Chrome 实例**（`--headless=new`、ppid=1、占 `--remote-debugging-port=9333`、临时 profile）以 bundle id 占着位置，`open -a "Google Chrome"` 和 Dock 点击全被 **handoff** 掉 | `pgrep -f 'Google Chrome.app/Contents/MacOS/Google Chrome'` 找到非 headless 为 0 的那个 pid → `kill <pid>` → `open -a "Google Chrome"`，扩展立刻重连（实测：Chrome 38027 起来、扩展第 1 次轮询就连上） |
| G5 | Chrome 一个窗口都没有（后台 service worker 休眠） | 扩展依赖前台有窗口 | 跑任务前先留至少一个 Chrome 窗口；**没有窗口时不要开始跑** |
| G7 | 验收脚本报 FAIL（服务端空），但你确定刚写进去了 | 传了**空/错的 submission id**：老版本会静默退化成"列表里最新那条草稿"→ 验的是**另一条**记录 | 只用报告里的干净 SID：`submission.submission_id.id`（引擎现在直接给，`create_listing.py` 跑完会打印**可复制粘贴**的验收命令）。`verify_persisted.py` 已改为**拒绝非数字参数**、无参时打明显警告 |
| G8 | 图片分区里 `Add Image Link` 点了没反应 / 喂了 URL 图集不长 | ① `Add Image Link` 是 picker 的**一个 tab**（不是动作键），点开后才挂载 `INPUT.link-input`，**真正确认键叫 `Add Image`**；② 图片分区**懒加载**，跳页后没等它渲染就去点 = 白点；③ URL 若已是**该草稿里**的图，平台**静默忽略**（计数不涨，别当故障）| **URL 直塞**已进引擎（`add_images_by_link`，`TL_IMG_MODE=drop` 可关）：每张 **≈3.8s** vs 拖入 ≈28s、且**零本地下载**（拆解重塑首次跑共省 ≈600s）；**URL 必须换 ≥600px 档**（`s-zoom`=1200px；`s-pdpxl`=459px 会让 Submit 静默禁用）；判据 = **分区内 `<img>` 数量增长**（别读 "N Images" 文本，实测读到过无关数字 20）；**计时器绝不能跨两步** —— 曾把富文本打字框进"图片全部上传"，得出"直塞没收益"的反结论 |
| G6 | AX 枚举 `windows of process "Google Chrome"` 为空 / 报 `<err>`，但 AppleScript 明明看得到窗口 | `process "Google Chrome"` 按**名**解析到了那个 headless 实例（0 窗口） | 用 **pid**：`first process whose unix id is <pid>`（实测能拿到 `Seller Portal - Google Chrome`） |

**G3 已排除的原因（逐项实测，别重复排查）**：
- ❌ “AX 里有多个同名窗口” —— 干净 Chrome（单实例、单窗口、单会话）下 **仍失败**（`wanted 71 got 0`）。
- ❌ 键盘机制/权限坏了 —— 同一时刻 `tl_engine.py --selftest-paste`（TextEdit 往返）**PASS**，Secure Input = 0。
- ❌ 剪贴板/焦点没到位 —— 剪贴板已装载、Chrome `frontmost = true`、agent 窗口是 key window、目标元素是 `document.activeElement`（还试了 bsk 真实点击）。
- ❌ `bsk window resize` 干扰 —— 从置前路径摘掉（改 `TL_RESIZE=1` opt-in）后依旧失败。
- ❌ 第二个 Chrome 实例 —— 用户正常启动的单一实例下依旧失败（新验收脚本 3/3 轮 FAIL）。
⇒ 结论：交付口径 = **自动填其余字段 + 存草稿 + 打印待粘文本**；“标题自动写入”列为**客户桌面的验收项**（客户机器/Chrome 版本上可能就好，但不得当默认承诺）。

| G9 | 服务端 description 与 facts 差 1 个字符（典型：末尾多一个句号） | 富文本收尾时**读回滞后**被误判成丢字 → 引擎"补尾"把已到位的尾巴又打了一遍（5552977：facts 705 → 服务端 706，`...cable..`） | 引擎已改：**读回只短 1–2 字时不补尾**（那几乎总是落值滞后），如实告警即可。判据只看 `verify_persisted.py` 的服务端回读 —— 注意它旧版"非空即 PASS"是**弱判据**（706 vs 705 也放过），现已改成与 facts **逐字比**，末尾 ±2 字内标 `PASS(近似)` 并打印差异上下文 |
| G10 | 下拉选不上：`option 'XXX' not found`，但页面上明明有这个值 | 该字段是**可搜索 combobox**（`INPUT[role=combobox]`，react-aria）：JS 原生 click（点外层 div 或 input）**打不开**；OS 级点击被 bsk 整页 overlay 吃掉；"读选项列表"在没打开时会读出假的 `(Optional)` → 容易误判"平台没这个值" | 用 `pick_combobox()`（`pick_dropdown` 遇到 combobox 自动改走它）：`_reveal` 滚到可见 → JS `focus()` → **`bsk press ArrowDown`**（真实按键，1s 开出全部选项）→ 需要就打前缀过滤 → **JS 点 `[role=option]`** → 读回断言。⚠️ `Enter` **不提交**（必须真点到选项）；值确实不存在时直接失败并**报出打开后的真实选项**（不再退老路白跑 30s）。实测 `cable_type="USB Type-C Cable"` → True/2.8s |

## E. 分区 / 提交类

| # | 症状 | 真因 | 处置 |
|---|---|---|---|
| E1 | `Continue to Preview` 一直点不动 | 它要**所有分区都 Next 过**才可用 | 逐区点各自 Next（属性/详情/图片/标识符），再继续 |
| E2 | 找不到 `Confirm Submission` | **Submit 本身还是 disabled，点击根本没触发提交**（把"没触发"误读成"弹窗找不到"） | 轮询到 enabled 再点；弹窗文案容错 `Confirm Submission\|Confirm\|Yes, submit` |
| E3 | 属性面板全绿、`assert_clean` 过，预览页 Submit 仍 disabled 且零报错 | 存在 **DOM 未标必填的软性必填** | 把该类目实测清单里的 textarea 类字段全填上；`facts` 用 `"optional": [...]` 兼容跨类目缺失 |

**E3 实测证据（同一字段、相邻两个类目标注不一致）**：
- Cellphone Cables：`Attribute.whats_in_the_box` 在 DOM 里 `data-isrequired=false` → 不填时预览页 Submit 持续 disabled（诊断跑 45s 仍 disabled、零报错）；补填后 Submit 立即 enabled 并提交成功。
- Tablet Cables（`discover_fields.py` 实测）：同一字段被标为 **REQUIRED**（textarea / `MultiLine` / 标签 `What's in the Box`）。
⇒ 结论：**不能只信 DOM 的必填标记**；换类目时把该类目的 textarea / MultiLine 类字段全部填上，比赌它是不是必填便宜得多。| E4 | 预览页 `data-submissionid` 是 `123`、React props 只有 `disabled:true` | 平台不给原因；草稿可能未落库 | 别在页面上找原因：等 enabled → 改唯一 Submission Name → Save and Close 落库后从 submissions 列表重开再提交 |

## F. 环境类

| # | 症状 | 真因 | 处置 |
|---|---|---|---|
| F1 | 页面能滚能点地址栏，但点击/键盘全无响应 | 内容进程卡死 | Cmd+R 重载（草稿会丢，回到第 1 步） |
| F2 | 界面文字像中文但字段名很怪（「羊肉袋尺寸」） | 浏览器翻译扩展翻的 | 锚点/匹配**不要依赖语言** |
| F3 | `curl https://www.takealot.com/...` 得 403 | 站点对直连/出口地区做风控 | 抽源数据一律走已登录的浏览器（`extract_listing.py`），别用 curl 抓 PDP |
| F4 | 脚本在新机器上找不到浏览器/会话 | 硬编码了 instance id / PATH | 用 `bsk session start`（不带 `--browser`）+ `preflight.py` 自检 |
| F5 | 类目选完了，但属性全部渲染成 **"Unknown field"**、`[data-fieldid]` 数量 = 0（后面 fill 全挂） | **会话退化**（不是字段必填、不是选择错） | `bsk session stop --all` → 重起会话 → 重做类目；实测 0 字段 → 27 字段 + 标签正常。**引擎已自动自愈**（`ensure_attributes`：字段没出来就重启会话重做一遍） |
| F6 | 新页面 DOM 已就绪，但 `element.click()` 没反应 | React 还没 hydrate（`domcontentloaded` 后还要 ~10–15s） | 等元素上出现 `__reactProps$…` 再点（见 `_HYD`）；`bsk` 真点击内部自带这类等待，所以它慢但不空点 |
| F7 | `bsk navigate` 一次要 ~13s | 默认 `--wait-until load`（等满载） | `goto(url, wait_until="domcontentloaded")`（实测 ~9s），真正要等的东西交给条件轮询 |

## H. 写值真假类（最隐蔽：看着点了，其实没写进去）

| # | 症状 | 真因 | 处置 |
|---|---|---|---|
| H1 | 选项"点了"但字段读回为空（如 `Attribute.connector_type`） | 按文本在**整篇文档**里找元素，命中了页面上别处的同名文字，点的是别的元素 | ① 只认**可见**元素（`getBoundingClientRect` 宽高 >0）② 点完**必须读回断言**（`_field_text`），不通过就换 observe→ref 真点击（实测这条把 Type-C 救回来了） |
| H2 | 读回断言假阴性（明明选上了却判成空） | `innerText` **不包含表单控件的值**，而下拉的已选值在 `input.value` 里 | `_field_text` 同时取 `innerText` + 所有 `input/textarea/select` 的 value（含 select 的 selectedOptions 文本） |
| H3 | 类目末级（叶子）用 JS click 点了不生效（Next 永远不 enable） | Miller 列会**保留多列**，同名叶子在旧列里也有；按文本找到的是旧列的节点 | 末级别用 JS click（引擎里 `js_first=False`），或直接走 observe→ref；**同一个末级不要重复点**（再点就是反选） |

**性能实测（2026-09-26，同一条 B 流程）**：一次 `bsk click` 约 **10–18s**（含内部稳定性等待），`observe` 1.3–4s，`_js` 0.04s，JS `el.click()` 0.1s。所以：类目快路（前几级 JS 点击）能省 ~60s，但末级不可靠 → **快路默认关闭**，想看/实验时用 `TL_FAST=1`（失败会自动硬重置并回退到 observe+ref，最坏情况只多花时间、不会把向导搞坏）。
