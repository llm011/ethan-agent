import 'dart:async';
import 'dart:convert';

import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';

import '../data/api_client.dart';
import '../data/ethan_repository.dart';
import '../models/app_models.dart';
import '../services/api_service.dart';
import '../widgets/common.dart';

/// Text fields create focus/inherited dependencies inside dialog routes. Do
/// not dispose their controllers in the same frame that the route is popped;
/// Flutter can still be deactivating the dialog subtree then, which triggers
/// InheritedElement's `_dependents.isEmpty` assertion. Waiting for the route
/// transition and one subsequent frame makes disposal deterministic for every
/// editor in Settings and the workspace.
Future<void> _disposeDialogControllers(
    Iterable<TextEditingController> controllers) async {
  await Future<void>.delayed(const Duration(milliseconds: 350));
  WidgetsBinding.instance.addPostFrameCallback((_) {
    for (final controller in controllers) {
      controller.dispose();
    }
  });
}

void _popEditorDialog<T>(BuildContext dialogContext, [T? result]) {
  // Release the active field before the dialog subtree starts deactivation.
  // This prevents FocusScope/TextField dependents from surviving the route
  // teardown and tripping Flutter's `_dependents.isEmpty` assertion.
  FocusScope.of(dialogContext).unfocus();
  Navigator.of(dialogContext).pop<T>(result);
}

class ResourceScreen extends StatefulWidget {
  const ResourceScreen({required this.kind, this.api, super.key});
  final String kind;
  final EthanApiService? api;

  @override
  State<ResourceScreen> createState() => _ResourceScreenState();
}

class _ResourceScreenState extends State<ResourceScreen> {
  late Future<List<ResourceItem>> _future;
  String _query = '';
  bool _semanticSearch = true;

  @override
  void initState() {
    super.initState();
    _future = _load();
  }

  Future<List<ResourceItem>> _load() => widget.api == null
      ? Future<List<ResourceItem>>.error(
          const EthanApiException(null, '尚未配置服务器连接'))
      : _loadResourceItems();

  Future<List<ResourceItem>> _loadResourceItems() async {
    final api = widget.api!;
    if (widget.kind == 'knowledge' && _query.trim().isNotEmpty) {
      final body = _semanticSearch
          ? await api.searchKnowledge(_query.trim())
          : await api.getKnowledge(query: _query.trim(), mode: 'keyword');
      return _asRows(body['results'] ?? body['items'])
          .map((item) => ResourceItem(
                id: _text(item['source']),
                title: _text(item['title'], fallback: '未命名知识'),
                subtitle: _tags(item['tags']),
                detail: _text(item['content']),
              ))
          .toList();
    }
    if (widget.kind == 'knowledge') {
      final body = await api.getKnowledge();
      return _asRows(body['items'])
          .map((item) => ResourceItem(
                id: _text(item['source']),
                title: _text(item['title'], fallback: '未命名知识'),
                subtitle: _tags(item['tags']),
                detail: _text(item['content']),
              ))
          .toList();
    }
    if (widget.kind == 'skills') {
      final body = await api.getSkills();
      return _asRows(body['skills'])
          .map((item) => ResourceItem(
                id: _text(item['name']),
                title: _text(item['name'], fallback: '未命名技能'),
                subtitle: _tags(item['trigger']),
                detail: _text(item['content'],
                    fallback: _text(item['description'])),
              ))
          .toList();
    }
    if (widget.kind == 'memory') {
      final body = await api.getFacts();
      final rows = _asRows(body['facts']);
      return rows.asMap().entries.map((entry) {
        final item = entry.value;
        return ResourceItem(
            id: '${entry.key}',
            title: _text(item['content'], fallback: '未命名记忆'),
            subtitle: [_text(item['category']), _text(item['source'])]
                .where((v) => v.isNotEmpty)
                .join(' · '),
            detail: _text(item['content']));
      }).toList();
    }
    return api.fetchResources(widget.kind, query: _query);
  }

  void _refresh() {
    if (!mounted) return;
    setState(() {
      _future = _load();
    });
  }

  void _search(String value) {
    setState(() {
      _query = value;
      _future = _load();
    });
  }

  @override
  Widget build(BuildContext context) {
    final meta = _resourceMeta(widget.kind);
    return EthanPage(
      title: meta.title,
      subtitle: meta.subtitle,
      actions: [
        if (widget.kind == 'knowledge')
          IconButton(
              onPressed: () {
                setState(() => _semanticSearch = !_semanticSearch);
                if (_query.trim().isNotEmpty) _refresh();
              },
              tooltip: _semanticSearch ? '切换关键词检索' : '切换语义检索',
              icon: Icon(_semanticSearch
                  ? Icons.psychology_rounded
                  : Icons.manage_search_rounded)),
        if (const {'knowledge', 'skills'}.contains(widget.kind))
          IconButton(
              onPressed: () => _editItem(null),
              icon: const Icon(Icons.add_rounded),
              tooltip: '新建'),
        IconButton(
            onPressed: _refresh,
            icon: const Icon(Icons.refresh_rounded),
            tooltip: '刷新')
      ],
      child: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 4, 16, 8),
            child: TextField(
              onChanged: _search,
              decoration: InputDecoration(
                  prefixIcon: const Icon(Icons.search_rounded),
                  hintText: '搜索${meta.title}…'),
            ),
          ),
          Expanded(
            child: FutureBuilder<List<ResourceItem>>(
              future: _future,
              builder: (context, snapshot) => _AsyncList(
                snapshot: snapshot,
                emptyText: '暂无${meta.title}',
                onRetry: _refresh,
                itemBuilder: (item) => InfoTile(
                  icon: meta.icon,
                  title: item.title,
                  subtitle: item.subtitle.isEmpty ? '点击查看详情' : item.subtitle,
                  onTap: () => _openDetail(item),
                  trailing: (const {'memory', 'knowledge', 'skills'}
                          .contains(widget.kind))
                      ? PopupMenuButton<String>(
                          onSelected: (action) {
                            if (action == 'edit') _editItem(item);
                            if (action == 'delete') _deleteItem(item);
                          },
                          itemBuilder: (_) => const [
                                PopupMenuItem(value: 'edit', child: Text('编辑')),
                                PopupMenuItem(
                                    value: 'delete', child: Text('删除')),
                              ])
                      : null,
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Future<void> _editItem(ResourceItem? item) async {
    final title = TextEditingController(text: item?.title ?? '');
    final content = TextEditingController(text: item?.detail ?? '');
    final tags = TextEditingController(text: item?.subtitle ?? '');
    final result = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
              title: Text(item == null
                  ? '新建${_resourceMeta(widget.kind).title}'
                  : '编辑${_resourceMeta(widget.kind).title}'),
              content: SizedBox(
                  width: 520,
                  child: Column(mainAxisSize: MainAxisSize.min, children: [
                    if (widget.kind != 'memory')
                      TextField(
                          controller: title,
                          decoration:
                              const InputDecoration(labelText: '标题 / 名称')),
                    TextField(
                        controller: content,
                        minLines: 3,
                        maxLines: 8,
                        decoration: const InputDecoration(labelText: '内容')),
                    if (widget.kind != 'memory')
                      TextField(
                          controller: tags,
                          decoration: const InputDecoration(
                              labelText: '标签 / 触发词（逗号分隔）')),
                  ])),
              actions: [
                TextButton(
                    onPressed: () => _popEditorDialog(context),
                    child: const Text('取消')),
                FilledButton(
                    onPressed: () async {
                      try {
                        final api = widget.api!;
                        final list = tags.text
                            .split(',')
                            .map((e) => e.trim())
                            .where((e) => e.isNotEmpty)
                            .toList();
                        if (widget.kind == 'knowledge') {
                          final body = {
                            'title': title.text.trim(),
                            'content': content.text,
                            'tags': list
                          };
                          if (item == null)
                            await api.addKnowledge(body);
                          else
                            await api.updateKnowledge(item.id, body);
                        } else if (widget.kind == 'skills') {
                          await api.saveSkill({
                            'name': title.text.trim(),
                            'description': content.text,
                            'trigger': list,
                            'content': content.text
                          });
                        } else if (widget.kind == 'memory' && item != null) {
                          await api
                              .updateFact(item.id, {'content': content.text});
                        }
                        if (context.mounted) _popEditorDialog(context, true);
                      } catch (error) {
                        if (context.mounted)
                          ScaffoldMessenger.of(context).showSnackBar(
                              SnackBar(content: Text('保存失败：$error')));
                      }
                    },
                    child: const Text('保存'))
              ],
            ));
    await _disposeDialogControllers([title, content, tags]);
    if (result == true) _refresh();
  }

  Future<void> _deleteItem(ResourceItem item) async {
    if (widget.api == null) return;
    try {
      if (widget.kind == 'knowledge')
        await widget.api!.deleteKnowledge(item.id);
      if (widget.kind == 'skills') await widget.api!.deleteSkill(item.id);
      if (widget.kind == 'memory') await widget.api!.deleteFact(item.id);
      _refresh();
    } catch (error) {
      if (mounted)
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('删除失败：$error')));
    }
  }

  Future<void> _openDetail(ResourceItem item) async {
    var detail = item.detail;
    if (widget.kind == 'docs' && item.id.isNotEmpty && widget.api != null) {
      try {
        detail = await widget.api!.fetchDoc(item.id);
      } catch (error) {
        detail = '文档加载失败：$error';
      }
    }
    if (!mounted) return;
    await showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      isScrollControlled: true,
      builder: (context) => SafeArea(
        child: SizedBox(
          height: MediaQuery.sizeOf(context).height * .7,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(24, 4, 24, 24),
            child:
                Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(item.title, style: Theme.of(context).textTheme.titleLarge),
              const SizedBox(height: 16),
              Expanded(
                  child: SingleChildScrollView(
                      child: SelectableText(
                          detail.isEmpty ? '没有可显示的详细内容。' : detail))),
            ]),
          ),
        ),
      ),
    );
  }
}

class MemoryScreen extends StatefulWidget {
  const MemoryScreen({required this.api, this.repository, super.key});
  final EthanApiService api;
  final EthanRepository? repository;

  @override
  State<MemoryScreen> createState() => _MemoryScreenState();
}

