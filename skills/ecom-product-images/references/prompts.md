# 图位 prompt 库与改写规则

所有送模型的 prompt 都用**英文**（实测中文场景描述写进英文 prompt 有效，但指令本身保持英文命中更稳）。
完整图位定义在 `scripts/specs.json` 的 `shots` 段；这里是改写规则和踩过的坑。

## 三条固定句式

1. **锁定产品（每条都要有）**
   `Take the exact product shown in the reference image(s) and render it ... Keep the product's shape, color, logo, proportions and details strictly identical to the reference.`
2. **禁字（无文字图位：主图／展示图／细节图）**
   `Absolutely no text, no captions, no watermark, no extra logos.`
   带文案图位（场景／使用／详情 banner）也要先禁字、留白，文字本地叠：
   `Do NOT print any text, letters or numbers anywhere in the image; leave clean empty areas for typography later.`
3. **参数图留位**（不渲字，只留干净区域）
   `Leave clean empty space for specification callouts and thin divider lines. No gibberish text, no watermark, no extra logos.`

## 图位清单

| kind | key | 标签 | 承载文字 | 要点 |
|---|---|---|---|---|
| gallery | main | 白底主图 | 否 | 纯 `{BG}`（takealot/emag/ozon 均为 white），正面、约占 85% |
| gallery | show | 产品展示图 | 否 | 柔和渐变棚拍、微侧角度、软阴影 |
| gallery | scene | 场景图 | 是 | 与品类相符的真实生活场景，产品是主角 |
| gallery | inuse | 使用场景 | 是 | 真实使用情境 |
| gallery | detail | 细节特写 | 否 | 微距材质/工艺，浅景深 |
| detail | d-hero | 主卖点 | 是 | 16:9 电影感 hero banner，留标题空间 |
| detail | d-sell1/2 | 卖点场景 | 是 | 宽幅生活场景 + 留白 |
| detail | d-life | 生活方式 | 是 | 真实居家环境、暖光 |
| detail | d-spec | 参数信息图 | 规格清单 | 浅色极简背景 + 干净留位 |

## 场景描述（`--scene`）

用户用中文说场景没问题，引擎直接拼进英文 prompt：`Seller's desired scene direction (follow faithfully): <原话>.`
实测「自然生活场景」「面包店柜台」这类描述模型能照做。

## 反例（不要这样做）

- ❌ 让模型渲染营销文字 → 实测出错字：`2 UB + 3 PD`（应为 2 USB + 3 PD）、`Dispoomhes`（应为 Dispozitive Compatibile）。文字一律本地叠。
- ❌ 用 `size: "2:3"` 这种比例字符串 → 上游 500 报错；必须传 `WxH`（引擎已从 `ratios_px` 映射）。
- ❌ 主图用重绘档翻译/换背景后不改标签 → 重绘会改动 logo/丝印，主图必须走保真路线（抠图或保真翻译），或明确标记为「效果图」。
- ❌ 一次塞 4 张以上参考图 → 引擎截断到 2~4 张（实测 2 张可用）；参考图超过 4MB 会让请求变大且变慢，先压到 ~2000px。

## 文案 prompt（DeepSeek vision）

引擎内置（`COPY_PROMPT`）：输出 `{"copies":[{"headline":"2~4词","subtitle":"<=8词"}],"specs":["规格1",...]}`，语言由平台 `copy_lang` 决定（Takealot=English／eMAG=Romanian／Ozon=Russian）。有卖家补充信息时通过 `--info` 传入，会进 prompt。
