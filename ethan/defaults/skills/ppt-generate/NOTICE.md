# PPT-Generate Skill - Third-Party Attribution Notice

## 1. PPTist (MIT)

- Source: https://github.com/pipipi-pikachu/PPTist
- License: MIT (Copyright (c) 2020-present pipipi-pikachu)
- Used: 中间格式的 schema 骨架设计——Slide/element 结构、统一定位系统、
  slideType / textType / imageType 语义、SlideTheme 主题结构、chart/table 数据模型。
  本技能在其基础上做了适配改造（文本 HTML → 结构化 runs、SVG path → 预设几何、
  latex → OMML 原生公式），未复制其代码。

## 2. latex2mathml (MIT)

- Source: https://github.com/roniemartinez/latex2mathml (PyPI: latex2mathml)
- License: MIT
- Used: LaTeX → MathML 转换（公式元素渲染链路第一段）。
  运行时依赖，由 render_pptx.py 首次使用时自动 pip 安装，不随仓库分发。

## 3. mathml2omml (MIT)

- Source: https://github.com/amedama41/mathml2omml (PyPI: mathml2omml)
- License: MIT (Copyright (c) 2019 amedama)
- Used: MathML → OMML 转换（公式元素渲染链路第二段）。
  运行时依赖，自动 pip 安装，不随仓库分发。

## 4. Iconify (API, free)

- Source: https://api.iconify.design / https://iconify.design
- Used: 图标 SVG 数据源（icon:collection:name 占位符）。
  图标本身的许可见各图标集（mdi=Apache-2.0，fa=CC-BY-4.0 等），按图标集声明。

## 5. Pexels / Unsplash API (optional)

- 仅在用户配置 PEXELS_API_KEY / UNSPLASH_ACCESS_KEY 时启用，照片许可见各自服务条款。