class _MemoryScreenState extends State<MemoryScreen>
    with SingleTickerProviderStateMixin {
  late final TabController _tabs = TabController(length: 4, vsync: this);
  late Future<List<Map<String, dynamic>>> _future;
  final _search = TextEditingController();
  String _recordStatus = '';
  String _recordType = '';
  String _recordDomain = '';
  DateTime? _insightDate;

  @override
  void initState() {
    super.initState();
    _future = _load();
    _tabs.addListener(() {
      if (!_tabs.indexIsChanging) _refresh();
    });
  }

  @override
  void dispose() {
    _tabs.dispose();
    _search.dispose();
    super.dispose();
  }

  Future<List<Map<String, dynamic>>> _load({bool force = false}) async {
    final tab = _tabs.index;
    final body = switch (tab) {
      0 =>
        await (widget.repository?.facts(force: force) ?? widget.api.getFacts()),
      1 => _insightDate == null
          ? await widget.api.getInsights(limit: 50)
          : await widget.api.getInsightsByDate(_dateKey(_insightDate!)),
      2 => await widget.api.getProcedures(),
      _ when _search.text.trim().isNotEmpty => await widget.api.searchRecords(
          _search.text.trim(),
          type: _recordType.isEmpty ? null : _recordType,
          domain: _recordDomain.isEmpty ? null : _recordDomain,
          status: _recordStatus.isEmpty ? null : _recordStatus),
      _ => await (widget.repository?.records(
              type: _recordType.isEmpty ? null : _recordType,
              domain: _recordDomain.isEmpty ? null : _recordDomain,
              status: _recordStatus.isEmpty ? null : _recordStatus) ??
          widget.api.getRecords(
              type: _recordType.isEmpty ? null : _recordType,
              domain: _recordDomain.isEmpty ? null : _recordDomain,
              status: _recordStatus.isEmpty ? null : _recordStatus)),
    };
    final key = switch (tab) {
      0 => 'facts',
      1 => 'items',
      2 => 'procedures',
      _ => 'items',
    };
    return _asRows(body[key] ?? body['records']);
  }

  // A refresh after any edit must bypass the shared repository snapshot;
  // otherwise the list can keep showing the pre-save text until the page is
  // recreated.
  void _refresh({bool force = true}) {
    if (!mounted) return;
    setState(() {
      _future = _load(force: force);
    });
  }

  String _dateKey(DateTime value) =>
      '${value.year.toString().padLeft(4, '0')}-${value.month.toString().padLeft(2, '0')}-${value.day.toString().padLeft(2, '0')}';

  Future<void> _pickInsightDate() async {
    final selected = await showDatePicker(
        context: context,
        initialDate: _insightDate ?? DateTime.now(),
        firstDate: DateTime(2020),
        lastDate: DateTime(2100));
    if (selected != null && mounted) {
      setState(() {
        _insightDate = selected;
        _future = _load();
      });
    }
  }

  String _title(Map<String, dynamic> item) => _text(item['title'],
      fallback: _text(item['content'],
          fallback: _text(item['name'], fallback: '未命名记忆')));

  String _subtitle(Map<String, dynamic> item) => [
        _text(item['type']),
        _text(item['status']),
        _text(item['category']),
        _text(item['source']),
        _text(item['summary'])
      ].where((text) => text.isNotEmpty).join(' · ');

  Future<void> _editRecord(Map<String, dynamic> record) async {
    final id = _text(record['id']);
    if (id.isEmpty) return;
    final content = TextEditingController(
        text: _text(record['content'], fallback: _text(record['summary'])));
    var confidence = _number(record['confidence'])?.toDouble() ?? 0.0;
    var importance = _number(record['importance'])?.toDouble() ?? 0.0;
    final saved = await showDialog<bool>(
        context: context,
        builder: (dialog) => AlertDialog(
              title: Text(_title(record)),
              content: StatefulBuilder(builder: (context, setDialogState) {
                return SingleChildScrollView(
                    child: Column(mainAxisSize: MainAxisSize.min, children: [
                  TextField(
                      controller: content,
                      minLines: 4,
                      maxLines: 10,
                      decoration: const InputDecoration(labelText: '内容')),
                  const SizedBox(height: 12),
                  _slider('置信度', confidence,
                      (value) => setDialogState(() => confidence = value)),
                  _slider('重要度', importance,
                      (value) => setDialogState(() => importance = value)),
                ]));
              }),
              actions: [
                TextButton(
                    onPressed: () => _popEditorDialog(dialog),
                    child: const Text('取消')),
                FilledButton(
                    onPressed: () async {
                      await widget.api.updateRecord(id, {
                        'content': content.text,
                        'confidence': confidence,
                        'importance': importance,
                      });
                      if (dialog.mounted) _popEditorDialog(dialog, true);
                    },
                    child: const Text('保存')),
              ],
            ));
    await _disposeDialogControllers([content]);
    if (saved == true) _refresh(force: true);
  }

  Future<void> _recordAction(String action, Map<String, dynamic> record) async {
    final id = _text(record['id']);
    if (id.isEmpty) return;
    if (action == 'edit') return _editRecord(record);
    if (action == 'confirm') await widget.api.confirmRecord(id);
    if (action == 'evidence') return _showEvidence(id);
    if (action == 'delete') {
      final confirmed = await showDialog<bool>(
          context: context,
          builder: (dialog) => AlertDialog(
                title: const Text('删除这条记录？'),
                content: const Text('删除后无法恢复。'),
                actions: [
                  TextButton(
                      onPressed: () => Navigator.pop(dialog, false),
                      child: const Text('取消')),
                  FilledButton(
                      onPressed: () => Navigator.pop(dialog, true),
                      child: const Text('删除'))
                ],
              ));
      if (confirmed != true) return;
      await widget.api.deleteRecord(id);
    }
    _refresh(force: true);
  }

  Future<void> _showEvidence(String id) async {
    try {
      final body = await widget.api.getRecordEvidence(id);
      if (!mounted) return;
      await showModalBottomSheet<void>(
          context: context,
          showDragHandle: true,
          isScrollControlled: true,
          builder: (_) => SafeArea(
              child: SizedBox(
                  height: MediaQuery.sizeOf(context).height * .7,
                  child: SingleChildScrollView(
                      padding: const EdgeInsets.all(20),
                      child: SelectableText(
                          const JsonEncoder.withIndent('  ').convert(body))))));
    } catch (error) {
      if (mounted)
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('加载证据失败：$error')));
    }
  }

  Widget _slider(String label, double value, ValueChanged<double> onChanged) =>
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('$label ${(value * 100).round()}%'),
        Slider(value: value.clamp(0, 1), onChanged: onChanged),
      ]);

  Widget _recordFilter(
          String label, String current, ValueChanged<String> onChanged) =>
      PopupMenuButton<String>(
          tooltip: '$label筛选',
          onSelected: onChanged,
          itemBuilder: (_) {
            final values = label == '领域'
                ? const ['', 'general', 'companion']
                : const ['', 'fact', 'preference', 'decision', 'instruction'];
            return values
                .map((value) => PopupMenuItem(
                    value: value,
                    child: Text(value.isEmpty ? '$label：全部' : value)))
                .toList();
          },
          child: OutlinedButton.icon(
              onPressed: null,
              icon: const Icon(Icons.filter_alt_outlined, size: 18),
              label: Text(current.isEmpty ? '$label：全部' : current)));

  Future<void> _showFact(Map<String, dynamic> fact, int index) async {
    final id = _text(fact['id']);
    // Facts are backed by structured-memory IDs.  An array offset is never a
    // valid server ID and using it here could mutate or delete another record.
    if (id.isEmpty) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('该事实缺少服务端 ID，无法安全修改或删除。')));
      }
      return;
    }
    final content = TextEditingController(text: _text(fact['content']));
    var confidence = _number(fact['confidence'])?.toDouble() ?? 0.0;
    final saved = await showDialog<bool>(
        context: context,
        builder: (dialog) => AlertDialog(
              title: const Text('编辑事实记忆'),
              content: StatefulBuilder(builder: (context, setDialogState) {
                return SingleChildScrollView(
                    child: Column(mainAxisSize: MainAxisSize.min, children: [
                  TextField(
                      controller: content,
                      minLines: 4,
                      maxLines: 10,
                      decoration: const InputDecoration(labelText: '内容')),
                  _slider('置信度', confidence,
                      (value) => setDialogState(() => confidence = value)),
                  Align(
                      alignment: Alignment.centerLeft,
                      child:
                          Text('来源：${_text(fact['source'], fallback: '无')}')),
                ]));
              }),
              actions: [
                TextButton(
                    onPressed: () => _popEditorDialog(dialog),
                    child: const Text('取消')),
                TextButton(
                    onPressed: () async {
                      final confirmed = await showDialog<bool>(
                          context: dialog,
                          builder: (confirm) => AlertDialog(
                                title: const Text('删除这条事实记忆？'),
                                content: const Text('删除后无法恢复。'),
                                actions: [
                                  TextButton(
                                      onPressed: () =>
                                          Navigator.pop(confirm, false),
                                      child: const Text('取消')),
                                  FilledButton(
                                      onPressed: () =>
                                          Navigator.pop(confirm, true),
                                      child: const Text('删除')),
                                ],
                              ));
                      if (confirmed == true) {
                        await widget.api.deleteFact(id);
                        if (dialog.mounted) _popEditorDialog(dialog, true);
                      }
                    },
                    child: const Text('删除')),
                FilledButton(
                    onPressed: () async {
                      await widget.api.updateFact(id, {
                        'content': content.text,
                        'confidence': confidence,
                      });
                      if (dialog.mounted) _popEditorDialog(dialog, true);
                    },
                    child: const Text('保存')),
              ],
            ));
    await _disposeDialogControllers([content]);
    // Facts are served through the repository cache; invalidate it after an
    // edit so the updated text is visible immediately without leaving the
    // Memory page and re-entering it.
    if (saved == true) _refresh(force: true);
  }

  @override
  Widget build(BuildContext context) => EthanPage(
        title: '记忆',
        subtitle: '事实、永久记忆、流程与结构化记录',
        actions: [
          if (_tabs.index == 3)
            IconButton(
                onPressed: () async {
                  await widget.api.consolidateRecords();
                  _refresh();
                },
                icon: const Icon(Icons.auto_awesome_rounded),
                tooltip: '整理结构化记忆'),
          IconButton(
              onPressed: _refresh, icon: const Icon(Icons.refresh_rounded))
        ],
        child: Column(children: [
          TabBar(controller: _tabs, isScrollable: true, tabs: const [
            Tab(text: '事实'),
            Tab(text: '永久记忆'),
            Tab(text: '流程'),
            Tab(text: '结构化记忆')
          ]),
          if (_tabs.index == 1)
            Padding(
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
                child: SingleChildScrollView(
                    scrollDirection: Axis.horizontal,
                    child: Row(children: [
                      OutlinedButton.icon(
                          onPressed: _pickInsightDate,
                          icon: const Icon(Icons.calendar_today_rounded),
                          label: Text(_insightDate == null
                              ? '全部日期'
                              : _dateKey(_insightDate!))),
                      if (_insightDate != null)
                        IconButton(
                            tooltip: '清除日期过滤',
                            onPressed: () => setState(() {
                                  _insightDate = null;
                                  _future = _load(force: true);
                                }),
                            icon: const Icon(Icons.clear_rounded))
                    ]))),
          if (_tabs.index == 3)
            Padding(
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
                child: Row(children: [
                  Expanded(
                      child: TextField(
                          controller: _search,
                          onSubmitted: (_) => _refresh(),
                          decoration: const InputDecoration(
                              hintText: '搜索结构化记忆',
                              prefixIcon: Icon(Icons.search_rounded)))),
                  const SizedBox(width: 8),
                  DropdownButton<String>(
                      value: _recordStatus,
                      items: const [
                        DropdownMenuItem(value: '', child: Text('全部')),
                        DropdownMenuItem(value: 'pending', child: Text('候选')),
                        DropdownMenuItem(
                            value: 'confirmed', child: Text('已确认')),
                        DropdownMenuItem(
                            value: 'superseded', child: Text('已替代')),
                      ],
                      onChanged: (value) {
                        _recordStatus = value ?? '';
                        _refresh();
                      }),
                  const SizedBox(width: 8),
                  _recordFilter('类型', _recordType, (value) {
                    _recordType = value;
                    _refresh();
                  }),
                  const SizedBox(width: 8),
                  _recordFilter('领域', _recordDomain, (value) {
                    _recordDomain = value;
                    _refresh();
                  }),
                ])),
          Expanded(
              child: FutureBuilder<List<Map<String, dynamic>>>(
                  future: _future,
                  builder: (context, snapshot) {
                    if (snapshot.connectionState != ConnectionState.done) {
                      return const Center(child: CircularProgressIndicator());
                    }
                    if (snapshot.hasError)
                      return _errorView(snapshot.error, _refresh);
                    final items = snapshot.data ?? const [];
                    if (items.isEmpty) return const Center(child: Text('暂无数据'));
                    return ListView.builder(
                        itemCount: items.length,
                        itemBuilder: (_, index) {
                          final item = items[index];
                          final record = _tabs.index == 3;
                          return Card(
                              margin: const EdgeInsets.symmetric(
                                  horizontal: 16, vertical: 5),
                              child: ListTile(
                                  onTap: record
                                      ? () => _editRecord(item)
                                      : () => _showFact(item, index),
                                  title: Text(_title(item)),
                                  subtitle: Text(_subtitle(item)),
                                  trailing: record
                                      ? PopupMenuButton<String>(
                                          onSelected: (action) =>
                                              _recordAction(action, item),
                                          itemBuilder: (_) => const [
                                                PopupMenuItem(
                                                    value: 'edit',
                                                    child: Text('编辑')),
                                                PopupMenuItem(
                                                    value: 'confirm',
                                                    child: Text('确认')),
                                                PopupMenuItem(
                                                    value: 'delete',
                                                    child: Text('删除')),
                                                PopupMenuItem(
                                                    value: 'evidence',
                                                    child: Text('查看证据')),
                                              ])
                                      : null));
                        });
                  }))
        ]),
      );
}

class AgendaScreen extends StatefulWidget {
  const AgendaScreen({this.api, this.repository, super.key});
  final EthanApiService? api;
  final EthanRepository? repository;
  @override
  State<AgendaScreen> createState() => _AgendaScreenState();
}

class _AgendaScreenState extends State<AgendaScreen> {
  late Future<List<AgendaItem>> _future;
  DateTime _month = DateTime(DateTime.now().year, DateTime.now().month);
  DateTime _selectedDate = DateTime.now();
  bool _calendarExpanded = true;
  bool enabled = true;
  bool toggling = false;
  @override
  void initState() {
    super.initState();
    _future = _load(force: true);
    _loadEnabled();
  }

  Future<List<AgendaItem>> _load({bool force = false}) => widget.api == null
      ? Future<List<AgendaItem>>.error(
          const EthanApiException(null, '尚未配置服务器连接'))
      : (widget.repository?.agenda(force: force) ?? widget.api!.fetchAgenda());
  void _refresh({bool force = true}) {
    if (!mounted) return;
    setState(() {
      _future = _load(force: force);
    });
  }

  String _dayKey(DateTime value) =>
      '${value.year.toString().padLeft(4, '0')}-${value.month.toString().padLeft(2, '0')}-${value.day.toString().padLeft(2, '0')}';

  DateTime? _eventDate(AgendaItem item) {
    // Pending recurring events are displayed at their next actual run, just
    // like Android's `eventDateKey`; a historical start date is not the day
    // that should receive the calendar marker.
    final raw = item.status == 'pending' && item.nextRunTime.trim().isNotEmpty
        ? item.nextRunTime.trim()
        : item.when.trim();
    if (raw.isEmpty) return null;
    final parsed = DateTime.tryParse(raw.replaceFirst(' ', 'T')) ??
        DateTime.tryParse(raw.split(' ').first);
    return parsed?.toLocal();
  }

