import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../data/api_client.dart';
import '../models/app_models.dart';
import '../services/api_service.dart';
import '../widgets/common.dart';

class SessionsScreen extends StatefulWidget {
  const SessionsScreen({required this.api, required this.onOpen, super.key});
  final EthanApiClient api;
  final ValueChanged<String> onOpen;
  @override
  State<SessionsScreen> createState() => _SessionsScreenState();
}

/// The left navigation destination is an overview, not a second chat tab.
/// It uses the same live sessions endpoint as [SessionsScreen], but keeps the
/// first screen focused on resuming work and deliberate next actions.
class WorkspaceScreen extends StatelessWidget {
  const WorkspaceScreen({
    required this.api,
    required this.workspaceApi,
    required this.onOpenSession,
    required this.onOpenAll,
    required this.onOpenTasks,
    required this.onNewChat,
    required this.onOpenMine,
    super.key,
  });

  final EthanApiClient api;
  final EthanApiService workspaceApi;
  final ValueChanged<String> onOpenSession;
  final VoidCallback onOpenAll;
  final VoidCallback onOpenTasks;
  final VoidCallback onNewChat;
  final VoidCallback onOpenMine;

  @override
  Widget build(BuildContext context) => EthanPage(
        title: '工作台',
        subtitle: '最近工作与快捷入口',
        child: FutureBuilder<List<Session>>(
          future: api.sessions(),
          builder: (context, snapshot) {
            final sessions = snapshot.data ?? const <Session>[];
            return FutureBuilder<List<BackgroundTaskItem>>(
                future: workspaceApi.fetchBackgroundTasks(),
                builder: (context, taskSnapshot) => ListView(
                      padding: const EdgeInsets.only(top: 8, bottom: 24),
                      children: [
                        _taskSection(context, taskSnapshot),
                        if (snapshot.connectionState != ConnectionState.done)
                          SettingsGroup(title: '最近会话', children: const [
                            Padding(
                              padding: EdgeInsets.all(24),
                              child: Center(child: CircularProgressIndicator()),
                            ),
                          ])
                        else if (snapshot.hasError)
                          SettingsGroup(title: '最近会话', children: [
                            SettingsRow(
                              icon: Icons.cloud_off_outlined,
                              title: '暂时无法加载',
                              subtitle: '检查连接后开始新的对话',
                              onTap: onNewChat,
                              danger: true,
                            ),
                          ])
                        else if (sessions.isEmpty)
                          SettingsGroup(title: '最近会话', children: [
                            SettingsRow(
                              icon: Icons.inbox_outlined,
                              title: '还没有最近会话',
                              subtitle: '从一句话开始，Ethan 会在这里保留工作上下文',
                              onTap: onNewChat,
                            ),
                          ])
                        else
                          SettingsGroup(
                            title: '最近会话',
                            children: sessions.take(5).map((session) {
                              final summary = session.summary.trim();
                              return SettingsRow(
                                icon: session.pinnedAt > 0
                                    ? Icons.push_pin_outlined
                                    : Icons.chat_bubble_outline_rounded,
                                title: session.title,
                                subtitle: summary.isEmpty
                                    ? session.time
                                    : '$summary\n${session.time}',
                                onTap: () => onOpenSession(session.id),
                              );
                            }).toList(),
                          ),
                        SettingsGroup(title: '快捷操作', children: [
                          SettingsRow(
                            icon: Icons.add_comment_outlined,
                            title: '新建对话',
                            subtitle: '在中央对话页开始一项新工作',
                            onTap: onNewChat,
                          ),
                          SettingsRow(
                            icon: Icons.list_alt_outlined,
                            title: '全部会话',
                            subtitle: '搜索、筛选和管理历史会话',
                            onTap: onOpenAll,
                          ),
                          SettingsRow(
                            icon: Icons.person_outline_rounded,
                            title: '我的与设置',
                            subtitle: '连接、工具、外观和个人偏好',
                            onTap: onOpenMine,
                          ),
                        ]),
                      ],
                    ));
          },
        ),
      );

