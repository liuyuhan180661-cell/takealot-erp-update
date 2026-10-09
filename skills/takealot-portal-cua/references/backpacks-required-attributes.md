# Bags & Cases → Backpacks 属性清单（从 DOM 抠出，勿凭截图目测）

来源：Chrome + `bsk get-html` 抓 `data-sectionname="Product Attributes"` 段，2026-09-25 在测试店实测。

## REQUIRED（必填，字段名后无 (Optional)）

**DOM 选择器（`data-fieldid`，直接用 CSS 定位，不要靠截图）**：

| 字段 | data-fieldid | 控件 |
|---|---|---|
| Fits Laptop Screen Size | `Attribute.fits_laptop_screen_size.value` | input（数字，英寸） |
| Water Resistant | `Attribute.is_water_resistant` | 下拉（Yes/No） |
| Waterproof | `Attribute.is_waterproof` | 下拉（Yes/No） |
| Laptop Compatibility | `Attribute.laptop_compatibility` | 可搜索下拉，**选项是笔记本品牌**（输入 Len → Lenovo） |
| Material | `Attribute.materials` | 多选可搜索，选 `Polyester`（落值为 chip） |
| Packaged Height (cm) | `Attribute.merchant_packaged_dimensions.height` | input，0.01–400 |
| Packaged Length (cm) | `Attribute.merchant_packaged_dimensions.length` | input，0.01–400 |
| Packaged Width (cm) | `Attribute.merchant_packaged_dimensions.width` | input，0.01–400 |
| Packaged Weight (g) | `Attribute.merchant_packaged_weight.value` | input，1–80000（**克**） |
| Warranty | `Attribute.warranty` | 两个下拉：类型（Lifetime/Limited/Full）+ 有效期（6/12/… Months） |

后续步骤的必填（同一套 `data-fieldid`）：`title`（富文本，Draft.js，`bsk fill ... .public-DraftEditor-content` 有效）、`description`（富文本，**≥200 字符**）、`Attribute.whats_in_the_box`（textarea）、**`ProductID.Value`（Registered Barcode，实测 required=true，不能空着交；可用带正确校验位的 EAN-13，如 6901234567892）**；`subtitle`/`SKU` 可选。图片分区：**至少 1 张图才让提交**（实测 3 张通过），主图要求白底 ≥600×600。

提交后到 `/catalogue/submissions` 核对：状态 `In Review` = 已成功提交（等待平台审核）。

| 字段 | 说明文字 | 单位/约束 |
|---|---|---|
| Fits Laptop Screen Size | Size of the laptop screen this product will fit in inches | 英寸 |
| Water Resistant | Is this product able to resist the penetration of water? | 下拉 |
| Waterproof | Pick from the down down | 下拉 |
| Laptop Compatibility | Pick from the down down | 下拉，**选项是笔记本品牌**（联想/惠普/戴尔/苹果/宏碁…），不是是/否 |
| Material | Main material/fabric that the product is made of | 可搜索下拉，如 聚酯纤维 |
| Packaged Height (cm) | 零售包装高度 | 0.01–400cm |
| Packaged Length (cm) | 零售包装长度 | 0.01–400cm |
| **Packaged Width (cm)** | 零售包装宽度 | 0.01–400cm |
| **Packaged Weight (g)** | 零售包装重量，**单位是克** | 1–80000g |
| **Warranty** | Please select a warranty type and/or valid period | 类型+有效期 |

> 上一轮 Firefox 里只填到 Packaged Length 就以为填完了，**漏掉最后三项**（Width / Weight / Warranty）→ 点 Next 报「某些所需属性不完整」，整块面板描红。加粗三项是那次失败的真正原因。

## RECOMMENDED（全部 (Optional)）
Colour(组) / Main Colour / Secondary / Colour Name · Country of Origin · Is Padded · Is Tamper Evident Sealed · Assembled Product Height/Length/Width (cm) · Proudly South African · **Requires Original Packaging Return** · **Bag Size**(升) · **Packed Quantity For Variant**

## 非必填但容易误判的
- **Brand**：明确标 `(Optional)`，空着不影响 Next（上一轮把它当嫌疑犯是错的）。
- **Main Colour**：在 RECOMMENDED 组里、字段名后无 `(Optional)`，但**不属于 REQUIRED**，不要为它纠结。

## 校验信号（廉价）
- 面板标题右侧属性计数（无 → `1 个属性` / `N Attributes`）
- 字段落值（如 `32` 被格式化成 `32.0`）；chip 标签代表多选已提交
- Next 按钮由灰变蓝（`bsk observe` 里 `[disabled]` 消失）