  List<AgendaItem> _forSelectedDate(List<AgendaItem> items) =>
      items.where((item) {
        final date = _eventDate(item);
        return date == null || _dayKey(date) == _dayKey(_selectedDate);
      }).toList();

  Widget _calendar(List<AgendaItem> items) {
    final first = DateTime(_month.year, _month.month, 1);
    final days = DateTime(_month.year, _month.month + 1, 0).day;
    final leading = first.weekday % 7;
    final cells = <Widget>[];
    for (var i = 0; i < leading; i++) {
      cells.add(const SizedBox.shrink());
    }
    for (var day = 1; day <= days; day++) {
      final date = DateTime(_month.year, _month.month, day);
      final count = items.where((item) {
        final eventDate = _eventDate(item);
        return eventDate != null && _dayKey(eventDate) == _dayKey(date);
      }).length;
      final selected = _dayKey(date) == _dayKey(_selectedDate);
      cells.add(InkWell(
          borderRadius: BorderRadius.circular(10),
          onTap: () {
            setState(() {
              _selectedDate = date;
              _calendarExpanded = false;
            });
            // A date is enough context for a quick event. The editor fills a
            // server-compatible default time and only asks for title/content.
            _edit(null, date);
          },
          child: Container(
              margin: const EdgeInsets.all(2),
              decoration: BoxDecoration(
                  color: selected
                      ? Theme.of(context).colorScheme.primaryContainer
                      : null,
                  borderRadius: BorderRadius.circular(10)),
              child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Text('$day',
                        style: TextStyle(
                            fontWeight: selected
                                ? FontWeight.w800
                                : FontWeight.normal)),
                    if (count > 0)
                      Text('$count',
                          style: TextStyle(
                              fontSize: 10,
                              color: Theme.of(context).colorScheme.primary))
                  ]))));
    }
    final header = Row(children: [
      IconButton(
          onPressed: () => setState(() {
                _month = DateTime(_month.year, _month.month - 1);
              }),
          icon: const Icon(Icons.chevron_left_rounded)),
      Expanded(
          child: Text('${_month.year}年${_month.month}月',
              textAlign: TextAlign.center,
              style: const TextStyle(fontWeight: FontWeight.w700))),
      IconButton(
          onPressed: () => setState(() {
                _month = DateTime(_month.year, _month.month + 1);
              }),
          icon: const Icon(Icons.chevron_right_rounded)),
      TextButton(
          onPressed: () => setState(() {
                final now = DateTime.now();
                _month = DateTime(now.year, now.month);
                _selectedDate = now;
              }),
          child: const Text('今天')),
      Text('点日期新建',
          style: Theme.of(context).textTheme.labelSmall?.copyWith(
                color: Theme.of(context).colorScheme.onSurfaceVariant,
              )),
      IconButton(
          tooltip: _calendarExpanded ? '收起日历' : '展开日历',
          onPressed: () =>
              setState(() => _calendarExpanded = !_calendarExpanded),
          icon: Icon(_calendarExpanded
              ? Icons.expand_less_rounded
              : Icons.expand_more_rounded)),
    ]);
    if (!_calendarExpanded) return header;
    return Column(children: [
      header,
      Row(
          children: ['日', '一', '二', '三', '四', '五', '六']
              .map((day) => Expanded(
                  child: Center(
                      child: Text(day,
                          style: Theme.of(context).textTheme.labelSmall))))
              .toList()),
      GridView.count(
          crossAxisCount: 7,
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          children: cells),
    ]);
  }

  Future<void> _loadEnabled() async {
    if (widget.api == null) return;
    try {
      final body = await widget.api!.getAgenda();
      if (mounted && body['enabled'] is bool)
        setState(() => enabled = body['enabled'] as bool);
    } catch (_) {}
  }

  Future<void> _pickAgendaTime(
      BuildContext dialogContext, TextEditingController when) async {
    final current = DateTime.tryParse(when.text.trim().replaceFirst(' ', 'T'));
    final baseDate = current ?? _selectedDate;
    final initial =
        DateTime(2020, 1, 1, current?.hour ?? 9, current?.minute ?? 0);
    var selected = initial;
    final picked = await showCupertinoModalPopup<DateTime>(
        context: dialogContext,
        builder: (pickerContext) => Container(
              height: 280,
              color:
                  CupertinoColors.systemBackground.resolveFrom(pickerContext),
              child: SafeArea(
                top: false,
                child: Column(children: [
                  Row(children: [
                    const Spacer(),
                    CupertinoButton(
                        padding: const EdgeInsets.symmetric(horizontal: 20),
                        onPressed: () =>
                            Navigator.of(pickerContext).pop(selected),
                        child: const Text('完成')),
                  ]),
                  Expanded(
                    child: CupertinoDatePicker(
                      mode: CupertinoDatePickerMode.time,
                      use24hFormat: true,
                      initialDateTime: initial,
                      onDateTimeChanged: (value) {
                        selected = value;
                      },
                    ),
                  ),
                ]),
              ),
            ));
    if (!dialogContext.mounted || picked == null) return;
    final date = '${baseDate.year.toString().padLeft(4, '0')}-'
        '${baseDate.month.toString().padLeft(2, '0')}-'
        '${baseDate.day.toString().padLeft(2, '0')}';
    when.text = '$date ${picked.hour.toString().padLeft(2, '0')}:'
        '${picked.minute.toString().padLeft(2, '0')}';
  }

  Future<void> _toggleEnabled(bool value) async {
    setState(() {
      enabled = value;
      toggling = true;
    });
    try {
      await widget.api!.setAgendaEnabled({'enabled': value});
    } catch (e) {
      if (mounted) {
        setState(() => enabled = !value);
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('更新失败：$e')));
      }
    } finally {
      if (mounted) setState(() => toggling = false);
    }
  }

  Future<void> _edit([AgendaItem? item, DateTime? presetDate]) async {
    final quickCreate = item == null && presetDate != null;
    final presetDateKey = presetDate == null ? '' : _dayKey(presetDate);
    final title = TextEditingController(text: item?.title ?? '');
    final when = TextEditingController(
        text: item?.when ?? '${_dayKey(presetDate ?? _selectedDate)} 09:00');
    final note = TextEditingController(text: item?.note ?? '');
    var repeat = item?.repeat ?? 'none';
    final weekdays = <int>{...?item?.weekdays};
    final ok = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
              title: Text(quickCreate
                  ? '$presetDateKey 新建日程'
                  : item == null
                      ? '新建日程'
                      : '编辑日程'),
              content: Column(mainAxisSize: MainAxisSize.min, children: [
                TextField(
                    controller: title,
                    decoration: const InputDecoration(labelText: '标题')),
                if (!quickCreate)
                  TextField(
                      controller: when,
                      readOnly: true,
                      onTap: () => _pickAgendaTime(context, when),
                      decoration: const InputDecoration(
                          labelText: '时间（滑动选择）',
                          suffixIcon: Icon(Icons.schedule_rounded))),
                TextField(
                    controller: note,
                    minLines: quickCreate ? 3 : 1,
                    maxLines: quickCreate ? 6 : 3,
                    decoration:
                        InputDecoration(labelText: quickCreate ? '内容' : '备注')),
                if (!quickCreate)
                  StatefulBuilder(
                      builder: (context, setDialogState) => Column(children: [
                            DropdownButtonFormField<String>(
                                value: repeat,
                                decoration:
                                    const InputDecoration(labelText: '重复'),
                                items: const [
                                  DropdownMenuItem(
                                      value: 'none', child: Text('不重复')),
                                  DropdownMenuItem(
                                      value: 'daily', child: Text('每天')),
                                  DropdownMenuItem(
                                      value: 'weekly', child: Text('每周')),
                                ],
                                onChanged: (value) => setDialogState(
                                    () => repeat = value ?? 'none')),
                            if (repeat == 'weekly')
                              Wrap(
                                  spacing: 4,
                                  children: List.generate(7, (index) {
                                    final day = index + 1;
                                    return FilterChip(
                                        label: Text('${day == 7 ? '日' : day}'),
                                        selected: weekdays.contains(day),
                                        onSelected: (selected) =>
                                            setDialogState(() => selected
                                                ? weekdays.add(day)
                                                : weekdays.remove(day)));
                                  }))
                          ])),
              ]),
              actions: [
                TextButton(
                    onPressed: () => _popEditorDialog(context),
                    child: const Text('取消')),
                FilledButton(
                    onPressed: () async {
                      try {
                        final body = {
                          'title': title.text.trim(),
                          // Quick creation uses the tapped date and a
                          // deterministic default time; users need not type
                          // a time just to add a day-level event.
                          'when': quickCreate
                              ? '$presetDateKey 09:00'
                              : when.text.trim(),
                          'repeat': repeat,
                          'weekdays': weekdays.toList()..sort(),
                          'note': note.text
                        };
                        if (item == null)
                          await widget.api!.createAgenda(body);
                        else
                          await widget.api!.patchAgenda(item.id, body);
                        if (context.mounted) _popEditorDialog(context, true);
                      } catch (e) {
                        if (context.mounted)
                          ScaffoldMessenger.of(context)
                              .showSnackBar(SnackBar(content: Text('保存失败：$e')));
                      }
                    },
                    child: const Text('保存'))
              ],
            ));
    await _disposeDialogControllers([title, when, note]);
    if (ok == true) _refresh(force: true);
  }

  @override
  Widget build(BuildContext context) => EthanPage(
        title: '日程',
        subtitle: '来自 Ethan 日程服务',
        actions: [
          IconButton(
              onPressed: () => _edit(),
              icon: const Icon(Icons.add_rounded),
              tooltip: '新建'),
          IconButton(
              onPressed: () => _toggleEnabled(!enabled),
              icon: Icon(enabled
                  ? Icons.notifications_active_rounded
                  : Icons.notifications_off_rounded),
              tooltip: enabled ? '停用日程工具' : '启用日程工具'),
          IconButton(
              onPressed: _refresh,
              icon: const Icon(Icons.refresh_rounded),
              tooltip: '刷新')
        ],
        child: FutureBuilder<List<AgendaItem>>(
          future: _future,
          builder: (context, snapshot) {
            if (snapshot.connectionState != ConnectionState.done) {
              return const Center(child: CircularProgressIndicator());
            }
            if (snapshot.hasError) return _errorView(snapshot.error, _refresh);
            final all = snapshot.data ?? const <AgendaItem>[];
            final events = _forSelectedDate(all);
            final eventCards = <Widget>[
              if (events.isEmpty)
                const Padding(
                    padding: EdgeInsets.all(36),
                    child: Center(child: Text('当天暂无日程'))),
              ...events.map((event) => Card(
                    margin:
                        const EdgeInsets.symmetric(horizontal: 16, vertical: 5),
                    child: ListTile(
                      leading: const Icon(Icons.event_rounded),
                      title: Text(event.title,
                          style: const TextStyle(fontWeight: FontWeight.w700)),
                      subtitle: Text([
                        event.when,
                        event.nextRunTime,
                        event.note,
                        _agendaStatus(event)
                      ].where((part) => part.isNotEmpty).join(' · ')),
                      trailing: PopupMenuButton<String>(
                          onSelected: (action) async {
                            if (action == 'edit') _edit(event);
                            if (action == 'delete') {
                              final confirmed = await showDialog<bool>(
                                  context: context,
                                  builder: (dialog) => AlertDialog(
                                        title: const Text('删除这个日程？'),
                                        content: const Text('删除后无法恢复。'),
                                        actions: [
                                          TextButton(
                                              onPressed: () =>
                                                  Navigator.pop(dialog, false),
                                              child: const Text('取消')),
                                          FilledButton(
                                              onPressed: () =>
                                                  Navigator.pop(dialog, true),
                                              child: const Text('删除')),
                                        ],
                                      ));
                              if (confirmed == true) {
                                await widget.api!.deleteAgenda(event.id);
                                _refresh(force: true);
                              }
                            }
                            if (action.startsWith('completion:')) {
                              var completion =
                                  action.substring('completion:'.length);
                              if (completion == 'abandoned') {
                                final text = TextEditingController();
                                final actual = await showDialog<String>(
                                    context: context,
                                    builder: (dialog) => AlertDialog(
                                          title: const Text('记录废弃原因'),
                                          content: TextField(
                                              controller: text,
                                              minLines: 2,
                                              maxLines: 4,
                                              decoration: const InputDecoration(
                                                  labelText: '实际完成了什么？')),
                                          actions: [
                                            TextButton(
                                                onPressed: () =>
                                                    _popEditorDialog(dialog),
                                                child: const Text('取消')),
                                            FilledButton(
                                                onPressed: () => Navigator.pop(
                                                    dialog, text.text.trim()),
                                                child: const Text('确认'))
                                          ],
                                        ));
                                await _disposeDialogControllers([text]);
                                if (actual == null) return;
                                await widget.api!.patchAgenda(event.id, {
                                  'completion': 'abandoned',
                                  if (actual.isNotEmpty) 'title': actual,
                                });
                                _refresh(force: true);
                                return;
                              }
                              await widget.api!.patchAgenda(
                                  event.id, {'completion': completion});
                              _refresh(force: true);
                            }
                          },
                          itemBuilder: (_) => const [
                                PopupMenuItem(value: 'edit', child: Text('编辑')),
                                PopupMenuItem(
                                    value: 'completion:done',
                                    child: Text('标记完成')),
                                PopupMenuItem(
                                    value: 'completion:partial',
                                    child: Text('标记部分完成')),
                                PopupMenuItem(
                                    value: 'completion:not_started',
                                    child: Text('重置完成度')),
                                PopupMenuItem(
                                    value: 'completion:abandoned',
                                    child: Text('废弃')),
                                PopupMenuItem(
                                    value: 'delete', child: Text('删除'))
                              ]),
                    ),
                  ))
            ];
            final calendarCard = Padding(
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 4),
                child: Card(
                    child: Padding(
                        padding: const EdgeInsets.all(8),
                        child: _calendar(all))));
            return LayoutBuilder(builder: (context, constraints) {
              final eventList = ListView(children: eventCards);
              final content = constraints.maxWidth >= 700
                  ? Row(children: [
                      Expanded(child: calendarCard),
                      Expanded(child: eventList)
                    ])
                  : ListView(children: [calendarCard, ...eventCards]);
              return RefreshIndicator(
                  onRefresh: () async => _refresh(), child: content);
            });
          },
        ),
      );
}

