---
name: ecom-product-images
description: Use when 用户要出电商商品图（白底图／整套套图／场景图／图片翻译／文生图／图生图）。自然语言驱动本地引擎出图并落盘到桌面。
category: productivity
---

# 电商商品图工作台（自然语言 → 一整套图）

把「一张产品图」变成「一整套可上架素材」：白底主图、展示图、场景图、使用场景、细节图、详情宽幅图、参数信息图，以及图片翻译（保真档／重绘档）。**不做插件、不做界面**——用户自然语言说需求，agent 按下面的固定词表路由到命令。

## 0. 硬规则（先看这五条）

1. **文字永远本地排版（Pillow），不交给扩散模型。** 实测：`agnes-image-2.5-flash` 把副标题写成 `2 UB + 3 PD`、把 `Dispositivo Compatibile` 写成 `Dispoomhes`；换 `agnes-image-2.1-flash` 同一 prompt 又全对 → 版本间行为不一致，赌不得。所以生成阶段一律在 prompt 里禁止出字（`Do NOT print any text`），出图后用 `compose.py overlay` 叠字。
2. **精确像素必须本地后处理。** 实测请求 `1200x1600` 实出 `864x1152`（比例生效、像素被归一化），`sips`/Pillow 再规范化到平台像素。
3. **上游会偶发 5xx**（`503 no available server`、`500 Failed to reach upstream`）→ 引擎已内置重试与退避；单张 15~40s，整套 10 张约 5~8 分钟。
4. **参考图决定保真度（实测分水岭）**：
   - 干净产品本体照 → 重绘白底 `fidelity 9/10`、包装印刷文字全对、`usable=true`（实测 720×720 焊锡丝 → 1500×1500）。
   - 带印刷品牌的包装/营销图 → 重绘掉到 `fidelity 5~6`、盒面文字被改错、`usable=false`。
   → 所以：参考图优先要**干净产品照**。但注意：**白底图和套图根本不需要靠模型重绘产品**——本地抠图（`--engine local`）已经实测可用且**产品像素零改动**（见第 3 节）；拿到营销图/包装图时走抠图（或合成）路线，不要拿重绘版当主图。
5. **包装/产品本体上的文字一律不动**（用户的硬口径）：翻译只翻画面上的**文案描述**（标题、副标题、banner、卖点、说明），商品本身/包装上原本印的字保持原样，不翻不改。
   - 保真档：`Ext.ignoreEntityRecognize="false"`（默认，= 执行主体识别 → 跳过印在主体上的字）；只有用户明确说「连包装一起翻」才加 `--translate-packaging-text`。
   - 重绘档：prompt 已写死只译营销文案、包装文字保持原样；验收时 `packaging_text_unchanged=false` 直接判不可用。
   - 套图生成同理：场景/详情图里产品带的包装字属「产品像素」，重绘会改字 → 这类图优先走「抠图产品 + 生成背景」合成，而不是让模型重画产品。

## 1. 意图路由（确定性：按词表命中，不要自己发挥）

| 用户会说的话 | 路由到 | 说明 |
|---|---|---|
| 白底图 / 主图 / 白底主图 / 纯白底 | `white` | 单张白底；**默认就应该是 `--engine local`**（免费离线、像素零改动），要重绘才用 `model` |
| 套图 / 整套图 / 一整套 / 全套商品图 / 出套图 | `set` | 平台规格 → 文案 → 逐图位生成 → 叠字 → 平台像素 |
| （默认推荐）套图但产品不能变 / 包装不能改字 | `set --composite` | 本地抠图 + 模型只画背景 + 本地合成 → 产品像素零改动 |
| 场景图 / 使用场景 / 生活图 | `set --gallery N --detail 0`（配 `--scene`） | 只出画廊图位 |
| 详情图 / 详情页 / 卖点图 / 参数图 / 规格图 | `set --gallery 0 --detail N` | 宽幅 16:9 |
| 文生图 / 画一张 / 生成一张（无参考图） | `gen --prompt "..."` | 纯文本出图 |
| 按这张图改 / 换个背景 / 加个标题 | `gen --ref 图 --prompt "..."` | 图生图 |
| 翻译 / 译图 / 翻成英文（罗马尼亚语…） | `translate`（默认 `--mode auto`） | **自动选档**：百炼 Key → `bailian`（主路线）；只有阿里云 AK → `precise`；都没有 → `local`（离线兜底），并打印选了哪条 |
| 精装 / 艺术字 / 高保真重绘 | `translate --mode hifi` | 重绘档：仅当保真档做不了时用（实测很差） |
| 检查 / 自检 / 验收 / 能不能上架 | `check` | 视觉模型对比原图与产出 |
| 自检面板 / 我的通道通不通 | `doctor` | 输出可贴回的表格 |

