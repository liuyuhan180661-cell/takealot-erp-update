# 通道契约、key 与排障

## Agnes（画面生成 / 图生图 / 重绘）

- 端点：`POST https://apihub.agnes-ai.com/v1/images/generations`
- 头：`Authorization: Bearer $AGNES_NEW_KEY`（`AGNES_API_KEY` 是另一个 provider 的 key，别混）
- 体：`{"model":"agnes-image-2.1-flash","prompt":"...","size":"1024x1024"}`，图生图加 `"image": "<dataURL>"` 或 `"image": ["<dataURL>","<dataURL>"]`
- 模型：`agnes-image-2.1-flash`（文字/细节更稳）／`agnes-image-2.5-flash`（更快）
- 返回：`{"data":[{"url":"https://platform-outputs.agnes-ai.space/images/i2i/....png"}]}`（`/images/i2i/` 表示走了图生图）
- 实测：请求 `1200x1600` → 实出 `864x1152`（比例对、像素归一化）→ 必须本地规范化到平台像素
- 实测报错：`size:"2:3"` → 500 `Failed to reach upstream`；瞬时 `503 no available server` / `do_request_failed` → 重试 3~4 次即可
- 图生图不保证产品像素不变：会重绘 logo/丝印。主图保真请走抠图或保真翻译。
- 另有 `/v1/images/edits`（multipart）端点，实测 `503 no available server`，不要用。

## DeepSeek（文案 / 看图 / 自检）

- 端点：`POST https://api.deepseek.com/v1/chat/completions`
- 模型：`deepseek-flash`（原生多模态，`input_modalities: text+image`；`deepseek-v4-pro` 只吃文本）
- 图片用 `{"type":"image_url","image_url":{"url":"data:image/jpeg;base64,..."}}`，一次 1~3 张够用
- 坑：`max_tokens` 给小了会被 reasoning 吃光 → `content` 为空字符串。**给 2000~4000**；要确定性就把输出约束成 JSON 并 `temperature` 保持默认
- 用途：看图出 headline/subtitle/specs（`copy`）、原图 vs 产出的保真/文字判定（`check`）

## 本地抠图（免费离线，无 key 无 API 费）

`scripts/matte.py`（onnxruntime CPU + Pillow，**不需要 rembg 全家桶**）

```bash
# 模型一次性下载（之后全离线；中国网络慢就前面拼 https://gh-proxy.com/）
curl -L -o ~/.hermes/venvs/models/u2net.onnx \
  https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx
curl -L -o ~/.hermes/venvs/models/isnet-general-use.onnx \
  https://github.com/danielgatis/rembg/releases/download/v0.0.0/isnet-general-use.onnx
```

| 模型 | 体积 | 输入尺寸 | 单张（720×720） | 峰值内存 | 许可 |
|---|---|---|---|---|---|
| `u2net`（默认） | 168 MB | 320×320 | 3～5 s | ~550 MB | Apache-2.0（U-2-Net） |
| `isnet-general-use` | 170 MB | 1024×1024 | 11 s | ~890 MB | Apache-2.0（DIS） |

- 均 CPU 推理，无 GPU 要求；onnxruntime 有 Windows/macOS 轮子（客户机 Hermes venv py3.11 直接装）。
- **产品像素零改动**：只产出 alpha 掩膜，RGB 原样保留；`--verify` 会实测 `max_abs_diff`（应为 0）。
- 不装 rembg 的原因：rembg 会带上 pymatting/scikit-image/opencv 等一堆包（数百 MB），我们只需要推理部分。
- `imgctl.py white --engine local` / `set --composite` 内部就是调它。

## 本地 OCR（翻译读字用，免费离线）

```bash
V=~/.hermes/venvs/imgtools/bin/python
# mac 卡住就是 opencv 新版无 wheel（要 macOS 13）→ 铉4.9.0.80；4.9 是 numpy1 编的，必须 numpy<2
uv pip install --python $V -i https://mirrors.aliyun.com/pypi/simple/ \
  "opencv-python-headless==4.9.0.80" "numpy==1.26.4" pyclipper shapely PyYAML six tqdm
uv pip install --python $V --no-deps rapidocr-onnxruntime   # 带 PP-OCR 模型，~15MB
```