class ScheduleScreen extends StatefulWidget {
  const ScheduleScreen(
      {this.api, this.repository, this.onOpenSession, super.key});
  final EthanApiService? api;
  final EthanRepository? repository;
  final ValueChanged<String>? onOpenSession;
  @override
  State<ScheduleScreen> createState() => _ScheduleScreenState();
}

class _ScheduleScreenState extends State<ScheduleScreen>
    with SingleTickerProviderStateMixin {
  late Future<List<ScheduleItem>> _future;
  late Future<List<Map<String, dynamic>>> _timelineFuture;
  late final TabController _tabs = TabController(length: 2, vsync: this);
  var _tab = 0;
  var _timelinesLoaded = false;
  final Set<String> _updating = {};
  @override
  void initState() {
    super.initState();
    _future = _load();
    // Do not hit the timeline endpoint while the task list is opening.  A
    // slow/unavailable timeline service must never block the initial page.
    _timelineFuture = Future.value(const <Map<String, dynamic>>[]);
  }

  @override
  void dispose() {
    _tabs.dispose();
    super.dispose();
  }

  Future<List<ScheduleItem>> _load({bool force = false}) {
    if (widget.api == null) {
      return Future<List<ScheduleItem>>.error(
          const EthanApiException(null, '尚未配置服务器连接'));
    }
    final request = widget.repository?.schedules(force: force) ??
        widget.api!.fetchSchedules();
    return request.timeout(const Duration(seconds: 8));
  }

  void _refresh({bool force = true}) {
    if (!mounted) return;
    setState(() {
      _future = _load(force: force);
    });
  }

  Future<List<Map<String, dynamic>>> _loadTimelines() async {
    if (widget.api == null) throw const EthanApiException(null, '尚未配置服务器连接');
    final body = await widget.api!
        .getTimelineStatus()
        .timeout(const Duration(seconds: 8));
    return _asRows(body['timelines']);
  }

  void _refreshTimelines() {
    if (!mounted) return;
    _timelinesLoaded = true;
    setState(() {
      _timelineFuture = _loadTimelines();
    });
  }

  Future<void> _syncTimelines() async {
    try {
      await widget.api!.syncTimelines();
      _refreshTimelines();
      if (mounted)
        ScaffoldMessenger.of(context)
            .showSnackBar(const SnackBar(content: Text('时间线已同步')));
    } catch (error) {
      if (mounted)
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('同步失败：$error')));
    }
  }

  Future<void> _timelineAction(String id, String action) async {
    try {
      await widget.api!.timelineLifecycle(id, action);
      _refreshTimelines();
    } catch (error) {
      if (mounted)
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('操作失败：$error')));
    }
  }

  Future<void> _create() async {
    if (widget.api == null) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(const SnackBar(content: Text('尚未配置服务器连接，无法创建定时任务')));
      }
      return;
    }
    final title = TextEditingController();
    final prompt = TextEditingController();
    final cron = TextEditingController();
    final interval = TextEditingController();
    final endDate = TextEditingController();
    final sessionId = TextEditingController();
    final category = TextEditingController();
    final scene = TextEditingController(text: 'work');
    var triggerType = 'cron';
    final ok = await showDialog<bool>(
        context: context,
        builder: (dialogContext) => AlertDialog(
              title: const Text('新建定时任务'),
              scrollable: true,
              content: StatefulBuilder(builder: (context, setDialogState) {
                return Column(mainAxisSize: MainAxisSize.min, children: [
                  TextField(
                      controller: title,
                      decoration: const InputDecoration(labelText: '任务名称')),
                  TextField(
                      controller: prompt,
                      minLines: 2,
                      maxLines: 4,
                      decoration: const InputDecoration(labelText: '提示词')),
                  DropdownButtonFormField<String>(
                      value: triggerType,
                      decoration: const InputDecoration(labelText: '触发方式'),
                      items: const [
                        DropdownMenuItem(value: 'cron', child: Text('Cron')),
                        DropdownMenuItem(value: 'interval', child: Text('间隔'))
                      ],
                      onChanged: (value) =>
                          setDialogState(() => triggerType = value ?? 'cron')),
                  if (triggerType == 'cron')
                    TextField(
                        controller: cron,
                        decoration: const InputDecoration(
                            labelText: 'Cron（如 0 9 * * *）'))
                  else
                    TextField(
                        controller: interval,
                        keyboardType: TextInputType.number,
                        decoration: const InputDecoration(labelText: '间隔分钟')),
                  TextField(
                      controller: endDate,
                      decoration: const InputDecoration(
                          labelText: '结束时间（可选，YYYY-MM-DD HH:MM）')),
                  TextField(
                      controller: sessionId,
                      decoration:
                          const InputDecoration(labelText: '关联会话 ID（可选）')),
                  TextField(
                      controller: category,
                      decoration: const InputDecoration(labelText: '分类（可选）')),
                  TextField(
                      controller: scene,
                      decoration:
                          const InputDecoration(labelText: '场景（默认 work）')),
                ]);
              }),
              actions: [
                TextButton(
                    onPressed: () => _popEditorDialog(dialogContext),
                    child: const Text('取消')),
                FilledButton(
                    onPressed: () async {
                      try {
                        await widget.api!.createSchedule({
                          'job_id': '',
                          'title': title.text.trim(),
                          'prompt': prompt.text,
                          'cron': triggerType == 'cron' ? cron.text : '',
                          'interval_minutes':
                              int.tryParse(interval.text.trim()) ?? 0,
                          'end_date': endDate.text.trim(),
                          'session_id': sessionId.text.trim(),
                          'category': category.text.trim(),
                          'scene': scene.text.trim().isEmpty
                              ? 'work'
                              : scene.text.trim(),
                        });
                        if (dialogContext.mounted) {
                          _popEditorDialog(dialogContext, true);
                        }
                      } catch (e) {
                        if (dialogContext.mounted)
                          ScaffoldMessenger.of(dialogContext)
                              .showSnackBar(SnackBar(content: Text('创建失败：$e')));
                      }
                    },
                    child: const Text('创建'))
              ],
            ));
    await _disposeDialogControllers([
      title,
      prompt,
      cron,
      interval,
      endDate,
      sessionId,
      category,
      scene,
    ]);
    if (ok == true) _refresh(force: true);
  }

  Future<void> _toggle(ScheduleItem item, bool enabled) async {
    if (widget.api == null) {
      return;
    }
    setState(() => _updating.add(item.id));
    try {
      await widget.api!.updateScheduleState(item.id, enabled);
      _refresh(force: true);
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('更新任务失败：$error')));
      }
    } finally {
      if (mounted) {
        setState(() => _updating.remove(item.id));
      }
    }
  }

  @override
  Widget build(BuildContext context) => EthanPage(
        title: '定时任务',
        subtitle: '管理 Cron、间隔与时间线任务',
        actions: [
          if (_tab == 0)
            IconButton(
                onPressed: _create,
                icon: const Icon(Icons.add_rounded),
                tooltip: '新建'),
          if (_tab == 1)
            IconButton(
                onPressed: _syncTimelines,
                icon: const Icon(Icons.sync_rounded),
                tooltip: '同步时间线'),
          IconButton(
              onPressed: _tab == 0 ? _refresh : _refreshTimelines,
              icon: const Icon(Icons.refresh_rounded),
              tooltip: '刷新')
        ],
        child: Column(children: [
          TabBar(
              controller: _tabs,
              onTap: (index) {
                if (!mounted) return;
                if (index == 1 && !_timelinesLoaded) {
                  _timelinesLoaded = true;
                  setState(() {
                    _tab = index;
                    _timelineFuture = _loadTimelines();
                  });
                } else {
                  setState(() => _tab = index);
                }
              },
              tabs: const [Tab(text: '任务'), Tab(text: '时间线')]),
          Expanded(
              child: _tab == 1
                  ? FutureBuilder<List<Map<String, dynamic>>>(
                      future: _timelineFuture,
                      builder: (context, snapshot) {
                        if (snapshot.connectionState != ConnectionState.done) {
                          return const Center(
                              child: CircularProgressIndicator());
                        }
                        if (snapshot.hasError) {
                          return _errorView(snapshot.error, _refreshTimelines);
                        }
                        final timelines = snapshot.data ?? const [];
                        if (timelines.isEmpty) {
                          return const Center(child: Text('暂无时间线'));
                        }
                        return RefreshIndicator(
                            onRefresh: () async => _refreshTimelines(),
                            child: ListView.builder(
                                itemCount: timelines.length,
                                itemBuilder: (_, index) {
                                  final timeline = timelines[index];
                                  final id = _text(timeline['id'],
                                      fallback: _text(timeline['timeline_id']));
                                  final status = _text(timeline['status'],
                                      fallback: _text(timeline['state']));
                                  return Card(
                                      margin: const EdgeInsets.symmetric(
                                          horizontal: 16, vertical: 5),
                                      child: ListTile(
                                          leading: const Icon(
                                              Icons.timeline_rounded),
                                          title: Text(_text(timeline['title'],
                                              fallback: id)),
                                          subtitle: Text([
                                            status,
                                            _text(timeline['current_phase']),
                                            _text(timeline['next_run_time'])
                                          ]
                                              .where((part) => part.isNotEmpty)
                                              .join(' · ')),
                                          trailing: PopupMenuButton<String>(
                                              onSelected: (action) =>
                                                  _timelineAction(id, action),
                                              itemBuilder: (_) => const [
                                                    PopupMenuItem(
                                                        value: 'pause',
                                                        child: Text('暂停')),
                                                    PopupMenuItem(
                                                        value: 'resume',
                                                        child: Text('恢复')),
                                                    PopupMenuItem(
                                                        value: 'skip_phase',
                                                        child: Text('跳过阶段')),
                                                    PopupMenuItem(
                                                        value: 'advance_phase',
                                                        child: Text('推进阶段')),
                                                    PopupMenuItem(
                                                        value: 'cleanup',
                                                        child: Text('清理'))
                                                  ])));
                                }));
                      })
                  : FutureBuilder<List<ScheduleItem>>(
                      future: _future,
                      builder: (context, snapshot) => _AsyncList(
                        snapshot: snapshot,
                        emptyText: '暂无定时任务',
                        onRetry: _refresh,
                        itemBuilder: (task) {
                          final enabled = task.status == 'active';
                          return Card(
                            margin: const EdgeInsets.symmetric(
                                horizontal: 16, vertical: 5),
                            child: Column(children: [
                              SwitchListTile(
                                value: enabled,
                                onChanged: _updating.contains(task.id)
                                    ? null
                                    : (value) => _toggle(task, value),
                                title: Text(task.title,
                                    style: const TextStyle(
                                        fontWeight: FontWeight.w700)),
                                subtitle: Text([
                                  task.trigger,
                                  if (task.sessionId.isNotEmpty)
                                    '会话 ${task.sessionId}',
                                  task.nextRunTime.isEmpty
                                      ? '已暂停'
                                      : '下次运行 $task.nextRunTime'
                                ].where((part) => part.isNotEmpty).join(' · ')),
                                secondary: _updating.contains(task.id)
                                    ? const SizedBox(
                                        width: 22,
                                        height: 22,
                                        child: CircularProgressIndicator(
                                            strokeWidth: 2))
                                    : const Icon(Icons.schedule_rounded),
                                contentPadding:
                                    const EdgeInsets.symmetric(horizontal: 20),
                              ),
                              OverflowBar(
                                  alignment: MainAxisAlignment.end,
                                  children: [
                                    if (task.sessionId.isNotEmpty)
                                      TextButton.icon(
                                          onPressed: () => widget.onOpenSession
                                              ?.call(task.sessionId),
                                          icon: const Icon(Icons.chat_rounded),
                                          label: const Text('查看对话')),
                                    TextButton.icon(
                                        onPressed: _updating.contains(task.id)
                                            ? null
                                            : () async {
                                                try {
                                                  setState(() =>
                                                      _updating.add(task.id));
                                                  await widget.api!
                                                      .triggerSchedule(task.id);
                                                  if (mounted) {
                                                    final messenger =
                                                        ScaffoldMessenger.of(
                                                            context);
                                                    final controller =
                                                        messenger.showSnackBar(
                                                      SnackBar(
                                                        content:
                                                            const Text('已触发任务'),
                                                        action: task.sessionId
                                                                .isEmpty
                                                            ? null
                                                            : SnackBarAction(
                                                                label: '查看对话',
                                                                onPressed: () => widget
                                                                    .onOpenSession
                                                                    ?.call(task
                                                                        .sessionId)),
                                                      ),
                                                    );
                                                    await controller.closed;
                                                  }
                                                } catch (e) {
                                                  if (mounted)
                                                    ScaffoldMessenger.of(
                                                            context)
                                                        .showSnackBar(SnackBar(
                                                            content: Text(
                                                                '触发失败：$e')));
                                                } finally {
                                                  if (mounted)
                                                    setState(() => _updating
                                                        .remove(task.id));
                                                }
                                              },
                                        icon: const Icon(
                                            Icons.play_arrow_rounded),
                                        label: const Text('立即运行')),
                                    TextButton.icon(
                                        onPressed: _updating.contains(task.id)
                                            ? null
                                            : () async {
                                                final confirmed =
                                                    await showDialog<bool>(
                                                  context: context,
                                                  builder: (dialog) =>
                                                      AlertDialog(
                                                    icon: const Icon(Icons
                                                        .delete_outline_rounded),
                                                    title:
                                                        const Text('删除定时任务？'),
                                                    content: Text(
                                                        '“${task.title}”将从 Ethan 服务端删除，且无法恢复。'),
                                                    actions: [
                                                      TextButton(
                                                          onPressed: () =>
                                                              Navigator.pop(
                                                                  dialog,
                                                                  false),
                                                          child:
                                                              const Text('取消')),
                                                      FilledButton(
                                                          style: FilledButton.styleFrom(
                                                              backgroundColor:
                                                                  Theme.of(
                                                                          context)
                                                                      .colorScheme
                                                                      .error,
                                                              foregroundColor:
                                                                  Theme.of(
                                                                          context)
                                                                      .colorScheme
                                                                      .onError),
                                                          onPressed: () =>
                                                              Navigator.pop(
                                                                  dialog, true),
                                                          child:
                                                              const Text('删除')),
                                                    ],
                                                  ),
                                                );
                                                if (confirmed != true) return;
                                                try {
                                                  await widget.api!
                                                      .deleteSchedule(task.id);
                                                  _refresh();
                                                } catch (e) {
                                                  if (mounted)
                                                    ScaffoldMessenger.of(
                                                            context)
                                                        .showSnackBar(SnackBar(
                                                            content: Text(
                                                                '删除失败：$e')));
                                                }
                                              },
                                        icon: const Icon(
                                            Icons.delete_outline_rounded),
                                        label: const Text('删除')),
                                  ])
                            ]),
                          );
                        },
                      ),
                    )),
        ]),
      );
}