缺参数就用默认：平台 `takealot`、语言取平台 `copy_lang`、张数取平台默认值。**不要反问**，直接按默认跑，跑完告诉用户改哪里能重跑。

## 1.5 安装（只有安装地址，不带任何二进制/凭证）

客户机一条命令（幂等，实测干净机器 **53 秒**跑完）：

```bash
bash ~/.hermes/skills/ecom-product-images/scripts/install.sh            # macOS / Linux
bash ~/.hermes/skills/ecom-product-images/scripts/install.sh --with-isnet
# Windows：powershell -ExecutionPolicy Bypass -File scripts\install.ps1 [-WithIsnet]
```

| 步骤 | 内容 | 来自 |
|---|---|---|
| venv | `~/.hermes/venvs/imgtools` | `uv venv` 或 `python -m venv`（可用 `IMGTOOLS_VENV` 换位置） |
| 基础包 | Pillow / numpy / onnxruntime | pypi（默认阿里云镜像，`PIP_INDEX_URL` 可换） |
| OCR 包 | rapidocr-onnxruntime + opencv-python-headless | pypi（**macOS<13 自动铉 opencv 4.9.0.80 + numpy 1.26.4**，避开源码编译） |
| 抠图模型 | u2net.onnx 168MB（可选 isnet 170MB） | github release，直连失败自动降级 gh-proxy / ghproxy.net（`IMGTOOLS_MODELS` 可换位置） |

**不做什么**：不把模型/字体/wheel 打进 skill（skill 本体 132KB，最大单文件 40KB）；不内置任何 key；不装 rembg 全家桶。
云端档（阿里云）**不需要额外安装**，配好 AccessKey 就生效（自动路由）。

## 2. 命令面

引擎：`~/.hermes/skills/ecom-product-images/scripts/imgctl.py`（纯 stdlib，Mac/Windows 同一份）。

```bash
S=~/.hermes/skills/ecom-product-images/scripts

python3 $S/imgctl.py doctor                                  # 通道自检（key/venv/字体/连通性）
python3 $S/imgctl.py copy  --images 图.jpg --lang English --count 3
python3 $S/imgctl.py gen   --prompt "..." [--ref 图] [--ratio 1:1] [--platform takealot]
python3 $S/imgctl.py white --image 图.jpg [--engine local|model|aliyun] [--matte-model u2net|isnet-general-use] [--platform takealot]
python3 $S/imgctl.py translate --image 图.jpg --to en [--from auto] [--mode precise|hifi] [--field e-commerce] [--translate-packaging-text] [--editor-data]
python3 $S/imgctl.py set   --images 图1.jpg [图2.jpg ...] --platform takealot --gallery 5 --detail 5 \
                           [--composite] [--product-rgba 抠好的.png] [--matte-model u2net|isnet-general-use] [--product-scale 0.7] \
                           [--lang English] [--scene "面包店柜台"] [--info "120W/5口"] [--check]
python3 $S/imgctl.py check --ref 原图.jpg --image 产出.png | --dir 输出目录 [--kind translate]
python3 $S/scripts/matte.py 图.png --out 抠好的.png --model u2net --bg white --verify   # 单跑抠图
```

输出：`~/Desktop/作图输出/<日期>-<产品名>/`，每张 `<序号>_<图位>_<宽>x<高>.png` + `manifest.json`（prompt、模型、耗时、计划文字、自检结论）。