- Windows / Apple Silicon 直接 `uv pip install rapidocr-onnxruntime` 即可（无需铉版本）。
- 依赖体积参考：装完 venv ~386MB（含 opencv）。
- 叫法：`sys.path` 里的模块名是 `rapidocr_onnxruntime`；用法 `RapidOCR()(img_path)` → `[[box4点, text, score], ...]`。
- 配套：`translate_local.py` 用它读字 + `matte.py` 拿掩膜 + Pillow 重排 + 再 OCR 自证。

## 百炼·千问图像翻译（主路线；一把 `DASHSCOPE_API_KEY`）

**关键：这个用的是百炼 API Key（`sk-…`），不是阿里云 AccessKey。** 入口：百炼控制台 → API-KEY → 创建 API Key（`https://help.aliyun.com/zh/model-studio/get-api-key`；各地域独立，华北2北京用 `dashscope.aliyuncs.com`）。

**端点（同步，不设异步头）**：
```
POST https://dashscope.aliyuncs.com/api/v1/services/aigc/image2image/image-synthesis
Authorization: Bearer $DASHSCOPE_API_KEY
Content-Type: application/json
X-DashScope-OssResourceResolve: enable      # 用 oss:// 临时 URL 时必须带

{"model":"qwen-mt-image-2.0",
 "input":{"image_url":"<公网URL 或 oss://…>","source_lang":"auto|ro|zh|…","target_lang":"en"},
 "config":{"imageSegment":true},
 "ext":{"terminologies":[{"src":"CF-10","tgt":"CF-10"}],"domainHint":"…English only, ≤200 words…"}}
```
响应：`output.image_url`（与原图同尺寸 JPG，**24h 有效，要及时下载**）+ `usage.image_count`（固定 1）+ `request_id`；失败时返回 `code`/`message`（如 `InvalidApiKey`）。

- `config.imageSegment`：**`true` = 不翻译主体（人物/商品/Logo）上的文字**（默认 `false` 全翻）。旧参数名 `skipImgSegment` 仍兼容。← 我们的硬口径开关
- `ext.sensitives`：完全匹配的敏感词在翻译前过滤（区分大小写，≤50 个）
- 限制：JPG/PNG/WEBP/… 15~8192px、≤100MB、宽高比 1:10~10:1；**URL 不能含中文**（引擎已自动把文件名压成 ASCII）
- `qwen-mt-image-2.0` 可同步调用；老模型 `qwen-mt-image` 必须带 `X-DashScope-Async: enable` 走轮询
- 价格：2.0 **0.004 元/张**、1.0 0.003 元/张，送 100 张（90 天）

**本地图 → 公网 URL（官方三步，引擎已实现 `dashscope_upload`）**
1. `GET /api/v1/uploads?action=getPolicy&model=qwen-mt-image-2.0` → `data{policy, signature, upload_dir, oss_access_key_id, x_oss_object_acl, x_oss_forbid_overwrite, upload_host}`
2. multipart POST 到 `upload_host`（字段 `key=upload_dir/文件名`、`OSSAccessKeyId`、`Signature`、`policy`、`x-oss-object-acl`、`x-oss-forbid-overwrite`、`success_action_status=200`、`file`）
3. 得到 `oss://<key>`（48h 有效），调用时带 `X-DashScope-OssResourceResolve: enable`

排障：换地域（北京 vs 新加坡）必须换对应地域的 key 与域名；`BadRequest.IllegalEndpoint`= 你用了 `{WorkspaceId}.cn-beijing.maas.aliyuncs.com` 形式但 ID 不对，默认业务空间直接用 `dashscope.aliyuncs.com`。

## 阿里云 alimt（备选保真档——注意：不是百炼 Key，是 AccessKey）

凭证：`ALIYUN_ACCESS_KEY_ID` / `ALIYUN_ACCESS_KEY_SECRET`（与百炼 `DASHSCOPE_API_KEY` 是**两把不同凭证**，同账号）。
签名：ACS3-HMAC-SHA256，引擎已内置无 SDK 实现（`aliyun_rpc()`）。报 `SignatureDoesNotMatch` 先查时间同步与 AK 归属。

### 图片翻译接口族（同一把 AccessKey）