  Widget _taskSection(
      BuildContext context, AsyncSnapshot<List<BackgroundTaskItem>> snapshot) {
    final tasks = snapshot.data ?? const <BackgroundTaskItem>[];
    return SettingsGroup(
      title: '任务状态',
      children: [
        if (snapshot.connectionState != ConnectionState.done)
          const Padding(
            padding: EdgeInsets.all(18),
            child: LinearProgressIndicator(minHeight: 2),
          )
        else if (snapshot.hasError)
          SettingsRow(
            icon: Icons.cloud_off_outlined,
            title: '任务状态暂不可用',
            subtitle: '打开后台任务查看并重试',
            onTap: onOpenTasks,
            danger: true,
          )
        else if (tasks.isEmpty)
          const SettingsRow(
            icon: Icons.check_circle_outline_rounded,
            title: '当前没有后台任务',
            subtitle: '新的异步任务会显示在这里',
          )
        else
          ...tasks.take(4).map((task) => SettingsRow(
                icon: _taskIcon(task.status),
                title: task.title,
                subtitle: _taskSubtitle(task),
                onTap: onOpenTasks,
                trailing: _taskStatusChip(context, task.status),
              )),
        if (tasks.isNotEmpty)
          SettingsRow(
            icon: Icons.list_alt_outlined,
            title: '管理后台任务',
            subtitle: '查看结果、刷新状态或停止运行中的任务',
            onTap: onOpenTasks,
          ),
      ],
    );
  }

  String _taskSubtitle(BackgroundTaskItem task) {
    if (task.error.isNotEmpty) return task.error;
    if (task.result.isNotEmpty) return task.result;
    if (task.status == 'running') return '正在处理，可在后台任务中停止';
    if (task.status == 'done') return '已完成，可打开后台任务查看结果';
    return '任务编号：${task.id}';
  }

  Widget _taskStatusChip(BuildContext context, String status) {
    final scheme = Theme.of(context).colorScheme;
    final (label, color) = switch (status) {
      'running' => ('运行中', scheme.primary),
      'done' => ('已完成', scheme.secondary),
      'failed' => ('失败', scheme.error),
      'cancelled' => ('已取消', scheme.outline),
      _ => (status.isEmpty ? '未知' : status, scheme.outline),
    };
    return Text(label,
        style: Theme.of(context)
            .textTheme
            .labelMedium
            ?.copyWith(color: color, fontWeight: FontWeight.w600));
  }

  IconData _taskIcon(String status) => switch (status) {
        'running' => Icons.sync_rounded,
        'done' => Icons.check_circle_outline_rounded,
        'failed' => Icons.error_outline_rounded,
        'cancelled' => Icons.stop_circle_outlined,
        _ => Icons.pending_outlined,
      };
}

class _SessionsScreenState extends State<SessionsScreen> {
  /// 一页的条数，与服务端 `/sessions` 默认上限一致。
  static const _pageSize = 50;

  /// 触发「加载更多」的距离 buffer：距离列表底部不足这个值才触发。
  /// 没有它，滚动中途一次轻微的惯性滑动就会误触发下一页（防误触）。
  static const _loadMoreBuffer = 400.0;

  final query = TextEditingController();
  final scroll = ScrollController();
  List<Session> sessions = [];
  List<Session> pinned = [];
  final Set<String> selectedSources = {};
  int _total = 0;
  bool loading = true;
  bool _refreshing = false;
  bool _loadingMore = false;
  String? _moreError;

  /// 「加载更多」的代币：显式刷新自增作废在飞的追加结果（防旧页覆盖新列表）。
  int _loadMoreToken = 0;

  /// 最近一页的分页元数据（total/totalKnown/pageFilled），驱动 [hasMore]。
  SessionPage? _lastPage;
  String? error;

  /// 已取条数追上服务端 total 才算到底；total 未知时退回「末页是否取满」
  /// （未取满一页说明服务端已经没有更多了）。
  bool get hasMore {
    final page = _lastPage;
    if (page == null) return sessions.length < _total;
    if (page.totalKnown) return sessions.length < page.total;
    return page.pageFilled;
  }

  @override
  void initState() {
    super.initState();
    load();
  }

  @override
  void dispose() {
    query.dispose();
    scroll.dispose();
    super.dispose();
  }

