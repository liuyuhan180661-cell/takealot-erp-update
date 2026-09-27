# 字体目录（可选，可空）

默认**不随 skill 打包任何字体二进制**——先按这个顺序找：

1. 本目录（`assets/fonts/*.ttf`）
2. 系统字体（macOS `Arial Unicode.ttf`；Windows `arialbd.ttf` / `msyh.ttc`）——覆盖拉丁、西里尔、CJK
3. Pillow 内置

什么时候要往这里放字体：目标市场语言系统字体盖不住（泰文、阿拉伯文、特殊设计字体），或客户要求固定品牌字体。
放进去的字体授权由交付方自负（商用需确认许可）。