| Action | 关键参数 | 返回 | 备注 |
|---|---|---|---|
| `TranslateImage` ★默认 | `ImageBase64`（支持本地图）/`ImageUrl`、`SourceLanguage`、`TargetLanguage`、`Field=general\|e-commerce`、`Ext={needEditorData,ignoreEntityRecognize}` | `Data.FinalImageUrl`、`Data.InPaintingUrl`、`Data.TemplateJson` | 电商域会自动跳过印在商品主体上的字 |
| `CreateImageTranslateTask` + `GetTranslateImageBatchResult` | `UrlList`（逗号分隔，**≤20 张**）、语言对、`Extra={have_ocr,without_text,have_psd,ignore_entity}`、`ClientToken`（3 分钟幂等） | `TaskId` → `Status`/`Result` | **只吃公网 URL**；批量整套图用这条 |
| `GetImageDiagnose` | `Url` | `Language` | 先判源语种再翻 |
| `GetImageTranslate`（老） | `Url` | `Url`（译图）、`Orc`（文字块）、`PictureEditor`（psd 数据） | 要自建文字层（自己叠字）时拿文字位置 |

不满意自动排版时的正确做法：拿 `InPaintingUrl`（已擦字的背景图）+ 本地 `compose.py overlay` 叠字，不要重跑模型。

### `alimt.TranslateImage`（图片翻译·保真档）
- host `mt.cn-hangzhou.aliyuncs.com`，version `2018-10-12`，form 参数：
  - `ImageBase64`（支持本地图，优先）/ `ImageUrl`
  - `SourceLanguage`（如 `zh`；`auto` 不被支持时按源语言显式传）、`TargetLanguage`（`en`/`ro`/`ru`…）
  - `Field`：`e-commerce`（电商领域，会自动跳过商品主体上的文字）/ `general`
  - `Ext`：JSON String。`needEditorData`（`"true"` 才返回译后编辑器数据）；`ignoreEntityRecognize` —— 官方语义：`"false"`/不传 = **执行**主体识别 → 印在商品主体上的文字被跳过不翻；`"true"` = 不做该判断 → 全部文字都翻。**默认必须保持 false**（包装/产品本体上的字不能动）；CLI 上对应 `--translate-packaging-text`（显式要求连包装一起翻时才用）。
- 返回：`Data.FinalImageUrl`（最终译图）、`Data.InPaintingUrl`（擦字后背景图）、`Data.TemplateJson`（编辑器模版）
- 定位：擦字 + 原版式重排；**不重塑艺术字**。要艺术字重绘走 Agnes `--mode hifi`（并过自检）。

### `imageseg.SegmentCommodity`（白底图·保真）
- host `imageseg.cn-shanghai.aliyuncs.com`，version `2019-12-30`，参数：`ImageURL`（**只接受公网 URL**）、`ReturnForm`
  - `whiteBK` → 白底图（推荐）、`crop` → 裁掉边缘空白的四通道 PNG、`mask` → 单通道蒙版、不传 → 原尺寸四通道 PNG
- 限制：图像 ≤3MB、分辨率 <2000×2000；推荐上海地域 OSS 链接
- 返回：`Data.ImageURL`（**临时地址，30 分钟过期**，要留档必须立刻下载）
- 本地图怎么办：**优先 `--engine local`（本地抠图，免费离线）**；或上传公网拿 URL 走 `aliyun`；最后才用 `--engine model` 让模型重绘白底（会重绘产品，包装图不适用）

## 本地排版（Pillow）

- venv：`~/.hermes/venvs/imgtools`（`uv venv` + `uv pip install pillow`）
- 字体解析顺序：`assets/fonts/*.ttf` → 系统字体（macOS `Arial Unicode.ttf` 覆盖拉丁/西里尔/CJK；Windows `arialbd.ttf`）→ Pillow 内置
- 给客户机交付时，若目标语言含西里尔/泰文等，往 `assets/fonts/` 放一个 Noto Sans / Arial Unicode 再发
- 文字带底板的明暗自适应：按文字带区域平均亮度自动选深字/浅字 + 半透明底板，避免叠在深色背景上看不清

## 常见错误速查

| 现象 | 原因 | 处理 |
|---|---|---|
| `AGNES_NEW_KEY 未配置` | `~/.hermes/.env` 缺 key | 补 key；`doctor` 复核 |
| `apikey is empty`（grsai） | 走了 grsai 通道但没配 key | 本 skill 默认不走 grsai；要质量档再配 `GRSAI_API_KEY` |
| `阿里云凭证未配置` | 未开通/未配 AK | 开通「机器翻译」+「视觉智能开放平台-分割抠图」，配 AK |
| `imageseg` 报参数错误 | 传了本地路径而非 URL | 用 `--image-url` 或换 engine |
| `clash` fake-ip 导致抓不到网页 | 本机 TUN 劫持 | 抓 CN 站点用 `terminal curl`，必要时临时 `PATCH mode=rule`，完事还原 `global` |
