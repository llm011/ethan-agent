/* 气泡身份的类型声明 —— 与后端 GET /api/user/identity 的响应对应。
 *
 * 放在 shared 而不是各自 lib/api-settings.ts：两端的气泡组件都要用这个类型，
 * 而 shared 不能反向依赖 web/desktop 的 lib。两端的 api-settings.ts 从这个类型
 * re-export（保持既有 import 路径可用）。
 */

export interface UserIdentity {
  user_id: string;
  /** 显示名；未设置时为空串，气泡按「不显示名字」处理 */
  display_name: string;
  /** 相对 URL（`images/img_avatar.<ext>`）；未设置时为空串，气泡走兜底头像 */
  avatar_url: string;
}
