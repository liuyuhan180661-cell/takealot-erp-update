# scripts —— 运行入口（照这个顺序用）

前提：已装 `bsk` CLI + Chrome 扩展，且 Chrome 登录了卖家后台。
工作目录默认 `~/.hermes/portal_cua`，可用环境变量改：`export TL_WORKDIR=/your/dir`。

```sh
# 0) 自检：7 项 PASS 才能开工（不需要管理员权限）
python3 preflight.py

# 1) 换类目 / 首次接触：拿该类的真字段清单（必填 + 控件类型 + 标签）
python3 discover_fields.py "Consumer Electronics" "Electronic Accessories" "Cellphone Cables"
#    → $TL_WORKDIR/manifests/fields_*.json

# 2A) 自编辑新建：用户给事实 + 本地图
python3 create_listing.py ../templates/facts_A_backpack.json --no-submit   # 先验到断言过
python3 create_listing.py ../templates/facts_A_backpack.json              # 验过再正式提交

# 2B) 拆解重塑：给一条 takealot listing
python3 extract_listing.py "https://www.takealot.com/xxx/PLIDxxxxxxxx" my_src   # ① 抽取：标题/图 URL/规格（已验，产物在 manifests/）
# ② ⚠️ 现状（2026-09-26 定版）：manifest → facts 这步**没有自动化**——缺一个转换器。
#    现在要人工/agent 按 ../templates/facts_B_cable.json 写「重写后的文案 + 属性映射 + 条码策略」。
#    ⇒ **B 是半自动：不能直接挂定时任务**（A 场景才可以）。
python3 create_listing.py facts_B_cable.json                                  # ③ 写值侧已验（5551654，服务端 description 477 字 ✅）

# 3) 出问题时
python3 diag_preview.py facts_B_cable.json    # 预览页 Submit 为什么 disabled
bsk doctor                                    # 环境问题
```

| 文件 | 作用 |
|---|---|
| `tl_engine.py` | 内核：`data-fieldid` 写值、`os_paste`（Draft 富文本）、图片下载 + 免权限 drop、分区 Next、`assert_clean`、`submit`（含兜底链） |
| `create_listing.py` | 入口：喂 facts JSON 跑一条（`--no-submit` 只建草稿） |
| `discover_fields.py` | 类目字段发现 |
| `extract_listing.py` | B1：PDP → manifest（标题/品牌/图 URL/规格） |
| `replicate_facts.py` | B2：manifest → facts **骨架**（字段名/图片 s-zoom/条码位由脚本保证，内容留给模型填） |
| `check_facts.py` | B3：**守门**。离线查必填/字段名/图片档位/条码口径/照抄风险；`--live` 让引擎真去选一遍下拉值 |
| `diag_preview.py` | 预览页 Submit disabled 诊断（React props + 页面提示） |
| `verify_persisted.py` | **验收（唯一判据）**：服务端回读 description 与 facts **逐字比**（可反查 facts；差异打印位置 + 上下文；末尾 ±2 字标近似） |
| `preflight.py` | 交付自检 7 项（客户机可自证；类目面板不出时自带硬重置自愈） |
| `verify_title_paste.py` | 富文本写入验收一条命令：确认「置前 + ⌘V」能不能落进 agent 窗口（`--full` 再跑 A 场景到 `assert_clean`） |
| `tl_engine.py` | 内核；也可当命令用：`python3 tl_engine.py --selftest-paste` 自证 OS 粘贴原语（跨平台） |
| `cors_http.py` | 本地 CORS 静态服务（图片上传用；引擎自己起/自己收，端口自动挑空） |
| `bskhelp.py` | bsk 封装（observe / ref / click / fill）；SID 读 `$BSK_SID_FILE`（默认 `/tmp/bsk_sid`） |

## 平台

- macOS / Windows 都内置（`tl_engine.py` 按 `sys.platform` 分支；Windows 走 ctypes `keybd_event` + tkinter 剪贴板，不依赖 PowerShell）。
- 交付到 Windows 客户机时，先让客户在**桌面上**（不是 SSH/RDP 会话）跑 `python3 tl_engine.py --selftest-paste`，看到 `PASS` 再跑正式流程。

产出物（都在 `$TL_WORKDIR`）：`runs/<name>.report.json`（每次运行的结果+提交凭证）、`manifests/`（类目字段 + 源 listing 抽取）、`assets/<name>/`（下载复用的图）。
每次提交的验收 = report 里的 `submission.cells`：日期 / 状态 `In Review` / 提交名 / Submission ID / 商品数。