平台规格表（`scripts/specs.json`，改这里就换规范）：

| 平台 | 文案语言 | 画廊 | 详情 | 主图规则 |
|---|---|---|---|---|
| takealot | English | 1:1 → 1500×1500 ×5 | 16:9 → 1500×844 ×5 | 纯白底、无文字、产品约 85% |
| emag | Romanian | 1:1 → 1500×1500 ×5 | 16:9 → 1500×844 ×5 | 纯白底、无文字 |
| ozon | Russian | 2:3 → 1200×1600 ×5 | 16:9 → 1500×844 ×5 | 纯白底、无文字、占比 60%~90% |
| custom | 自选 | 1:1 → 1024×1024 | 16:9 → 1500×844 | 无 |

## 3. 通道与 key（skill 不内置任何 key，凭证由使用方 agent 自己匹配）

**本 skill 只做技术路线，不含任何凭证。** 使用方的 agent 照下表在自己的套餐里取 key、写进 `~/.hermes/.env`，然后用 `imgctl.py doctor` 自证：

| 用途 | 通道 | 需要的变量 | 开通位置 |
|---|---|---|---|
| 画面生成 / 图生图 / 重绘 | Agnes `images/generations`（`agnes-image-2.1/2.5-flash`，`image` 支持单张或数组，1~4 张参考图） | `AGNES_NEW_KEY`（或 `AGNES_API_KEY`） | Agnes 套餐（Token Plan） |
| 文案 / 看图 / 出图自检 | DeepSeek `chat/completions`（`deepseek-flash`，原生多模态） | `DEEPSEEK_API_KEY` | DeepSeek 平台 |
| **本地抠图（默认免费）** | onnxruntime CPU 直跑模型（`scripts/matte.py`）+ Pillow | 本地图 | 本地透明 PNG / 白底 PNG | 白底主图、套图合成；**不需任何 key、离线可跑、产品像素零改动** |
| 白底图保真（云端备选） | 阿里云 `imageseg.SegmentCommodity`（`ReturnForm=whiteBK` 直接出白底） | **只吃公网 URL** | 白底图 URL | 本地图上传麻烦时用；有公网图 URL 时可用 |
| **百炼·千问图像翻译（主路线）** | `qwen-mt-image-2.0`（同步 `/api/v1/services/aigc/image2image/image-synthesis`；本地图自动上传换 `oss://`） | `DASHSCOPE_API_KEY` | 百炼控制台 → API-KEY（**不是** 阿里云 AccessKey） |
| 图片翻译保真（备选） | 阿里云 `alimt.TranslateImage`（`Field=e-commerce`，`ImageBase64` 支持本地图） | `ALIYUN_ACCESS_KEY_ID` / `ALIYUN_ACCESS_KEY_SECRET` | 阿里云 → 机器翻译 |
| 图片翻译保真（备选） | 百度图片翻译 V2（含高精擦除） | `BAIDU_TRANSLATE_APPID` / `BAIDU_TRANSLATE_KEY` | 百度翻译开放平台 |
| **本地 OCR（翻译用）** | RapidOCR/PP-OCR onnx（`scripts/translate_local.py`，离线） | 本地图 | 文字块+坐标 | 本地翻译档的读字，零凭证 |
| 本地排版 | Pillow | `~/.hermes/venvs/imgtools` | `uv venv` + 见 `references/providers.md` 的钉版本命令 |

> 装 OCR 依赖的坑（macOS）：`opencv-python-headless` 最新版只出 macOS 13+ 的 wheel，本机 12.7 会掉进源码编译（uv 卡死十分钟以上）。**钉 `opencv-python-headless==4.9.0.80` + `numpy==1.26.4`**（4.9 是 numpy1 编的，配 numpy2 会 `_ARRAY_API not found`）；Windows 直接用最新即可。

**凭证自配流程（交给客户 agent 执行，不要人工干预）**

