# 自愈手册：症状 → 判断 → 处置（agent 遇到突发状况照这个做）

> 原则：**先取证再动手**。每一步的"失败"必须落到一个可读的信号上（DOM 状态、按钮属性、平台表格），
> 不允许用"再试一次"当处理。失败即停是默认值；只有下面明确写了自愈动作的才继续。

## 0. 三条硬规则

1. **只在有断言的地方继续**：`data-error` 全 false / 无错误文案 / 该填的必填非空 / 预览页 Submit enabled。没断言就不要往下走。
2. **一次只改一个变量**：重跑前想清楚"这次验证哪个假设"，不要一口气改一堆再重跑（否则不知道是哪条生效）。
3. **失败必留证据**：把当时的 URL / `location.href`、按钮属性、错误文案、报告 JSON 存下来。没证据的自愈不算自愈。

## 1. 自愈表（按症状）

| 症状 | 先取证 | 判断 | 处置 |
|---|---|---|---|
| 页面要不到元素 | `location.href` + `document.querySelector('[data-sectionname]')` | 是否被踢回登录页 / 是否还在同一向导步 | 被踢回 → 报用户去登录；还在 → 等 2s 重读一次，仍无则报该步失败 |
| 点击没反应 | 目标元素 `disabled` / 是否在视口内 / 是否存在 overlay | 是 disabled 还是没点到 | disabled → 等 enabled（最多 45s）再点；不可见 → `scrollIntoView` 后重试一次 |
| 写值后读回为空 | 读回值 + `data-changed` / `data-error` | 是真没写进还是假阴性 | 富文本：**先等服务端状态落定**（Draft 最后一次输入事件落后一步）→ 缺尾就补尾 / 多就"全选 + `bsk press Delete`"清空重打；**不要**用 OS 粘贴（本机被 Chrome 吞掉）、**不要**用 `bsk fill`/`insertText`（不持久）→ 见 `rich-input-routes.md`。普通 input：重写一次，仍空则报错（不静默继续） |
| 图片没进图集 | 分区标题的 `N Images` + `blob:`/`covers_images` 计数 | 是没传还是没计数对 | 计数口径先修（D5）；确实没传 → 查本地服务是否真的在服务该目录（D4） |
| 校验报错但找不到哪个字段 | `[data-isrequired="true"]` + `[data-error="true"]` | 哪些字段被平台自己标错 | 只补被标的字段；DOM 没标但提交被卡 → 按 E3 补软性必填 |
| 预览页 Submit 不动 | 按钮 `disabled` + `data-submissionid` + React props | 等它亮 / 改名单 / 落库重开 | 先等 45s；再改唯一 Submission Name；再 Save and Close → 从列表重开 |
| 页面卡死（能滚不能点） | 连续两帧截图是否相同 | 内容进程卡死 | Cmd+R 重载（草稿丢），从类目重跑 |
| 类目点了但表单不出现（0 字段） | `[data-fieldid]` 数量 | 是 SPA 残留反选，还是会话退化 | 先硬重置（about:blank → 新建页）；仍 0 → `bsk session stop --all` 后重起会话（实测字段 0→27 回来） |
| 属性全渲染成 "Unknown field" | 字段总数 + 属性区文本 | 会话退化的特征 | 同上（引擎已自动自愈；人工路就是重启会话） |
| 选项点了但字段读回空 | `_field_text(fieldid)` | 命中了页面上别处的同名文字 | 只用可见元素 + 读回断言；不过就换 observe→ref 真点击 |
| 富文本写不进 / 写了但服务端是空 | **判据只有一个**：已提交 listing 回读（`verify_persisted.py <submission_id>`）。**草稿从不落富文本**（重开必空，实测多次）→ 拿草稿当判据会得到假阴性 | 是"页面状态被改了"还是"真的持久化了" | 写入路只有一条：**`bsk press` 逐字真实按键**（477/477 精确，152ms/字）；❌ fiber 注入 / `bsk fill` / `insertText` / 合成事件 / OS ⌘V **一律不持久** → 见 `rich-input-routes.md` |
| 富文本少 1 字 / 多 1 字 | Draft 真身长度 vs 期望长度 | 平台**最后一次输入事件总落后一步**（543→542）；抢着补尾会撞上迟到落值 → 544 | 等 ≤30s → 缺就**补尾** → 仍不对就**全选+Delete 清空重打**（≤1 次）；**`Backspace` 实测无效**；末尾 ±2 字按要求打警告并接受（不许伪装精确），提交后回读服务端 |
| 预览页 Submit 灰着且找不到原因 | **先看引擎自带取证**：日志里 `submit 取证` 会打印正文含 `error/required/missing/invalid` 的行 + `[data-error="true"]` 字段清单 | 是平台校验没过、还是草稿没落库、还是向导没走完 | ⚠️ **别扫 `Duplicate`**——那是草稿页上的**普通操作按钮**（`Edit`/`Duplicate`/`Delete`）。顺序：等 45s → 改唯一 Submission Name → Save and Close 落库 → 从列表重开 → **重开后必须重走分区 Next 再提交**（否则按钮在表单页上必然禁用）+ 重写富文本 |
| Chrome 点不开 / 没窗口 / 扩展 `no browsers connected` | `pgrep -f 'Google Chrome.app/Contents/MacOS/Google Chrome'` | 有残留 headless 实例占着 bundle id（`open -a` 被 handoff）；或窗口全关导致扩展休眠 | 先 `kill` 掉那个 headless pid → `open -a "Google Chrome"`；**开跑前必须至少留一个 Chrome 窗口**（pitfalls G4/G5） |
| 类目/字段结构变了 | `discover_fields.py` 输出对比上次 manifest | 平台改版 | **重学**：重跑 discover_fields → 更新 facts 的字段名 → 跑一条 `--no-submit` 验到断言通过 → 再提交 |
| 同一步连续失败 2 次 | 两次的日志/截图 | 是同一个错还是新错 | 同一错 → 停，把证据交给用户；新错 → 当新问题处理（别合并成一个"重试"） |