class BackgroundTasksScreen extends StatefulWidget {
  const BackgroundTasksScreen({this.api, this.onOpenSession, super.key});
  final EthanApiService? api;
  final ValueChanged<String>? onOpenSession;
  @override
  State<BackgroundTasksScreen> createState() => _BackgroundTasksScreenState();
}

class _BackgroundTasksScreenState extends State<BackgroundTasksScreen> {
  late Future<List<BackgroundTaskItem>> _future;
  Timer? _poller;
  @override
  void initState() {
    super.initState();
    _future = _load();
    _poller = Timer.periodic(const Duration(seconds: 3), (_) {
      if (mounted) _refresh();
    });
  }

  @override
  void dispose() {
    _poller?.cancel();
    super.dispose();
  }

  Future<List<BackgroundTaskItem>> _load() => widget.api == null
      ? Future<List<BackgroundTaskItem>>.error(
          const EthanApiException(null, '尚未配置服务器连接'))
      : widget.api!.fetchBackgroundTasks();
  void _refresh() {
    if (!mounted) return;
    setState(() {
      _future = _load();
    });
  }

  @override
  Widget build(BuildContext context) => EthanPage(
        title: '后台任务',
        subtitle: 'Agent 异步执行队列',
        actions: [
          IconButton(
              onPressed: _refresh,
              icon: const Icon(Icons.refresh_rounded),
              tooltip: '刷新')
        ],
        child: FutureBuilder<List<BackgroundTaskItem>>(
          future: _future,
          builder: (context, snapshot) => _AsyncList(
            snapshot: snapshot,
            emptyText: '暂无后台任务',
            onRetry: _refresh,
            itemBuilder: (task) => InfoTile(
              icon: _taskIcon(task.status),
              title: task.title,
              subtitle: [
                _taskStatus(task.status),
                if (task.result.isNotEmpty) task.result,
                if (task.error.isNotEmpty) task.error,
                if (task.result.isEmpty && task.error.isEmpty) task.id,
              ].join(' · '),
              subtitleMaxLines: 2,
              trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                if (task.sessionId.isNotEmpty && widget.onOpenSession != null)
                  IconButton(
                    tooltip: '打开关联对话',
                    onPressed: () => widget.onOpenSession!(task.sessionId),
                    icon: const Icon(Icons.chat_bubble_outline_rounded),
                  ),
                if (task.status == 'running')
                  IconButton(
                    tooltip: '停止',
                    onPressed: () async {
                      try {
                        await widget.api!.stopBackgroundTask(task.id);
                        _refresh();
                      } catch (error) {
                        if (mounted)
                          ScaffoldMessenger.of(context).showSnackBar(
                              SnackBar(content: Text('停止失败：$error')));
                      }
                    },
                    icon: const Icon(Icons.stop_circle_outlined),
                  ),
              ]),
            ),
          ),
        ),
      );
}