1. 跑 `python3 $S/imgctl.py doctor` → 看缺哪个通道、缺哪个变量名
2. 客户 agent 用自己的套餐凭据补齐 `~/.hermes/.env`（只写变量名对应的值，不回显）
3. 再跑 `doctor` 直到目标通道 `OK`
4. 缺凭证时的降级：`translate --mode precise` 缺阿里云凭证会**打印三条可行动选项**（配凭证 / 换 `--mode hifi` 重绘 / 换百度保真档）而不是抛裸异常；`set` 缺 Agnes key 则直接失败报变量名

- 阿里云两把凭证别搞混：**AccessKey**（`alimt`/`imageseg` 用，ACS3 签名，引擎已内置无 SDK 实现）与 **百炼 `DASHSCOPE_API_KEY`**（`wanx*`/`qwen*` 模型用）是同一账号下的两把不同凭证。
- `SegmentCommodity` 与批量翻译接口都只接受**公网 URL**（≤3MB、<2000×2000），本地图走 `TranslateImage`（支持 base64）或 `--engine model` 重绘。
- 详细契约与错误码见 `references/providers.md`。

## 3.5 本地抠图（免费离线 —— 普通电脑实测数据）

**结论：可以跑，且不要钱。** 在普通 Intel Mac（无 GPU）实测数据：

| 项 | u2net（默认） | isnet-general-use |
|---|---|---|
| 模型体积 | 168 MB | 170 MB |
| 首次下载 | 13.8 s（10～13 MB/s） | 17.9 s |
| 单张推理（720×720） | **3～5 s** | 11 s |
| 峰值内存 | **~550 MB** | ~890 MB |
| 边缘细节 | 够用于电商白底 | 更细，但慢 3 倍 |

- 依赖：`onnxruntime` + `numpy` + `Pillow`（venv 共 ~166 MB；**不用装 rembg 全家桶**，不下 scikit-image/pymatting）。
- 许可：模型权重 **U-2-Net = Apache-2.0**、**DIS(isnet) = Apache-2.0**；rembg 代码 MIT。均可商用、无 API 费（只需保留许可文本）。
- 模型下载（一次性，之后全离线；中国网络慢就换 gh-proxy）：
  ```bash
  curl -L -o ~/.hermes/venvs/models/u2net.onnx \
    https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx
  ```
- **产品像素零改动（实测可自证）**：模型只产出 alpha 掩膜，`--verify` 实测 `product_pixels_unchanged=true`（掩膜覆盖区 11～19 万像素，`max_abs_diff=0`）。边缘 1～2px 羽化区会与背景混合（正常）。
- 实测终端到终端：`white --engine local` → 1500×1500 白底图，自检 `fidelity 9/10`、包装文字全对、`usable=true`，全程 5.3 s。
- 已知限制：源图小于交付像素时是**放大**（720→1500），视觉判定会看到轻微软化；有更高分辨率原图优先用它。

## 3.6 合成路线（套图保真的推荐做法）

`set --composite`：① 本地抠出产品透明 PNG；② 模型**只画背景板**（prompt 里写死 `NO product, NO object`，主图白底连模型都不调）；③ 本地合成（缩放/落位/投影）。
→ 产品像素与包装文字**不可能被模型改掉**（它们根本没进模型），这是把「包装上原来是什么就什么」从翻译扩到整套图的唯一确定性做法。

实测：焊锡丝 2 张（主图=白底合成、展示图=生成工作室背景+合成）→ 像素 1500×1500、自检 `usable=true`（主图 7/10：就是放大软化导致的；展示图 9/10）。

## 4. 验收（客户机可自证）

出图后必跑：
```bash
python3 $S/imgctl.py set ... --check        # 或单独 check --dir <输出目录>
```
判据（`references/acceptance.md`）：`same_product=true` 且 `fidelity_1_10>=7` 且 `text_rendered` 与计划文字完全一致 且 `usable=true`。任一不满足 → 该张重生成或改本地叠字，并把结论写进交付说明。
抠图/合成路线额外两条硬判据：**`product_pixels_unchanged=true`**（`matte.py --verify` 实测 `max_abs_diff=0`）与 `masked_pixels_checked>0`（掩膜非空）。这两个是确定性证据，不受视觉判定波动影响。

