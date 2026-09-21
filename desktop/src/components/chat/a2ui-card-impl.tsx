// A2UI 卡片渲染（桌面端）：真正的实现在 @ethan/shared，两端共用同一份。
// 这里保留一层同路径的薄包装，是因为 a2ui-card.tsx 用 React.lazy 按相对路径
// 懒加载本文件，好把 @a2ui 依赖切到单独的 chunk。
export { default } from "@ethan/shared/chat/a2ui-card-impl";