class SettingsScreen extends StatefulWidget {
  const SettingsScreen(
      {required this.server,
      required this.token,
      required this.api,
      required this.themeMode,
      required this.onTheme,
      super.key});
  final String server;
  final String token;
  final EthanApiService api;
  final ThemeMode themeMode;
  final ValueChanged<ThemeMode> onTheme;
  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen>
    with SingleTickerProviderStateMixin {
  late final server = TextEditingController(text: widget.server);
  // Android treats this field as an optional token replacement.  Never show
  // the existing secret just because the user opened the settings page.
  late final token = TextEditingController();
  bool heartbeat = false;
  bool savingConnection = false;
  bool savingAgent = false;
  bool _showingDetail = false;
  late ThemeMode _themeMode;
  String agentName = '';
  String _profilePreview = '';
  String _providerPreview = '';
  String _channelPreview = '';
  final Map<String, String> _systemPreviews = {};
  String? connectionStatus;
  late final TabController _tabs = TabController(length: 13, vsync: this);

  static const _tabLabels = [
    '连接',
    '偏好',
    '模型服务',
    '消息渠道',
    '助手风格',
    '行为准则',
    '工具使用',
    '自动检查',
    '我的偏好',
    '提示词预览',
    'API 密钥',
    '快速规则',
    '工具路由',
  ];
  @override
  void initState() {
    super.initState();
    _themeMode = widget.themeMode;
    _loadAgent();
  }

  void _selectSettingsTab(int index) {
    // Detail pages are selected by the grouped list, never by swipe. Setting
    // the controller index synchronously avoids an in-flight TabBar animation
    // while the previous detail subtree is being removed.
    _tabs.index = index;
    setState(() => _showingDetail = true);
  }

  void _closeSettingsDetail() {
    FocusManager.instance.primaryFocus?.unfocus();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) setState(() => _showingDetail = false);
    });
  }

  /// Most settings entries expose one editor/dialog. Opening an intermediate
  /// detail shell for those entries produced a duplicate interaction such as
  /// “设置 → 模型服务 → 模型服务”. Keep grouped pages only where they contain
  /// multiple controls (connection and preferences), and open single-purpose
  /// editors directly from the Apple-style settings list.
  Future<void> _openSettingsAction(int index) async {
    switch (index) {
      case 0:
      case 1:
        _selectSettingsTab(index);
      case 2:
        await _showProviders();
      case 3:
        await _editChannels();
      case 4:
        await _editSystemSection('助手风格', 'identity', '身份内容');
      case 5:
        await _editSystemSection('表达偏好', 'soul', '偏好内容');
      case 6:
        await _editSystemSection('工具使用', 'tools', '工具内容');
      case 7:
        await _editSystemSection('自动检查', 'heartbeat', '检查内容');
      case 8:
        await _editProfile();
      case 9:
        await _showPromptPreview();
      case 10:
        await _showApiKeys();
      case 11:
        await _showFastRules();
      case 12:
        await _showToolTiers();
    }
  }

  Widget _settingsHome(BuildContext context) {
    String summary(String key, String fallback) {
      final value = _systemPreviews[key]?.trim() ?? '';
      if (value.isEmpty) return fallback;
      final normalized = value.replaceAll(RegExp(r'\s+'), ' ');
      return normalized.length > 48
          ? '${normalized.substring(0, 48)}…'
          : normalized;
    }

    String profileSummary() {
      final value = _profilePreview.trim();
      if (value.isEmpty) return '称呼、背景与个人信息';
      final normalized = value.replaceAll(RegExp(r'\s+'), ' ');
      return normalized.length > 48
          ? '${normalized.substring(0, 48)}…'
          : normalized;
    }

    final rows = <String, List<Widget>>{
      '连接与账户': [
        SettingsRow(
          icon: Icons.link_rounded,
          title: '连接',
          subtitle: '服务器地址与访问 Token',
          onTap: () => _openSettingsAction(0),
        ),
      ],
      '常用偏好': [
        SettingsRow(
          icon: Icons.tune_rounded,
          title: '偏好',
          subtitle: '助手名称、语言与外观主题',
          onTap: () => _openSettingsAction(1),
        ),
        SettingsRow(
          icon: Icons.badge_outlined,
          title: '我的偏好',
          subtitle: profileSummary(),
          onTap: () => _openSettingsAction(8),
        ),
      ],
      '助手行为': [
        SettingsRow(
          icon: Icons.person_outline_rounded,
          title: '助手风格',
          subtitle: summary('identity', '身份与表达方式'),
          onTap: () => _openSettingsAction(4),
        ),
        SettingsRow(
          icon: Icons.auto_awesome_outlined,
          title: '表达偏好',
          subtitle: summary('soul', '回复风格与行为原则'),
          onTap: () => _openSettingsAction(5),
        ),
        SettingsRow(
          icon: Icons.extension_outlined,
          title: '工具使用',
          subtitle: summary('tools', '工具调用边界与说明'),
          onTap: () => _openSettingsAction(6),
        ),
        SettingsRow(
          icon: Icons.favorite_outline_rounded,
          title: '自动检查',
          subtitle: summary('heartbeat', '周期检查提示与开关'),
          onTap: () => _openSettingsAction(7),
        ),
      ],
      '接入与能力': [
        SettingsRow(
          icon: Icons.cloud_outlined,
          title: '模型服务',
          subtitle: _providerPreview.isEmpty ? '服务商、模型与备用模型' : _providerPreview,
          onTap: () => _openSettingsAction(2),
        ),
        SettingsRow(
          icon: Icons.hub_outlined,
          title: '消息渠道',
          subtitle: _channelPreview.isEmpty ? '飞书、微信及其他消息接入' : _channelPreview,
          onTap: () => _openSettingsAction(3),
        ),
      ],
      '高级': [
        SettingsRow(
          icon: Icons.preview_outlined,
          title: '提示词预览',
          subtitle: '查看服务端最终上下文',
          onTap: () => _openSettingsAction(9),
        ),
        SettingsRow(
          icon: Icons.key_outlined,
          title: 'API 密钥',
          subtitle: '管理服务端访问密钥',
          onTap: () => _openSettingsAction(10),
        ),
        SettingsRow(
          icon: Icons.rule_outlined,
          title: '快速规则',
          subtitle: '行为规则与模型选项',
          onTap: () => _openSettingsAction(11),
        ),
        SettingsRow(
          icon: Icons.account_tree_outlined,
          title: '工具路由',
          subtitle: '查看工具调用路由档位',
          onTap: () => _openSettingsAction(12),
        ),
      ],
    };
    return ListView(
      padding: const EdgeInsets.only(top: 8, bottom: 24),
      children: [
        for (final entry in rows.entries)
          SettingsGroup(title: entry.key, children: entry.value),
      ],
    );
  }

  Future<void> _loadAgent() async {
    try {
      // Settings is an interactive shell; a slow/unreachable server must not
      // make opening the page appear frozen. The individual editor actions
      // still use the normal request timeout and surface their own errors.
      final settings = await widget.api
          .getAgentSettings()
          .timeout(const Duration(seconds: 6));
      if (mounted)
        setState(() {
          heartbeat = settings['heartbeat_enabled'] == true;
          agentName = _text(settings['agent_name']);
        });
    } catch (_) {}
  }

  Future<void> _saveConnection() async {
    final suppliedToken = token.text.trim();
    final next = ApiConfig(
        baseUrl: server.text.trim(),
        token: suppliedToken.isEmpty ? widget.token : suppliedToken);
    setState(() => savingConnection = true);
    final client = EthanApiClient(next);
    var didPop = false;
    try {
      await client.health();
      // An empty field means "keep the current token".  The development
      // token preserves the explicit login flow, but never fakes server data.
      if (suppliedToken.isNotEmpty && suppliedToken != 'mock-token') {
        await client.authenticate();
      }
      // Return the new config to MainShell. The caller applies it only after
      // Navigator.push completes, so the Settings route is fully disposed
      // before its keyed host is rebuilt.
      if (mounted) {
        FocusScope.of(context).unfocus();
        didPop = true;
        Navigator.of(context).pop(next);
      }
    } catch (e) {
      if (mounted) {
        setState(() => connectionStatus = '连接失败');
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('连接失败：$e')));
      }
    } finally {
      client.close();
      if (mounted && !didPop) setState(() => savingConnection = false);
    }
  }

  Future<void> _editAgent() async {
    Map<String, dynamic> settings;
    try {
      settings = await widget.api.getAgentSettings();
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('加载 Agent 设置失败：$error')));
      }
      return;
    }
    final fields = <String, TextEditingController>{
      'agent_name': TextEditingController(text: _text(settings['agent_name'])),
      'default_model':
          TextEditingController(text: _text(settings['default_model'])),
      'lite_model': TextEditingController(text: _text(settings['lite_model'])),
      'language': TextEditingController(
          text: _text(settings['language'], fallback: 'zh')),
      'workspace': TextEditingController(text: _text(settings['workspace'])),
      'proxy': TextEditingController(text: _text(settings['proxy'])),
      'heartbeat_interval_minutes': TextEditingController(
          text: _text(settings['heartbeat_interval_minutes'], fallback: '30')),
      'max_tokens': TextEditingController(
          text: _text(settings['max_tokens'], fallback: '8192')),
      'max_tool_iterations': TextEditingController(
          text: _text(settings['max_tool_iterations'], fallback: '20')),
    };
    var heartbeatEnabled = settings['heartbeat_enabled'] == true;
    final saved = await showDialog<bool>(
        context: context,
        builder: (dialog) => AlertDialog(
              title: const Text('Agent 设置'),
              content: SizedBox(
                width: MediaQuery.sizeOf(context).width >= 600
                    ? 560
                    : double.infinity,
                child: StatefulBuilder(builder: (context, setDialogState) {
                  return SingleChildScrollView(
                    child: Column(mainAxisSize: MainAxisSize.min, children: [
                      _agentField(fields['agent_name']!, 'Agent 名称'),
                      _agentField(fields['default_model']!, '默认模型'),
                      _agentField(fields['lite_model']!, '轻量模型'),
                      _agentField(fields['language']!, '语言 (zh/en)'),
                      _agentField(fields['workspace']!, '工作区'),
                      _agentField(fields['proxy']!, '代理地址'),
                      _agentField(
                          fields['heartbeat_interval_minutes']!, '心跳间隔（分钟）',
                          number: true),
                      _agentField(fields['max_tokens']!, '最大 Tokens',
                          number: true),
                      _agentField(fields['max_tool_iterations']!, '最大工具轮次',
                          number: true),
                      SwitchListTile(
                          contentPadding: EdgeInsets.zero,
                          value: heartbeatEnabled,
                          onChanged: (value) =>
                              setDialogState(() => heartbeatEnabled = value),
                          title: const Text('启用心跳')),
                    ]),
                  );
                }),
              ),
              actions: [
                TextButton(
                    onPressed: () => _popEditorDialog(dialog),
                    child: const Text('取消')),
                FilledButton(
                    onPressed: () => _popEditorDialog(dialog, true),
                    child: const Text('保存'))
              ],
            ));
    if (saved != true) {
      await _disposeDialogControllers(fields.values);
      return;
    }
    if (!mounted) {
      await _disposeDialogControllers(fields.values);
      return;
    }
    setState(() => savingAgent = true);
    try {
      await widget.api.updateAgentSettings({
        'agent_name': fields['agent_name']!.text.trim(),
        'default_model': fields['default_model']!.text.trim(),
        'lite_model': fields['lite_model']!.text.trim(),
        'language': fields['language']!.text.trim(),
        'workspace': fields['workspace']!.text.trim(),
        'proxy': fields['proxy']!.text.trim(),
        'heartbeat_enabled': heartbeatEnabled,
        'heartbeat_interval_minutes':
            int.tryParse(fields['heartbeat_interval_minutes']!.text.trim()) ??
                30,
        'max_tokens': int.tryParse(fields['max_tokens']!.text.trim()) ?? 8192,
        'max_tool_iterations':
            int.tryParse(fields['max_tool_iterations']!.text.trim()) ?? 20,
      });
      if (mounted) {
        setState(() {
          agentName = fields['agent_name']!.text.trim();
          heartbeat = heartbeatEnabled;
        });
      }
    } catch (e) {
      if (mounted)
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('保存失败：$e')));
    } finally {
      await _disposeDialogControllers(fields.values);
      if (mounted) setState(() => savingAgent = false);
    }
  }

  Widget _agentField(TextEditingController controller, String label,
          {bool number = false}) =>
      Padding(
          padding: const EdgeInsets.only(bottom: 10),
          child: TextField(
              controller: controller,
              keyboardType: number ? TextInputType.number : null,
              decoration: InputDecoration(labelText: label)));

  Future<void> _editSystemSection(
      String title, String field, String label) async {
    try {
      final settings = await widget.api.getSystemSettings();
      if (!mounted) return;
      final controller = TextEditingController(text: _text(settings[field]));
      final saved = await showDialog<bool>(
          context: context,
          builder: (dialog) => AlertDialog(
                title: Text(title),
                content: SizedBox(
                    width: MediaQuery.sizeOf(context).width >= 600
                        ? 620
                        : double.infinity,
                    child: TextField(
                        controller: controller,
                        minLines: 10,
                        maxLines: 18,
                        decoration: InputDecoration(labelText: label))),
                actions: [
                  TextButton(
                      onPressed: () => _popEditorDialog(dialog),
                      child: const Text('取消')),
                  FilledButton(
                      onPressed: () async {
                        await widget.api
                            .updateSystemSettings({field: controller.text});
                        if (dialog.mounted) _popEditorDialog(dialog, true);
                      },
                      child: const Text('保存')),
                ],
              ));
      final updated = controller.text.trim();
      await _disposeDialogControllers([controller]);
      if (saved == true && mounted) {
        setState(() => _systemPreviews[field] = updated);
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('$title 已保存')));
      }
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('$title 保存失败：$error')));
      }
    }
  }

  Future<void> _saveHeartbeat(bool value) async {
    setState(() {
      heartbeat = value;
      savingAgent = true;
    });
    try {
      await widget.api.updateAgentSettings({'heartbeat_enabled': value});
    } catch (e) {
      if (mounted) {
        setState(() => heartbeat = !value);
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('保存失败：$e')));
      }
    } finally {
      if (mounted) setState(() => savingAgent = false);
    }
  }

  Future<void> _editBackendJson(
      String title,
      Future<Map<String, dynamic>> Function() load,
      Future<Map<String, dynamic>> Function(Map<String, dynamic>) save) async {
    try {
      final initial = await load();
      if (!mounted) return;
      final controller = TextEditingController(
          text: const JsonEncoder.withIndent('  ').convert(initial));
      final submitted = await showDialog<bool>(
          context: context,
          builder: (dialog) => AlertDialog(
                title: Text(title),
                content: SizedBox(
                    width: MediaQuery.sizeOf(context).width >= 600
                        ? 620
                        : double.infinity,
                    child: TextField(
                        controller: controller,
                        minLines: 10,
                        maxLines: 18,
                        keyboardType: TextInputType.multiline,
                        decoration:
                            const InputDecoration(labelText: '服务端 JSON 配置'))),
                actions: [
                  TextButton(
                      onPressed: () => _popEditorDialog(dialog),
                      child: const Text('取消')),
                  FilledButton(
                      onPressed: () async {
                        try {
                          final value = jsonDecode(controller.text);
                          if (value is! Map)
                            throw const FormatException('配置必须是 JSON 对象');
                          await save(Map<String, dynamic>.from(value));
                          if (dialog.mounted) _popEditorDialog(dialog, true);
                        } catch (e) {
                          if (dialog.mounted) {
                            ScaffoldMessenger.of(dialog).showSnackBar(
                                SnackBar(content: Text('保存失败：$e')));
                          }
                        }
                      },
                      child: const Text('保存')),
                ],
              ));
      await _disposeDialogControllers([controller]);
      if (submitted == true && mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('$title 已保存')));
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('加载失败：$e')));
      }
    }
  }

  Future<void> _showReadOnlyJson(String title, Map<String, dynamic> body) =>
      showModalBottomSheet<void>(
          context: context,
          isScrollControlled: true,
          showDragHandle: true,
          builder: (_) => SafeArea(
              child: SizedBox(
                  height: MediaQuery.sizeOf(context).height * .8,
                  child: SingleChildScrollView(
                      padding: const EdgeInsets.all(20),
                      child: SelectableText(
                          '$title\n\n${const JsonEncoder.withIndent('  ').convert(body)}')))));

  Future<void> _editProfile() async {
    try {
      final profile = await widget.api.getUserProfile();
      if (!mounted) return;
      final controller = TextEditingController(text: _text(profile['content']));
      final saved = await showDialog<bool>(
          context: context,
          builder: (dialog) => AlertDialog(
                title: const Text('用户画像'),
                content: TextField(
                    controller: controller,
                    minLines: 8,
                    maxLines: 16,
                    decoration: const InputDecoration(labelText: '画像内容')),
                actions: [
                  TextButton(
                      onPressed: () => _popEditorDialog(dialog),
                      child: const Text('取消')),
                  FilledButton(
                      onPressed: () async {
                        await widget.api
                            .updateUserProfile({'content': controller.text});
                        if (dialog.mounted) _popEditorDialog(dialog, true);
                      },
                      child: const Text('保存'))
                ],
              ));
      final updated = controller.text.trim();
      await _disposeDialogControllers([controller]);
      if (saved == true && mounted) {
        setState(() => _profilePreview = updated);
        ScaffoldMessenger.of(context)
            .showSnackBar(const SnackBar(content: Text('用户画像已保存')));
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('用户画像失败：$e')));
      }
    }
  }

  Future<void> _editChannels() async {
    try {
      final body = await widget.api.getChannels();
      final channels = _asRows(body['channels']);
      if (!mounted) return;
      var savedChannel = false;
      await showModalBottomSheet<void>(
          context: context,
          showDragHandle: true,
          builder: (sheet) => ListView(
              padding: const EdgeInsets.all(16),
              children: channels
                  .map((channel) => ListTile(
                        title: Text(_text(channel['name'],
                            fallback: _text(channel['id']))),
                        subtitle: Text(_text(channel['id'])),
                        trailing: const Icon(Icons.edit_rounded),
                        onTap: () async {
                          final config = channel['config'] is Map
                              ? Map<String, dynamic>.from(
                                  channel['config'] as Map)
                              : <String, dynamic>{};
                          final editor = TextEditingController(
                              text: const JsonEncoder.withIndent('  ')
                                  .convert(config));
                          final saved = await showDialog<bool>(
                              context: sheet,
                              builder: (dialog) => AlertDialog(
                                    title: Text(_text(channel['name'],
                                        fallback: '渠道配置')),
                                    content: TextField(
                                        controller: editor,
                                        minLines: 8,
                                        maxLines: 16),
                                    actions: [
                                      TextButton(
                                          onPressed: () =>
                                              _popEditorDialog(dialog),
                                          child: const Text('取消')),
                                      FilledButton(
                                          onPressed: () async {
                                            final decoded =
                                                jsonDecode(editor.text);
                                            if (decoded is! Map) {
                                              throw const FormatException(
                                                  '配置必须是 JSON 对象');
                                            }
                                            await widget.api.patchChannel({
                                              'channel_id':
                                                  _text(channel['id']),
                                              'config':
                                                  Map<String, String>.from(
                                                      decoded.map((k, v) =>
                                                          MapEntry('$k', '$v')))
                                            });
                                            savedChannel = true;
                                            if (dialog.mounted)
                                              _popEditorDialog(dialog, true);
                                          },
                                          child: const Text('保存'))
                                    ],
                                  ));
                          await _disposeDialogControllers([editor]);
                          if (saved == true && sheet.mounted)
                            Navigator.pop(sheet);
                        },
                      ))
                  .toList()));
      if (savedChannel && mounted) {
        setState(() => _channelPreview = '配置已保存');
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('渠道失败：$e')));
      }
    }
  }

  Future<void> _validateKnowledge() async {
    var backend = 'filesystem';
    final path = TextEditingController();
    final vault = TextEditingController();
    final folder = TextEditingController(text: '.');
    final endpoint = TextEditingController();
    final apiKey = TextEditingController();
    final result = await showDialog<bool>(
        context: context,
        builder: (dialog) => StatefulBuilder(builder: (context, setState) {
              Widget field(TextEditingController controller, String label,
                      {bool secret = false}) =>
                  TextField(
                      controller: controller,
                      obscureText: secret,
                      decoration: InputDecoration(labelText: label));
              return AlertDialog(
                title: const Text('知识库验证'),
                content: SingleChildScrollView(
                    child: Column(mainAxisSize: MainAxisSize.min, children: [
                  DropdownButtonFormField<String>(
                      value: backend,
                      decoration: const InputDecoration(labelText: '后端'),
                      items: const [
                        DropdownMenuItem(
                            value: 'filesystem', child: Text('filesystem')),
                        DropdownMenuItem(
                            value: 'obsidian', child: Text('obsidian')),
                        DropdownMenuItem(
                            value: 'external', child: Text('external')),
                      ],
                      onChanged: (value) =>
                          setState(() => backend = value ?? 'filesystem')),
                  if (backend == 'filesystem') field(path, '路径（可选）'),
                  if (backend == 'obsidian') ...[
                    field(vault, 'Vault 路径'),
                    field(folder, 'Folder'),
                  ],
                  if (backend == 'external') ...[
                    field(endpoint, 'Endpoint'),
                    field(apiKey, 'API Key', secret: true),
                  ],
                ])),
                actions: [
                  TextButton(
                      onPressed: () => _popEditorDialog(dialog),
                      child: const Text('取消')),
                  FilledButton(
                      onPressed: () async {
                        try {
                          final response =
                              await widget.api.validateKnowledgeBackend({
                            'backend': backend,
                            'obsidian_vault_path': vault.text.trim(),
                            'obsidian_folder': folder.text.trim(),
                            'external_base_url': endpoint.text.trim(),
                            'external_api_key': apiKey.text,
                            'filesystem_path': path.text.trim(),
                          });
                          if (!dialog.mounted) return;
                          await showDialog<void>(
                              context: dialog,
                              builder: (resultDialog) => AlertDialog(
                                    title: Text(response['ok'] == true
                                        ? '连接成功'
                                        : '连接失败'),
                                    content: Text(_text(response['message'],
                                        fallback: '服务端未返回验证结果')),
                                    actions: [
                                      FilledButton(
                                          onPressed: () =>
                                              _popEditorDialog(resultDialog),
                                          child: const Text('关闭'))
                                    ],
                                  ));
                          if (dialog.mounted) _popEditorDialog(dialog, true);
                        } catch (error) {
                          if (dialog.mounted) {
                            ScaffoldMessenger.of(dialog).showSnackBar(
                                SnackBar(content: Text('验证失败：$error')));
                          }
                        }
                      },
                      child: const Text('测试连接')),
                ],
              );
            }));
    await _disposeDialogControllers([path, vault, folder, endpoint, apiKey]);
    if (result == true && mounted) _loadAgent();
  }

  Future<void> _showFastRules() async {
    try {
      final body = await widget.api.getFastRules();
      if (!mounted) return;
      final rules = _asRows(body['fast_rules']);
      final baseTools = body['fast_base_tools'] is List
          ? (body['fast_base_tools'] as List).map((value) => '$value').toList()
          : const <String>[];
      await showModalBottomSheet<void>(
          context: context,
          showDragHandle: true,
          isScrollControlled: true,
          builder: (sheet) => SafeArea(
                child: ListView(
                  padding: const EdgeInsets.all(20),
                  children: [
                    Text('快速规则', style: Theme.of(context).textTheme.titleLarge),
                    const SizedBox(height: 6),
                    Text('${rules.length} 条规则 · ${baseTools.length} 个基础工具',
                        style: Theme.of(context).textTheme.bodySmall),
                    const SizedBox(height: 16),
                    if (baseTools.isNotEmpty)
                      SettingsGroup(title: '基础工具', children: [
                        Padding(
                            padding: const EdgeInsets.all(16),
                            child: Text(baseTools.join(' · ')))
                      ]),
                    ...rules.map((rule) => Card(
                          margin: const EdgeInsets.symmetric(vertical: 4),
                          child: ListTile(
                            title: Text(_text(rule['name'], fallback: '未命名规则')),
                            subtitle: Text([
                              _tags(rule['keywords']),
                              _tags(rule['tools']),
                              _tags(rule['skills']),
                            ].where((value) => value.isNotEmpty).join(' · ')),
                          ),
                        )),
                    OutlinedButton.icon(
                        onPressed: () async {
                          await Navigator.of(sheet).maybePop();
                          await Future<void>.delayed(Duration.zero);
                          if (mounted) {
                            await _editBackendJson(
                                '快速规则',
                                widget.api.getFastRules,
                                widget.api.updateFastRules);
                          }
                        },
                        icon: const Icon(Icons.code_rounded),
                        label: const Text('高级 JSON 编辑')),
                  ],
                ),
              ));
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('加载快速规则失败：$error')));
      }
    }
  }

  Future<void> _showProviders() async {
    try {
      final body = await widget.api.getProviderSettings();
      final providers = body['providers'] is Map
          ? Map<String, dynamic>.from(body['providers'] as Map)
          : body;
      if (!mounted) return;
      final fields = <String, Map<String, TextEditingController>>{};
      for (final entry in providers.entries) {
        final value = entry.value is Map
            ? Map<String, dynamic>.from(entry.value as Map)
            : const <String, dynamic>{};
        fields[entry.key] = {
          'api_key': TextEditingController(text: _text(value['api_key'])),
          'base_url': TextEditingController(text: _text(value['base_url'])),
        };
      }
      final saved = await showDialog<bool>(
          context: context,
          builder: (dialog) => AlertDialog(
                title: const Text('模型服务'),
                content: SizedBox(
                  width: 620,
                  child: SingleChildScrollView(
                    child: Column(
                      children: [
                        for (final entry in fields.entries) ...[
                          Align(
                              alignment: Alignment.centerLeft,
                              child: Padding(
                                  padding: const EdgeInsets.only(bottom: 6),
                                  child: Text(entry.key,
                                      style: Theme.of(context)
                                          .textTheme
                                          .titleSmall))),
                          TextField(
                              controller: entry.value['api_key'],
                              obscureText: true,
                              decoration: const InputDecoration(
                                  labelText: 'API Key',
                                  helperText: '留空则保留当前密钥')),
                          const SizedBox(height: 8),
                          TextField(
                              controller: entry.value['base_url'],
                              decoration: const InputDecoration(
                                  labelText: 'Base URL（可选）')),
                          const SizedBox(height: 16),
                        ],
                        Text('高级字段仍可通过服务端配置管理。',
                            style: Theme.of(context).textTheme.bodySmall),
                      ],
                    ),
                  ),
                ),
                actions: [
                  TextButton(
                      onPressed: () => _popEditorDialog(dialog),
                      child: const Text('取消')),
                  FilledButton(
                      onPressed: () async {
                        try {
                          final payload = <String, dynamic>{};
                          for (final entry in fields.entries) {
                            final apiKey = entry.value['api_key']!.text.trim();
                            final baseUrl =
                                entry.value['base_url']!.text.trim();
                            payload[entry.key] = {
                              if (apiKey.isNotEmpty) 'api_key': apiKey,
                              'base_url': baseUrl,
                            };
                          }
                          await widget.api.updateProviderSettings(payload);
                          if (dialog.mounted) {
                            _popEditorDialog(dialog, true);
                          }
                        } catch (error) {
                          if (dialog.mounted) {
                            ScaffoldMessenger.of(dialog).showSnackBar(
                                SnackBar(content: Text('保存失败：$error')));
                          }
                        }
                      },
                      child: const Text('保存')),
                ],
              ));
      await _disposeDialogControllers(
          fields.values.expand((entry) => entry.values));
      if (saved == true && mounted) {
        setState(() => _providerPreview = '${fields.length} 个服务配置已保存');
        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (mounted) {
            ScaffoldMessenger.of(context)
                .showSnackBar(const SnackBar(content: Text('模型服务已保存')));
          }
        });
      }
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('模型服务保存失败：$error')));
      }
    }
  }

  Future<void> _showPromptPreview() async {
    try {
      final preview = await widget.api.getSystemPromptPreview();
      if (!mounted) return;
      await showModalBottomSheet<void>(
          context: context,
          isScrollControlled: true,
          showDragHandle: true,
          builder: (_) => SafeArea(
              child: SizedBox(
                  height: MediaQuery.sizeOf(context).height * .8,
                  child: SingleChildScrollView(
                      padding: const EdgeInsets.all(20),
                      child: SelectableText(
                          preview['system_prompt']?.toString() ??
                              '服务端未返回 Prompt')))));
    } catch (error) {
      if (mounted)
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('加载 Prompt 失败：$error')));
    }
  }

  Future<void> _showApiKeys() async {
    try {
      final body = await widget.api.getApiKeys();
      final keys = _asRows(body['keys']);
      if (!mounted) return;
      await showModalBottomSheet<void>(
          context: context,
          showDragHandle: true,
          builder: (sheet) => SafeArea(
                  child: ListView(padding: const EdgeInsets.all(16), children: [
                Row(children: [
                  Expanded(
                      child: Text('API Keys',
                          style: Theme.of(context).textTheme.titleLarge)),
                  IconButton(
                      onPressed: () async {
                        await Navigator.of(sheet).maybePop();
                        await Future<void>.delayed(Duration.zero);
                        if (mounted) await _createApiKey();
                      },
                      icon: const Icon(Icons.add_rounded))
                ]),
                ...keys.map((key) => ListTile(
                    title: Text(_text(key['name'], fallback: '未命名 Key')),
                    subtitle: Text(_text(key['key_preview'])),
                    trailing: IconButton(
                        icon: const Icon(Icons.delete_outline),
                        onPressed: () async {
                          final confirmed = await showDialog<bool>(
                              context: sheet,
                              builder: (dialog) => AlertDialog(
                                    title: const Text('删除 API 密钥？'),
                                    content: Text(
                                        '“${_text(key['name'], fallback: '未命名 Key')}”删除后无法恢复。'),
                                    actions: [
                                      TextButton(
                                          onPressed: () =>
                                              Navigator.pop(dialog, false),
                                          child: const Text('取消')),
                                      FilledButton(
                                          style: FilledButton.styleFrom(
                                              backgroundColor: Theme.of(context)
                                                  .colorScheme
                                                  .error),
                                          onPressed: () =>
                                              Navigator.pop(dialog, true),
                                          child: const Text('删除')),
                                    ],
                                  ));
                          if (confirmed != true) return;
                          await widget.api.deleteApiKey(_text(key['id']));
                          if (sheet.mounted) Navigator.pop(sheet);
                        }))),
              ])));
    } catch (error) {
      if (mounted)
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('加载 API Keys 失败：$error')));
    }
  }

  Future<void> _showToolTiers() async {
    try {
      final body = await widget.api.getToolTiers();
      if (!mounted) return;
      await showModalBottomSheet<void>(
          context: context,
          showDragHandle: true,
          isScrollControlled: true,
          builder: (sheet) => SafeArea(
                  child: ListView(padding: const EdgeInsets.all(20), children: [
                Text('工具路由', style: Theme.of(context).textTheme.titleLarge),
                const SizedBox(height: 8),
                Text(
                    'Fast ${_text(body['fast_count'], fallback: '0')} · Full ${_text(body['full_count'], fallback: '0')} · Longtail ${_text(body['longtail_count'], fallback: '0')}',
                    style: Theme.of(context).textTheme.bodySmall),
                const SizedBox(height: 16),
                ..._asRows(body['tiers']).map((tier) => Card(
                      margin: const EdgeInsets.symmetric(vertical: 5),
                      child: ExpansionTile(
                        title: Text(_text(tier['label'], fallback: '未命名档位')),
                        subtitle: Text(_text(tier['desc'])),
                        children: [
                          for (final tool in _asRows(tier['tools']))
                            ListTile(
                              dense: true,
                              title: Text(_text(tool['name'])),
                              subtitle: Text(_text(tool['description'])),
                            ),
                        ],
                      ),
                    )),
                OutlinedButton.icon(
                    onPressed: () async {
                      await Navigator.of(sheet).maybePop();
                      await Future<void>.delayed(Duration.zero);
                      if (mounted) await _showReadOnlyJson('工具路由', body);
                    },
                    icon: const Icon(Icons.code_rounded),
                    label: const Text('查看原始数据')),
              ])));
    } catch (error) {
      if (mounted)
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('加载 Tool Tiers 失败：$error')));
    }
  }

  Future<void> _showLarkDeps() async {
    try {
      var body = await widget.api.getLarkDepsStatus();
      if (!mounted) return;
      final install = await showDialog<bool>(
          context: context,
          builder: (dialog) => AlertDialog(
                title: const Text('Lark 依赖'),
                content: Text(const JsonEncoder.withIndent('  ').convert(body)),
                actions: [
                  TextButton(
                      onPressed: () => Navigator.pop(dialog, false),
                      child: const Text('关闭')),
                  FilledButton(
                      onPressed: () => Navigator.pop(dialog, true),
                      child: const Text('安装/更新'))
                ],
              ));
      if (install == true) {
        body = await widget.api.installLarkDeps();
        if (mounted)
          ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(content: Text('Lark 依赖任务已提交：${_text(body['status'])}')));
      }
    } catch (error) {
      if (mounted)
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('Lark 依赖操作失败：$error')));
    }
  }

  Future<void> _createApiKey() async {
    final name = TextEditingController();
    Map<String, dynamic>? created;
    final saved = await showDialog<bool>(
        context: context,
        builder: (dialog) => AlertDialog(
              title: const Text('新建 API Key'),
              content: TextField(
                  controller: name,
                  decoration: const InputDecoration(labelText: '名称')),
              actions: [
                TextButton(
                    onPressed: () => _popEditorDialog(dialog),
                    child: const Text('取消')),
                FilledButton(
                    onPressed: () async {
                      created = await widget.api
                          .createApiKey({'name': name.text.trim()});
                      if (dialog.mounted) _popEditorDialog(dialog, true);
                    },
                    child: const Text('创建'))
              ],
            ));
    await _disposeDialogControllers([name]);
    if (saved != true || !mounted) return;
    final key = _text(created?['key']);
    if (key.isEmpty) {
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('API Key 已创建')));
      return;
    }
    await showDialog<void>(
        context: context,
        builder: (dialog) => AlertDialog(
              title: const Text('API Key 已创建'),
              content: Column(mainAxisSize: MainAxisSize.min, children: [
                const Text('请立即保存，此密钥不会再次显示：'),
                const SizedBox(height: 10),
                SelectableText(key),
              ]),
              actions: [
                FilledButton(
                    onPressed: () => Navigator.pop(dialog),
                    child: const Text('已保存')),
              ],
            ));
  }

  @override
  void dispose() {
    _tabs.dispose();
    server.dispose();
    token.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => EthanPage(
      title: '设置',
      subtitle: '连接、偏好与工作方式',
      child: _showingDetail
          ? Column(children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(8, 4, 16, 8),
                child: Row(children: [
                  IconButton(
                    tooltip: '返回设置',
                    onPressed: _closeSettingsDetail,
                    icon: const Icon(Icons.chevron_left_rounded),
                  ),
                  const SizedBox(width: 2),
                  Text(_tabLabels[_tabs.index],
                      style: Theme.of(context).textTheme.titleMedium),
                ]),
              ),
              Expanded(
                  // A plain IndexedStack avoids TabBarView's keep-alive and
                  // inherited-dependency teardown race when a settings
                  // detail is closed on iOS.
                  child: IndexedStack(index: _tabs.index, children: [
                ListView(children: [
                  SettingsGroup(title: '连接与账户', children: [
                    SettingsRow(
                      icon: connectionStatus == '连接已验证'
                          ? Icons.check_circle_outline_rounded
                          : Icons.info_outline_rounded,
                      title: connectionStatus ?? '当前连接',
                      subtitle: server.text.isEmpty ? '尚未配置服务器' : server.text,
                      danger: connectionStatus == '连接失败',
                    ),
                    Padding(
                      padding: const EdgeInsets.fromLTRB(16, 14, 16, 6),
                      child: TextField(
                          controller: server,
                          decoration: const InputDecoration(
                              labelText: '服务器地址',
                              hintText: 'http://192.168.1.100:8900',
                              prefixIcon: Icon(Icons.dns_rounded))),
                    ),
                    Padding(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 16, vertical: 6),
                      child: TextField(
                          controller: token,
                          obscureText: true,
                          decoration: const InputDecoration(
                              labelText: 'Access Token',
                              helperText: '留空则保留当前 Token',
                              prefixIcon: Icon(Icons.key_rounded))),
                    ),
                    Padding(
                      padding: const EdgeInsets.fromLTRB(16, 6, 16, 14),
                      child: FilledButton.icon(
                          onPressed: savingConnection ? null : _saveConnection,
                          icon: savingConnection
                              ? const SizedBox(
                                  width: 18,
                                  height: 18,
                                  child:
                                      CircularProgressIndicator(strokeWidth: 2))
                              : const Icon(Icons.link_rounded),
                          label: const Text('测试并保存连接')),
                    ),
                  ]),
                ]),
                ListView(children: [
                  SettingsGroup(title: '常用偏好', children: [
                    SettingsRow(
                        icon: Icons.smart_toy_rounded,
                        title: agentName.isEmpty ? '助手名称与语言' : agentName,
                        subtitle: '名称、语言和默认工作方式',
                        onTap: _editAgent),
                    SettingsRow(
                        icon: Icons.dark_mode_outlined,
                        title: '外观主题',
                        subtitle: switch (_themeMode) {
                          ThemeMode.light => '浅色',
                          ThemeMode.dark => '深色',
                          _ => '跟随系统',
                        },
                        trailing: DropdownButton<ThemeMode>(
                            value: _themeMode,
                            items: const [
                              DropdownMenuItem(
                                  value: ThemeMode.system, child: Text('系统')),
                              DropdownMenuItem(
                                  value: ThemeMode.light, child: Text('浅色')),
                              DropdownMenuItem(
                                  value: ThemeMode.dark, child: Text('深色')),
                            ],
                            onChanged: (mode) {
                              if (mode == null) return;
                              setState(() => _themeMode = mode);
                              widget.onTheme(mode);
                            })),
                  ]),
                ]),
                ListView(children: [
                  SettingsGroup(title: '接入与能力', children: [
                    SettingsRow(
                        icon: Icons.tune_rounded,
                        title: '模型服务',
                        subtitle: '服务商、模型与备用模型',
                        onTap: _showProviders),
                  ]),
                ]),
                ListView(children: [
                  SettingsGroup(title: '接入与能力', children: [
                    SettingsRow(
                        icon: Icons.hub_rounded,
                        title: '消息渠道',
                        subtitle: '飞书、微信及其他消息接入',
                        onTap: _editChannels),
                    SettingsRow(
                        icon: Icons.extension_rounded,
                        title: 'Lark 依赖',
                        subtitle: '查看并更新渠道依赖',
                        onTap: _showLarkDeps),
                    SettingsRow(
                        icon: Icons.storage_rounded,
                        title: '知识库连通性',
                        subtitle: '测试 filesystem、Obsidian 或外部知识库',
                        onTap: _validateKnowledge),
                  ]),
                ]),
                ListView(children: [
                  SettingsGroup(title: '助手行为', children: [
                    SettingsRow(
                        icon: Icons.person_rounded,
                        title: '助手风格',
                        subtitle: '编辑身份与表达方式（identity.md）',
                        onTap: () =>
                            _editSystemSection('助手风格', 'identity', '身份内容'))
                  ]),
                ]),
                ListView(children: [
                  SettingsGroup(title: '助手行为', children: [
                    SettingsRow(
                        icon: Icons.auto_awesome_rounded,
                        title: '表达偏好',
                        subtitle: '编辑回复风格与行为原则（soul.md）',
                        onTap: () => _editSystemSection('表达偏好', 'soul', '偏好内容'))
                  ]),
                ]),
                ListView(children: [
                  SettingsGroup(title: '助手行为', children: [
                    SettingsRow(
                        icon: Icons.extension_rounded,
                        title: '工具使用',
                        subtitle: '设置工具调用边界与说明（tools.md）',
                        onTap: () =>
                            _editSystemSection('工具使用', 'tools', '工具内容'))
                  ]),
                ]),
                ListView(children: [
                  SettingsGroup(title: '助手行为', children: [
                    SettingsRow(
                        icon: Icons.favorite_outline_rounded,
                        title: '自动检查',
                        subtitle: '编辑周期检查提示并控制开关（heartbeat.md）',
                        onTap: () =>
                            _editSystemSection('自动检查', 'heartbeat', '检查内容')),
                    SwitchListTile(
                        value: heartbeat,
                        onChanged: savingAgent ? null : _saveHeartbeat,
                        title: const Text('启用自动检查'),
                        subtitle: const Text('让 Ethan 定期检查待办事项'))
                  ]),
                ]),
                ListView(children: [
                  SettingsGroup(title: '常用偏好', children: [
                    SettingsRow(
                        icon: Icons.badge_rounded,
                        title: '我的偏好',
                        subtitle: '编辑 Ethan 对你的称呼与背景信息',
                        onTap: _editProfile)
                  ]),
                ]),
                ListView(children: [
                  SettingsGroup(title: '高级', children: [
                    SettingsRow(
                        icon: Icons.preview_rounded,
                        title: '提示词预览',
                        subtitle: '查看服务端最终上下文（只读）',
                        onTap: _showPromptPreview)
                  ]),
                ]),
                ListView(children: [
                  SettingsGroup(title: '高级', children: [
                    SettingsRow(
                        icon: Icons.vpn_key_rounded,
                        title: 'API 密钥',
                        subtitle: '管理服务端访问密钥',
                        onTap: _showApiKeys)
                  ]),
                ]),
                ListView(children: [
                  SettingsGroup(title: '高级', children: [
                    SettingsRow(
                        icon: Icons.rule_rounded,
                        title: '快速规则',
                        subtitle: '快速行为规则与模型选项',
                        onTap: _showFastRules)
                  ]),
                ]),
                ListView(children: [
                  SettingsGroup(title: '高级', children: [
                    SettingsRow(
                        icon: Icons.account_tree_rounded,
                        title: '工具路由',
                        subtitle: '查看工具调用的路由档位',
                        onTap: _showToolTiers)
                  ]),
                ]),
              ])),
            ])
          : _settingsHome(context));
}