## 5. 图片翻译怎么解决（四档：百炼主路线 / 阿里云备选 / 本地兜底 / 重绘不用）

| 档 | 接口 | 输入 | 输出 | 用在哪 |
|---|---|---|---|---|
| **百炼·主路线** | 阿里云百炼 `qwen-mt-image-2.0`（`/services/aigc/image2image/image-synthesis`，同步） | 公网 URL 或百炼临时 `oss://`（本地图自动上传） | `output.image_url`（与原图同尺寸 JPG，24h 有效） | **默认首选**：一把 `DASHSCOPE_API_KEY`，保排版，0.004 元/张，自带商品主体检测 |
| **阿里云·备选** | 阿里云 `alimt.TranslateImage`（`Field=e-commerce`） | 本地图 base64 或 URL | `Data.FinalImageUrl` / `InPaintingUrl` / `TemplateJson` | 有阿里云 AccessKey 但没百炼 Key 时；0.06 元/张 |
| **本地·兜底** | RapidOCR + u2net 掩膜 + Pillow 重排（`--mode local`） | 本地图 | 本地 PNG + `manifest.json` | 零凭证/离线/没开通云端时；普通字体文案图 |
| **重绘（艺术字）** | Agnes 图生图 `--mode hifi` | 本地图 | 整图重绘 | 实测很差，默认不用 |

同步调用、不设异步头；**图片需 15~8192px、≤100MB、宽高比 1:10~10:1**；本地图用百炼官方临时上传（getPolicy → OSS 直传 → `oss://…`，48h），带 `X-DashScope-OssResourceResolve: enable` 头。

辅助：`GetImageDiagnose`（只给 URL → `Language`，用户说「翻成英文」但不知原语种时先识别）；老接口 `GetImageTranslate`（返回 `Orc` 文字块 + `PictureEditor` 的 psd 数据）→ 需要**自建文字层**（Pillow 自己叠字、字体自选）时用它拿文字位置。

- 「要不要翻商品主体上的字」= `Ext.ignoreEntityRecognize`（电商域默认会自动跳过印在商品主体上的字）——与易可图那个「是否翻译商品主体文字」开关等价。**默认 false = 包装文字保持原样（我们的硬口径）**；要连包装一起翻才传 `--translate-packaging-text`。
- 验收：`check` 对翻译产出走专门判据（`marketing_copy_translated` / `packaging_text_unchanged` / `spelling_correct`）；`packaging_text_unchanged=false` 直接判不可用。
- 译图必须过 `check`：`text_rendered` 抄录的文字应与目标语言文案一致且拼写正确。
- 对字体/排版不满意时：拿 `InPaintingUrl`（已擦字的背景图）+ 本地叠字重排，**不要重跑模型**。
- 当前状态：保真档按官方契约实现（`TranslateImage` 用 base64 传本地图），但阿里云凭证未配 → **尚未跑过真实请求**；重绘档已实测（会出错字，只做兜底）。

## 5.1 翻译自动路由（主路线 = 百炼，兜底 = 本地）

`translate` 默认 `--mode auto`，**确定性判定，不靠模型猜**（用户只说「翻成英文」就跑）：

```
有 DASHSCOPE_API_KEY → bailian（百炼 qwen-mt-image-2.0：0.004 元/张、保排版、主体文字不翻）= 主路线
有 阿里云 AccessKey    → precise（alimt 电商图片翻译：0.06 元/张）
都没有               → local  （本地保真：离线、零成本、OCR 字节级自证）= 兜底
```
选档结果打到 stderr（`[translation] 选档：local —— …`），可审计。

**百炼档的两个关键参数**（都已在 CLI 暴露）：
- `config.imageSegment: true`（默认）→ **不翻译商品主体/Logo 上的文字**，就是用户的硬口径；要全翻才加 `--no-image-segment`
- `ext.terminologies` → 术语干预，锁定品牌/型号或固定译法：`--term "CF-10=CF-10" --term "焊锡丝=Solder Wire"`（可重复）
- `ext.domainHint` → 英文领域提示（≤200 词），影响译文风格：`--domain-hint "..."`

