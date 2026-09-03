import 'package:flutter/material.dart';
import '../widgets/common.dart';

class MoreScreen extends StatelessWidget {
  const MoreScreen(
      {required this.onOpen, required this.onOpenSettings, super.key});
  final void Function(String route) onOpen;
  final VoidCallback onOpenSettings;
  @override
  Widget build(BuildContext context) => EthanPage(
        title: '我的',
        subtitle: '账户、偏好与工作工具',
        child: ListView(
          children: [
            SettingsGroup(title: '账户', children: [
              SettingsRow(
                icon: Icons.settings_outlined,
                title: '设置',
                subtitle: '连接、外观与 Ethan 的工作方式',
                onTap: onOpenSettings,
              ),
            ]),
            const SectionLabel('智能助手'),
            _tool(
                '记忆', '管理 Ethan 记住的事实与流程', Icons.psychology_rounded, 'memory'),
            _tool('知识库', '浏览和编辑 Markdown 知识', Icons.menu_book_rounded,
                'knowledge'),
            _tool('技能', '管理可调用的 Agent 技能', Icons.extension_rounded, 'skills'),
            const SectionLabel('自动化'),
            _tool('日程', '查看今天和未来的安排', Icons.event_rounded, 'agenda'),
            _tool('定时任务', 'Cron、间隔与心跳任务', Icons.schedule_rounded, 'schedule'),
            _tool('后台任务', '查看正在运行和已完成的任务', Icons.downloading_rounded,
                'background'),
            const SectionLabel('资料'),
            _tool('文档', '阅读 Ethan 使用文档', Icons.auto_stories_rounded, 'docs'),
          ],
        ),
      );

  Widget _tool(String title, String subtitle, IconData icon, String route) =>
      InfoTile(
        icon: icon,
        title: title,
        subtitle: subtitle,
        onTap: () => onOpen(route),
      );
}