class _ResourceMeta {
  const _ResourceMeta(this.title, this.subtitle, this.icon);
  final String title, subtitle;
  final IconData icon;
}

_ResourceMeta _resourceMeta(String kind) => switch (kind) {
      'memory' =>
        const _ResourceMeta('记忆', '长期事实与流程', Icons.psychology_rounded),
      'knowledge' =>
        const _ResourceMeta('知识库', '服务器已索引的知识文档', Icons.menu_book_rounded),
      'skills' =>
        const _ResourceMeta('技能', '服务器注册的 Agent 技能', Icons.extension_rounded),
      'docs' =>
        const _ResourceMeta('文档', 'Ethan 使用指南', Icons.auto_stories_rounded),
      'logs' => const _ResourceMeta('日志', '后端最近日志', Icons.receipt_long_rounded),
      _ => const _ResourceMeta('资源', '', Icons.folder_outlined),
    };

class _AsyncList<T> extends StatelessWidget {
  const _AsyncList(
      {required this.snapshot,
      required this.emptyText,
      required this.onRetry,
      required this.itemBuilder});
  final AsyncSnapshot<List<T>> snapshot;
  final String emptyText;
  final VoidCallback onRetry;
  final Widget Function(T item) itemBuilder;
  @override
  Widget build(BuildContext context) {
    if (snapshot.connectionState == ConnectionState.waiting) {
      return const Center(child: CircularProgressIndicator());
    }
    if (snapshot.hasError) {
      return Center(
          child: Padding(
              padding: const EdgeInsets.all(24),
              child: Column(mainAxisSize: MainAxisSize.min, children: [
                const Icon(Icons.cloud_off_rounded, size: 40),
                const SizedBox(height: 12),
                Text('加载失败：${snapshot.error}', textAlign: TextAlign.center),
                const SizedBox(height: 12),
                OutlinedButton.icon(
                    onPressed: onRetry,
                    icon: const Icon(Icons.refresh_rounded),
                    label: const Text('重试'))
              ])));
    }
    final items = snapshot.data ?? const [];
    if (items.isEmpty) return Center(child: Text(emptyText));
    return RefreshIndicator(
        onRefresh: () async => onRetry(),
        child: ListView(children: items.map(itemBuilder).toList()));
  }
}

