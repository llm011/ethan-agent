// 实现已统一到 @ethan/shared/components/code-block，两端共用同一份。
// 共享版把「自动换行」改成 useEffect 同步 DOM：既保留不重渲染 SyntaxHighlighter 的
// 性能优势，又保证组件重新挂载后 state 与 DOM 不会失步（两端旧副本是直接改 DOM）。
export * from "@ethan/shared/components/code-block";