  /// 下拉 / 刷新按钮 / 首次进入共用的整列表刷新。
  ///
  /// 返回真实完成的 Future：RefreshIndicator 拿它决定指示器何时收起 ——
  /// 之前指示器「一闪就没」就是因为把一个立刻完成的空 Future 交给了它。
  /// 同一时刻只允许一个刷新在飞（防抖 + 单飞）。
  ///
  /// [resetPage] 标记这是一次会改变列表内容的显式动作（搜索/下拉/手动刷新）：
  /// 它优先于正在进行的「加载更多」—— 加载更多在飞时被挤掉的只是追加结果，
  /// 用户显式输入的新搜索不能被静默吞掉。
  Future<void> load({bool resetPage = false}) async {
    if (!mounted || _refreshing) return;
    if (_loadingMore && !resetPage) return;
    _loadMoreToken++; // 使在飞的「加载更多」落地时不再写回旧分页。
    setState(() {
      _refreshing = true;
      _loadingMore = false;
      error = null;
      _moreError = null;
      // 只有首屏（还没有任何数据）才整页转圈；已有列表时刷新交给
      // RefreshIndicator 表达，避免把用户正在看的列表整个拆掉。
      if (sessions.isEmpty) loading = true;
    });
    try {
      final result = await Future.wait([
        widget.api.sessionsPage(query: query.text, limit: _pageSize),
        widget.api.pinnedSessions(),
      ]);
      if (!mounted) return;
      setState(() {
        sessions = (result[0] as SessionPage).sessions;
        _lastPage = result[0] as SessionPage;
        _total = _lastPage!.total;
        pinned = result[1] as List<Session>;
        _moreError = null;
      });
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) {
        setState(() {
          loading = false;
          _refreshing = false;
        });
      }
    }
  }

  /// 加载下一页并追加。失败只把错误写在 footer 上，绝不动已有列表。
  ///
  /// [_loadMoreToken] 单调递增：显式刷新（[load]）会先自增令牌作废在飞的
  /// 追加，避免它带着旧分页/旧关键词的结果覆盖新列表。
  Future<void> _loadMore() async {
    if (!mounted || loading || _refreshing || _loadingMore || !hasMore) return;
    final token = _loadMoreToken;
    setState(() {
      _loadingMore = true;
      _moreError = null;
    });
    try {
      final page = await widget.api.sessionsPage(
          query: query.text, limit: _pageSize, offset: sessions.length);
      if (!mounted || token != _loadMoreToken) return;
      setState(() {
        // 追加前按 id 去重：刷新窗口里服务端水位变了，offset 可能与旧页重叠。
        final known = {for (final session in sessions) session.id};
        sessions = [
          ...sessions,
          ...page.sessions.where((session) => !known.contains(session.id)),
        ];
        _lastPage = page;
        _total = page.total;
      });
    } catch (e) {
      if (mounted && token == _loadMoreToken) {
        setState(() => _moreError = e.toString());
      }
    } finally {
      if (mounted && token == _loadMoreToken) {
        setState(() => _loadingMore = false);
      }
    }
  }

  /// 滚动触底（不足 [_loadMoreBuffer]）时加载下一页。
  /// [_loadingMore] 单飞 + [hasMore] 兜底，footer 正在加载或已到底时忽略。
  bool _onScroll(ScrollNotification notification) {
    if (notification is! ScrollUpdateNotification &&
        notification is! ScrollEndNotification) {
      return false;
    }
    final metrics = notification.metrics;
    if (metrics.maxScrollExtent - metrics.pixels > _loadMoreBuffer) {
      return false;
    }
    _loadMore();
    return false;
  }

  Future<void> _delete(Session session) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialog) => AlertDialog(
        icon: const Icon(Icons.delete_outline_rounded),
        title: const Text('删除此会话？'),
        content: Text('“${session.title}”及其消息将从 Ethan 服务端删除，且无法恢复。'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(dialog, false),
              child: const Text('取消')),
          FilledButton(
              style: FilledButton.styleFrom(
                  backgroundColor: Theme.of(context).colorScheme.error,
                  foregroundColor: Theme.of(context).colorScheme.onError),
              onPressed: () => Navigator.pop(dialog, true),
              child: const Text('删除')),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      await widget.api.deleteSession(session.id);
      await load();
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    }
  }

  Future<void> _togglePin(Session session) async {
    try {
      if (session.pinnedAt > 0) {
        await widget.api.unpinSession(session.id);
      } else {
        await widget.api.pinSession(session.id);
      }
      await load();
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    }
  }

  Future<void> _regenerateTitle(Session session) async {
    try {
      await widget.api.regenerateTitle(session.id);
      await load();
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    }
  }

  Future<void> _showSummary(Session session) async {
    try {
      final result = await widget.api.summarizeSession(session.id);
      if (!mounted) return;
      await showModalBottomSheet<void>(
          context: context,
          showDragHandle: true,
          isScrollControlled: true,
          builder: (_) => SafeArea(
              child: Padding(
                  padding: const EdgeInsets.all(20),
                  child: SingleChildScrollView(
                      child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      SelectableText(result['summary']?.toString() ?? '暂无摘要'),
                      const SizedBox(height: 16),
                      Align(
                        alignment: Alignment.centerRight,
                        child: OutlinedButton.icon(
                          onPressed: () async {
                            await Clipboard.setData(ClipboardData(
                                text: result['summary']?.toString() ?? ''));
                            if (context.mounted) {
                              ScaffoldMessenger.of(context).showSnackBar(
                                  const SnackBar(content: Text('摘要已复制')));
                            }
                          },
                          icon: const Icon(Icons.copy_rounded),
                          label: const Text('复制摘要'),
                        ),
                      ),
                    ],
                  )))));
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    }
  }

  List<Session> get _sourceFiltered => selectedSources.isEmpty
      ? sessions
      : sessions
          .where((item) => selectedSources.contains(item.source))
          .toList();

  List<Session> get _filteredPinned => selectedSources.isEmpty
      ? pinned
      : pinned.where((item) => selectedSources.contains(item.source)).toList();

  String _sourceLabel(String source) => switch (source) {
        'heartbeat' => '心跳',
        'scheduled' => '定时',
        _ => source,
      };

  Widget _sessionTile(Session session) => InfoTile(
        icon: session.pinnedAt > 0
            ? Icons.push_pin_rounded
            : Icons.chat_bubble_outline_rounded,
        title: session.title,
        subtitle:
            '${session.summary.isEmpty ? '暂无摘要' : session.summary}\n${_sourceLabel(session.source)} · ${session.time}',
        subtitleMaxLines: 2,
        onTap: () => widget.onOpen(session.id),
        trailing: PopupMenuButton<String>(
            onSelected: (action) async {
              switch (action) {
                case 'pin':
                  await _togglePin(session);
                case 'rename':
                  await _rename(session);
                case 'regen':
                  await _regenerateTitle(session);
                case 'summary':
                  await _showSummary(session);
                case 'delete':
                  await _delete(session);
              }
            },
            itemBuilder: (_) => [
                  PopupMenuItem(
                      value: 'pin',
                      child: Text(session.pinnedAt > 0 ? '取消置顶' : '置顶')),
                  const PopupMenuItem(value: 'rename', child: Text('重命名')),
                  const PopupMenuItem(value: 'regen', child: Text('重新生成标题')),
                  const PopupMenuItem(value: 'summary', child: Text('查看摘要')),
                  const PopupMenuItem(value: 'delete', child: Text('删除')),
                ]),
      );

  /// 列表尾部：加载中 / 加载失败重试 / 到底提示。数据未满一页时返回占位。
  Widget _listFooter(BuildContext context) {
    final textStyle = Theme.of(context)
        .textTheme
        .bodySmall
        ?.copyWith(color: Theme.of(context).colorScheme.onSurfaceVariant);
    if (_moreError != null) {
      return Padding(
          padding: const EdgeInsets.symmetric(vertical: 18),
          child: Column(children: [
            Text('加载更多失败：$_moreError',
                textAlign: TextAlign.center, style: textStyle),
            const SizedBox(height: 10),
            OutlinedButton.icon(
                onPressed: _loadMore,
                icon: const Icon(Icons.refresh_rounded),
                label: const Text('重试')),
          ]));
    }
    if (_loadingMore) {
      return Padding(
          padding: const EdgeInsets.symmetric(vertical: 18),
          child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
            const SizedBox(
                width: 16,
                height: 16,
                child: CircularProgressIndicator(strokeWidth: 2)),
            const SizedBox(width: 10),
            Text('加载中…', style: textStyle),
          ]));
    }
    if (!hasMore && sessions.isNotEmpty) {
      return Padding(
          padding: const EdgeInsets.symmetric(vertical: 18),
          child: Center(child: Text('没有更多了', style: textStyle)));
    }
    return const SizedBox.shrink();
  }

  @override
  Widget build(BuildContext context) => EthanPage(
        title: '全部对话',
        subtitle: '${_total > 0 ? _total : sessions.length} 个会话',
        actions: [
          IconButton(
              onPressed: loading ? null : () => load(resetPage: true),
              icon: const Icon(Icons.refresh_rounded))
        ],
        child: Column(children: [
          SizedBox(
              height: 44,
              child: ListView(
                  padding: const EdgeInsets.symmetric(horizontal: 12),
                  scrollDirection: Axis.horizontal,
                  children: [
                    FilterChip(
                        label: const Text('全部'),
                        selected: selectedSources.isEmpty,
                        onSelected: (_) => setState(selectedSources.clear)),
                    ...const [
                      'web',
                      'lark',
                      'repl',
                      'desktop',
                      'wechat',
                      'heartbeat',
                      'scheduled'
                    ].map((source) => Padding(
                        padding: const EdgeInsets.only(left: 6),
                        child: FilterChip(
                            label: Text(_sourceLabel(source)),
                            selected: selectedSources.contains(source),
                            onSelected: (selected) => setState(() {
                                  if (selected) {
                                    selectedSources.add(source);
                                  } else {
                                    selectedSources.remove(source);
                                  }
                                })))),
                  ])),
          Padding(
              padding: const EdgeInsets.fromLTRB(16, 4, 16, 12),
              child: TextField(
                  controller: query,
                  onSubmitted: (_) => load(resetPage: true),
                  decoration: const InputDecoration(
                      prefixIcon: Icon(Icons.search_rounded),
                      hintText: '搜索会话…'))),
          if (error != null)
            MaterialBanner(content: Text('加载会话失败：$error'), actions: [
              TextButton(
                  onPressed: () => load(resetPage: true),
                  child: const Text('重试')),
              TextButton(
                  onPressed: () => setState(() => error = null),
                  child: const Text('关闭')),
            ]),
          Expanded(
              child: loading
                  ? const Center(child: CircularProgressIndicator())
                  : RefreshIndicator(
                      onRefresh: load,
                      child: _sourceFiltered.isEmpty
                          ? ListView(
                              // 空态也包一层可滚动列表：空列表同样能下拉刷新。
                              physics: const AlwaysScrollableScrollPhysics(),
                              children: [
                                  SizedBox(
                                      height:
                                          MediaQuery.sizeOf(context).height *
                                              .6,
                                      child: EmptyHint(
                                        icon: Icons.chat_bubble_outline_rounded,
                                        text: selectedSources.isEmpty
                                            ? '暂无会话，去对话页开始第一段交流吧'
                                            : '没有符合当前来源筛选的会话',
                                        actionLabel: selectedSources.isEmpty
                                            ? null
                                            : '清除筛选',
                                        onAction: selectedSources.isEmpty
                                            ? null
                                            : () =>
                                                setState(selectedSources.clear),
                                      ))
                                ])
                          : NotificationListener<ScrollNotification>(
                              onNotification: _onScroll,
                              child: ListView(
                                  controller: scroll,
                                  physics:
                                      const AlwaysScrollableScrollPhysics(),
                                  children: [
                                    if (_filteredPinned.isNotEmpty) ...[
                                      const SectionLabel('置顶会话'),
                                      ..._filteredPinned.map(_sessionTile),
                                      const Divider(),
                                    ],
                                    if (_sourceFiltered.isNotEmpty)
                                      const SectionLabel('全部会话'),
                                    ..._sourceFiltered
                                        .where((session) =>
                                            !_filteredPinned.any((item) =>
                                                item.id == session.id) &&
                                            (selectedSources.isEmpty ||
                                                selectedSources
                                                    .contains(session.source)))
                                        .map(_sessionTile),
                                    _listFooter(context),
                                  ])))),
        ]),
      );

  Future<void> _rename(Session session) async {
    final controller = TextEditingController(text: session.title);
    final title = await showDialog<String>(
        context: context,
        builder: (_) => AlertDialog(
                title: const Text('重命名会话'),
                content: TextField(controller: controller, autofocus: true),
                actions: [
                  TextButton(
                      onPressed: () => Navigator.pop(context),
                      child: const Text('取消')),
                  FilledButton(
                      onPressed: () =>
                          Navigator.pop(context, controller.text.trim()),
                      child: const Text('保存'))
                ]));
    // Let the dialog route finish deactivation before disposing its text
    // controller. Immediate disposal can race FocusScope teardown on iOS.
    final renamedController = controller;
    Future<void>.delayed(const Duration(milliseconds: 350), () {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        renamedController.dispose();
      });
    });
    if (title != null && title.isNotEmpty) {
      try {
        await widget.api.renameSession(session.id, title);
        await load();
      } catch (e) {
        if (mounted) setState(() => error = e.toString());
      }
    }
  }
}