String _agendaStatus(AgendaItem item) => [
      item.status,
      item.completion,
      item.repeat == 'none' ? '' : item.repeat
    ].where((value) => value.isNotEmpty).join(' · ');

Widget _errorView(Object? error, VoidCallback retry) => Center(
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        Text('加载失败：$error'),
        const SizedBox(height: 8),
        OutlinedButton(onPressed: retry, child: const Text('重试'))
      ]),
    );
String _taskStatus(String status) => switch (status) {
      'running' => '运行中',
      'done' => '已完成',
      'failed' => '失败',
      'cancelled' => '已取消',
      _ => status.isEmpty ? '等待中' : status
    };
IconData _taskIcon(String status) => switch (status) {
      'running' => Icons.autorenew_rounded,
      'done' => Icons.check_circle_rounded,
      'failed' => Icons.error_outline_rounded,
      _ => Icons.pause_circle_outline_rounded
    };

List<Map<String, dynamic>> _asRows(dynamic value) => value is List
    ? value
        .whereType<Map>()
        .map((row) => Map<String, dynamic>.from(row))
        .toList()
    : const [];
String _text(dynamic value, {String fallback = ''}) {
  final text = value?.toString() ?? '';
  return text.isEmpty ? fallback : text;
}

num? _number(dynamic value) =>
    value is num ? value : num.tryParse(value?.toString() ?? '');

String _tags(dynamic value) =>
    value is List ? value.map((item) => '$item').join(' · ') : _text(value);
