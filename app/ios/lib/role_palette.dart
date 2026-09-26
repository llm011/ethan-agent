import 'package:flutter/material.dart';

/// 聊天气泡的说话方分类 —— 与 Android 端 `MessageRoleKind` 同一套语义。
///
/// 分类而不是「user / 非 user」两档：工具结果、系统提示与助手正式回复在语义上不同，
/// 共用一种颜色会让长会话变成一坨同色气泡，用户分不清哪段是 AI 说的话、
/// 哪段是工具的输出。
///
/// 未知 role 一律落到 [assistant]：服务端将来加新 role 或历史数据有脏值时，
/// 气泡至少有颜色，不会因为查不到而渲染异常。
enum MessageRoleKind {
  user,
  assistant,
  tool,
  system;

  static MessageRoleKind of(String? role) {
    switch (role?.trim().toLowerCase()) {
      case 'user':
        return MessageRoleKind.user;
      case 'tool':
      case 'function':
      case 'tool_result':
        return MessageRoleKind.tool;
      case 'system':
        return MessageRoleKind.system;
      default:
        return MessageRoleKind.assistant;
    }
  }
}

/// 角色配色 —— 全部从 `ColorScheme` 派生，不写死十六进制。
///
/// 这样切换亮/暗主题时颜色自动一起变（iOS 端跟随系统的 dark mode），
/// 也符合设计系统「不写死颜色」的要求。
///
/// 与 Android 端 `BubblePalette` 保持一致的思路：
///   - 用户 = primary（蓝系）
///   - 助手 = tertiary（青绿系，刻意避开 primary，否则两个深浅不同的蓝在色弱视角下几乎一样）
///   - 工具 = secondary（紫系，比对话内容更中性）
///   - 系统 = 纯中性（它不代表任何「说话的人」）
///
/// 底色用低透明度压在 surface 上、正文仍用 onSurface：无论主题深浅，
/// 文字对比度都有保证（不是「浅底浅字」）。
extension MessageRolePalette on BuildContext {
  Color bubbleColor(MessageRoleKind kind) {
    final scheme = Theme.of(this).colorScheme;
    switch (kind) {
      case MessageRoleKind.user:
        return scheme.primaryContainer;
      case MessageRoleKind.assistant:
        return scheme.tertiaryContainer.withOpacity(.45);
      case MessageRoleKind.tool:
        return scheme.secondaryContainer.withOpacity(.45);
      case MessageRoleKind.system:
        return scheme.surfaceContainerHighest;
    }
  }

  /// 气泡左侧的强调色条 —— 角色识别的主要标记。实色（不透明），
  /// 因为 3dp 的细线如果也是低透明度就彻底看不见了。
  Color bubbleAccent(MessageRoleKind kind) {
    final scheme = Theme.of(this).colorScheme;
    switch (kind) {
      case MessageRoleKind.user:
        return scheme.primary;
      case MessageRoleKind.assistant:
        return scheme.tertiary;
      case MessageRoleKind.tool:
        return scheme.secondary;
      case MessageRoleKind.system:
        return Colors.transparent;
    }
  }

  /// 角色名（气泡顶部那行小字）。
  ///
  /// 这是**无障碍的主要兜底**：颜色可能被色盲用户忽略，
  /// 但「我」「Ethan」「工具」这几个词一定读得出来。
  String bubbleRoleLabel(MessageRoleKind kind) {
    switch (kind) {
      case MessageRoleKind.user:
        return '我';
      case MessageRoleKind.assistant:
        return 'Ethan';
      case MessageRoleKind.tool:
        return '工具';
      case MessageRoleKind.system:
        return '系统';
    }
  }

  /// 角色头像位的图标。iOS 端原本就有这个 16dp 小图标（不是完整的头像），
  /// 保留它并让它跟随角色配色 —— 图标 + 色条 + 名字三者互相印证。
  IconData bubbleRoleIcon(MessageRoleKind kind) {
    switch (kind) {
      case MessageRoleKind.user:
        return Icons.person_outline_rounded;
      case MessageRoleKind.assistant:
        return Icons.auto_awesome_rounded;
      case MessageRoleKind.tool:
        return Icons.build_outlined;
      case MessageRoleKind.system:
        return Icons.info_outline_rounded;
    }
  }
}
