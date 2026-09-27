# 自检判据与平台主图合规清单

出图后**必须**跑 `imgctl.py check`（或 `set ... --check`）再交付。自检走 DeepSeek vision 双图对比，判据如下。

## 通过判据（全部满足才算过）

| 字段 | 判据 | 不满足怎么办 |
|---|---|---|
| `same_product` | `true` | 重生成该张；连续两次不过 → 换参考图（更干净的白底原图效果最好） |
| `fidelity_1_10` | `>= 7`（主图建议 `>= 8`） | 主图改走保真路线（抠图/保真翻译），不要用重绘版当主图 |
| `text_rendered` | 与 `manifest.json` 里的 `text_planned` **完全一致**（无计划文字时为 `none`） | 出现错字/多余字 → 把文字改回本地叠字，并在 prompt 强化禁字句 |
| `usable` | `true` | 单张重跑；整批不过 → 换模型档（`--quality high`）或换参考图 |

辅助字段 `reason` 要求中文一句话说明，交付时抄进交付说明。

## 本地翻译档（`--mode local`）的自证 —— 不靠视觉模型

`translate_local.py` 跑完会自动再 OCR 一遍产出，按位置（IoU）对上原框逐条比：

| 项 | 通过标准 |
|---|---|
| 主体外文字（`action=translate`） | 与译文相似度 ≥ 0.6 且 IoU ≥ 0.1 |
| 主体/包装上文字（`action=keep`） | 与原文相似度 = 1.0（只归一样近字符 O/0、I/1） |
| 整体 | `verify.all_pass = true`（实测 4/4） |

失败项会逐条打在终端（期望/实得/相似度/位置），直接看得到是哪一块没排好；`*.manifest.json` 里保留每块的覆盖率、字色、字号、行数、背景是否平整。

## 翻译类产出的专用判据（云端保真档 `check --kind translate`）
| 字段 | 判据 |
|---|---|
| `marketing_copy_translated` | `true`：画面上的文案描述已译成目标语言 |
| `packaging_text_unchanged` | **必须 `true`**：商品/包装上原本印的文字一字未改；为 `false` 直接判不可用（硬口径） |
| `spelling_correct` | `true`：译文拼写正确（变音符号、大小写） |
| `usable` | 三者全满足才 `true` |

不过时怎么办：① 确认走了保真档（`--mode precise`）且没加 `--translate-packaging-text`；② 仍被翻 → 改用 `InPaintingUrl`（已擦字底图）+ 本地叠字重排；③ 重绘档改不动包装字 → 直接换保真档，不要继续调 prompt。

## 平台主图合规清单（按 `specs.json` 的 `main_rules`）

- **纯白背景**：取四角像素验证，均值 ≥ 250（本地可加一行 Pillow 校验）
- **无文字/水印/横幅**：主图位 `text=false`，且 prompt 里禁字；自检 `text_rendered=none`
- **产品占比**：takealot ~85%；ozon 60%~90%（太满或太小都会被平台裁）
- **无额外 logo/边框**：prompt 里 `no watermark, no extra logos`
- **像素精确**：等于 `gallery_out`/`detail_out`（本地 `compose fit` 保证，不看模型输出尺寸）
- **格式**：PNG；若目标平台只收 JPG，用 Pillow 转存（白底图无透明通道，转 JPG 不丢内容）

## 交付时附什么

1. 输出目录（`~/Desktop/作图输出/<日期>-<产品名>/`）
2. `manifest.json`（每张的 prompt、模型、像素、计划文字）
3. 自检结果（`check` 的 JSON；`usable` 计数与总数）
4. 待人工点检项：产品 logo/丝印是否被重绘、目标语言变音符号是否正确、主图占比是否需微调

## 已知不能自动判定的

- **产品 logo/丝印的细微改动**：vision 能发现「明显不同」，但细小丝印差异要人眼复核（尤其重绘档与换背景图）
- **目标市场审美**：场景图「好不好看」只能人评，自检只判合规与保真
- **艺术字设计感**：重绘档的艺术标题是否比原设计更好，需人评
