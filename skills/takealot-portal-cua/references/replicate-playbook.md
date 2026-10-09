# B 复刻 / 新建改编：作业手册（2026-09-26 定版）

**口径（用户定）**：文案**由模型编写**；用户只提供**差异参数**（价格/规格等覆盖值）；**没给参数就按源链接上的参数重塑**；
全程**无需用户有感操作** —— 客户只要说"把这条链接改编成我们的 listing"。

## 链路（四步，两个脚本 + 模型写内容）

```bash
# ① 抽取（脚本，已验）：PDP → manifest
python3 extract_listing.py "https://www.takealot.com/xxx/PLIDxxxxxxxx" my_src

# ② 生成骨架（脚本，结构由它保证）：manifest → facts 骨架（字段名/图片档位/条码位都从类目清单来）
python3 replicate_facts.py ~/.hermes/portal_cua/manifests/src_PLIDxxxxxxxx.json my_name \
    --category "Consumer Electronics/Electronic Accessories/Cellphone Cables"

# ③ 模型填内容（唯一由模型产出的部分）：读 facts 里的 `_material`（源标题/价格/原文 4000 字）
#    写 rich_fields.title / rich_fields.description + 各属性值。差异参数有就用，没有就沿用源。
#    ❗ 事实类字段（尺寸/重量/材质/保修）**不许编**：源里没有就留空，让守门脚本报出来。

# ④ 守门（脚本，别跳过）：
python3 check_facts.py <facts.json>          # 离线：结构/必填/字段名/图片档位/条码口径/照抄风险
python3 check_facts.py <facts.json> --live   # 在线：让引擎**真去选一遍**每个下拉值（~2 分钟）

# ⑤ 跑（写值侧已验 5551654 477 字）
python3 create_listing.py <facts.json>
python3 verify_persisted.py <SID>            # 唯一验收判据
```

## 为什么必须有守门（B 的失败全在这五类，都是可静态查的）

1. 字段名不在该类目里（拼错 / 换类目了没更新清单）
2. **下拉值平台根本没有** —— 实测坑：`option 'USB Type-C Cable' not found`，而当时没人知道平台到底有哪些值
3. 必填没填够（该类目 10 项，条码也在其中）
4. 图片 URL 用了 `s-pdpxl`(459px) → **<600px 平台不报错，只把 Submit 静默禁用**
5. 文案**整段照抄**源站（**这不是判重标准**，是自查：文案本该是模型改写产物；`check_facts.py` 会拿 `_material` 原文比对 ≥40 字整段）

## 两个曾经的缺口：现在的状态

### 1. 包装尺寸 / 重量：买家页没有 → 用"默认表 + 估值标记"自动化
事实不变：这几项是**卖家侧物流属性**，PDP 从不公开（实测源页规格表只有线长、保修、连接器、箱内清单）。
处理顺序：
① `config/spec_defaults.json` 里按类目配一次（**推荐**：填完就是真零人工）；
② 没配 → **由模型按品类估值**，并在 facts 里写 `"_logistics_source": "model-estimate"` → 守门脚本把这几条必填**降级成提醒**（不拦）→ 跑完日志可追。

> 口径（用户定）：**我们只负责"能不能自动化"，不去对齐平台的判重/自创标准**。估值上线后可用真实值覆盖，或固化进默认表。

### 2. `Attribute.cable_type` 这类**可搜索 combobox**：已打通 ✅
实测 2026-09-27（`Cellphone Cables`），三条路逐一排除：
- ❌ JS 原生 click（点外层 `.ZorkInput__input-selector`、点 `input` 都试过）→ `[role=option]` 恒为 0，打不开；
- ❌ OS 级点击 → bsk 的整页 overlay 会吃掉；
- ❌ 把"读选项列表"当判据 → 没打开时读出假的 `(Optional)`，**曾据此误判"平台没有这个值"**。

**正解**（已进引擎 `pick_combobox()`；`pick_dropdown()` 发现 `INPUT[role=combobox]` 会自动改走它，失败退回老路不回归）：
`_reveal` 滚到可见 → JS `focus()` → **`bsk press ArrowDown`**（真实按键，1 秒开出 30 个选项）→ 需要就打前缀过滤 → **JS 点那个 `[role=option]`** → 读回断言。
实测：`pick_dropdown("Attribute.cable_type", "USB Type-C Cable")` → **True / 2.8s**。

⚠️ `Enter` **不提交**（按了字段仍是空）→ 必须真点到选项。
平台真实选项（Cellphone Cables）：`USB Cable` / `USB Type-C Cable` / `Micro USB Cable` / `Mini USB Cable`。
出错时会**报出打开后的真实选项**；值确实不存在时直接失败，不再退老路白跑 30s。

## 验收纪律（照旧）

- 唯一判据 = `verify_persisted.py <SID>` 回读**服务端**；草稿不落富文本，验草稿会得到假阴性。
- 图片走 **URL 直塞**（≈3.8s/张，零下载）；失败自动退回本地下载 + drop。
- 一条 ≈5.5 分钟（富文本 152 ms/字占大头）。