**成本对比（给客户的真实数字）**：百炼千问图像翻译 **0.004 元/张**（2.0）／0.003（1.0），送 100 张；阿里云 alimt 电商图片翻译 0.06 元/张、每月 100 张免费、失败不计费 → **百炼便宜 15 倍，且 key 与抠图/其他百炼能力共用一把**。

**已实测**：假 key 调百炼 getPolicy 返回 `InvalidApiKey`（非 404）→ 端点、鉴权头、请求体形状均已验证，只差一把有效 Key；阿里云那条同理（返回 `InvalidAccessKeyId.NotFound`）。

## 5.2 本地保真档（`--mode local`，零凭证 —— 实测已跑通）

不依赖任何云凭证，把云端保真档干的三件事全在本地做：**OCR 拿字块 → 抠图掩膜判断「字在商品主体上」→ 只翻主体外的文案 → 擦字 + 原位置字体重排 → 产出再 OCR 自证**。

- 「字在商品主体上就不翻」= 掩膜覆盖率 ≥ 0.6 → 跳过（`ignoreEntityRecognize` 的确定性本地等价；`--translate-inside-product` 可关掉）
- 字色/背景色从原图采样（不猜黑/白），字号二分适配框宽高，粗体按原图墨迹占比判断
- 实测（罗马尼亚语设计图 → 英语）：4 个文字块，主体上 1 块不翻 ✓，3 块翻译重排 ✓，**自证 4/4 一致**，17 秒，全程离线
- 局限（如实）：① 设计字体/艺术字会掉档（本地只能用系统字体，霓虹描边这类效果无法还原）；② 纹理背景擦字会留痕（manifest 里 `texture_bg_warn` 计数）；③ OCR 漏字就少翻（不会乱改）
- 选档口诀：**普通字体文案图 → `local`；设计图/艺术字/要原版式 → 配阿里云 `precise`**

## 6. 什么时候才需要「重塑艺术字」（重绘档 —— 实测很差，默认不用）

**实测警告（2026-09-27）**：用 `--mode hifi`（Agnes 图生图）翻一张罗马尼亚语设计图，产出全是乱码：`Niên / rpptrs / Nigeria Flats / Anprechtsrybwls`，**连包装原本的字都被改掉了**；专用判据当场判 `marketing_copy_translated=false`、`packaging_text_unchanged=false`、`usable=false`。
→ 结论：**翻译一律走保真档；重绘档不是翻译方案，只是最后手段**，且要质量就换 grsai `gpt-image-2`（OpenListing 已验证的路线），用完必须过 `check --kind translate`。

保真档（阿里云/百度图片翻译）不做艺术字重塑；只有下面三种情况才考虑重绘档：① 原图文字是设计字体/变形艺术字，擦除重排会丢设计感；② 目标语言字符集与原字体不兼容（中文 → 罗马尼亚语/俄语/泰语，变音符号缺字）；③ 文字与产品图像交织（印在包装曲面上）擦不干净。用完必须过 `check --kind translate`；不过就回去走「`InPaintingUrl` 已擦字底图 + 本地叠字」自己排，不要继续赌模型。

## 7. 已评估过的外部工具（别重复调研）

**易可图（yiketu.com）**：电商在线作图 SaaS（Vue SPA + Chrome MV3 扩展 + App）。有「开放平台」页面但**无公开文档站、只有商务「联系我们」入口**，自述能力 = 智能抠图/图片编辑/AI商拍/模版设计，**图片翻译不在开放能力清单里**；它的图片翻译是「保真档（擦字+原版式重排）+ 手动微调」，不是艺术字重塑。结论：值得借鉴功能，**不适合作为接入底座**（无自助 API、要登录态、改版即失效）。

## 8. 参考文件

- `references/prompts.md` — 图位 prompt 库与改写规则（product-preserving 句式、禁字句式、场景注入）
- `references/providers.md` — 各通道契约、key 配置、错误码与排障
- `references/acceptance.md` — 自检判据与平台主图合规清单
