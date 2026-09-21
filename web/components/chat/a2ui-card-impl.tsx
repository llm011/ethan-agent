"use client";

// A2UI 卡片渲染（Web 端）：真正的实现在 @ethan/shared，两端共用同一份。
// 这里保留一层同路径的薄包装，是因为 a2ui-card.tsx 用 next/dynamic 按相对路径
// 懒加载本文件 —— 直接 import 共享模块会把 @a2ui 这坨依赖拉进首屏 bundle。
export { default } from "@ethan/shared/chat/a2ui-card-impl";