## 2. 重学流程（页面改版 / 换新类目）

换类目或平台改版时，**不要凭记忆写字段名**，走这套：

1. `python3 discover_fields.py "类目1" "类目2" "叶子"` → 得到该类的真字段清单（`data-fieldid` / 是否必填 / 控件类型 / 标签）。
2. 对比上次的 `manifests/fields_*.json`：新字段、改名、变必填的，逐条记下来。
3. 按新清单写 facts（参考 `templates/`），**先用 `--no-submit` 跑到断言全过**，看报告里的 `clean: true`。
4. 再跑一次带提交，核对 submissions 表新增行。
5. **把学到的东西写回**：新类目的字段清单留在 `manifests/`，新坑写进 `references/pitfalls.md`（带证据），facts 样例进 `templates/`。

学习成本参考：新类目首读 = 1 次 `discover_fields` + 1 次 `--no-submit` 验证（约 5-10 分钟）；同类型再来一条 = 直接 `create_listing.py`（约 6-8 分钟）。

## 3. 自我进化：经验写回哪里（做完必须落一处）

| 学到什么 | 写到哪 | 格式要求 |
|---|---|---|
| 新坑 / 新症状 | `references/pitfalls.md` | 症状→真因→处置，附实测证据（命令输出/页面信号） |
| 类目字段清单 | `manifests/fields_<slug>.json`（`discover_fields.py` 自落） | 不改手写 |
| 可复用的 facts | `templates/facts_*.json` | 参数化：字段名可换、值可换 |
| 引擎改进（新控件/新兜底） | `scripts/tl_engine.py` | 必须：能失败即停 + 注释写清"为什么"（源自哪个坑） |
| 平台机制结论（如条码留空=平台生成） | `SKILL.md` 对应章节 | 一句话结论 + 实测证据 |

**不要写的东西**：账号/操作者身份、登录凭据、客户商品数据、一次性调试路径、"今天改了 X"这类过程叙事。

## 4. 什么时候必须停（不自愈）

- 登录/2FA/验证码/短信 → 交人（本技能不碰凭据）。
- 平台弹出风控/验证页（“Verify you are human”）→ 停，交人。
- 需要删数据、下架、改价、动权限 → 超出本技能范围，停。
- 同一失败重复 3 次仍无新信息 → 停，交证据给用户（“最快止血”与“最终定版”两条方案各一条）。
