/* 桌面端的 useCachedResource：实现已统一到 @ethan/shared，两端共用同一份。
 * 这里保留同路径 shim，是因为已有 import 走 "@/lib/use-cached-resource"。
 *
 * 注意：本文件曾被 fork 成一份浅比较只有一层（aa[i] !== bb[i]）的版本，
 * 后端每次 JSON 解析出来的元素都是新对象引用，浅比较必然判不等，
 * 导致每次后台 refetch 都触发一轮多余 re-render。改用共享版后消失。 */
export { useCachedResource } from "@ethan/shared/lib/use-cached-resource";
