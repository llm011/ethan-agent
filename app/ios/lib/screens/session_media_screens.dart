import 'package:flutter/material.dart';
import 'package:video_player/video_player.dart';

import '../data/api_client.dart';
import '../models/app_models.dart';
import '../services/api_service.dart';
import '../widgets/common.dart';

class AnnotationsScreen extends StatefulWidget {
  const AnnotationsScreen({
    required this.api,
    required this.messageIds,
    super.key,
  });

  final EthanApiService api;
  final List<int> messageIds;

  @override
  State<AnnotationsScreen> createState() => _AnnotationsScreenState();
}

class _AnnotationsScreenState extends State<AnnotationsScreen> {
  late Future<Map<int, List<AnnotationItem>>> _future;

  @override
  void initState() {
    super.initState();
    _future = _load();
  }

  Future<Map<int, List<AnnotationItem>>> _load() async {
    final ids = widget.messageIds.toSet().toList()..sort();
    if (ids.isEmpty) return const {};
    final body = await widget.api.batchGetAnnotations(ids.join(','));
    return body.map((rawId, rawItems) {
      final messageId = int.tryParse(rawId) ?? -1;
      final items = rawItems is List
          ? rawItems.whereType<Map>().map((value) {
              final item = Map<String, dynamic>.from(value);
              return AnnotationItem(
                id: _number(item['id']),
                messageId: messageId,
                type: _text(item['type'], fallback: 'highlight'),
                color:
                    _text(item['color']).isEmpty ? null : _text(item['color']),
                start: _number(item['start']),
                end: _number(item['end']),
                quote:
                    _text(item['quote']).isEmpty ? null : _text(item['quote']),
                note: _text(item['note']).isEmpty ? null : _text(item['note']),
              );
            }).toList()
          : const <AnnotationItem>[];
      return MapEntry(messageId, items);
    });
  }

  void _refresh() {
    if (!mounted) return;
    setState(() {
      _future = _load();
    });
  }

  Future<void> _delete(AnnotationItem item) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialog) => AlertDialog(
        title: const Text('删除标注？'),
        content: const Text('删除后无法恢复。'),
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
      await widget.api.deleteAnnotation(item.id);
      _refresh();
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('删除失败：$error')));
      }
    }
  }

  @override
  Widget build(BuildContext context) => EthanPage(
        title: '标注',
        subtitle: '当前会话的消息标注',
        actions: [
          IconButton(
              onPressed: _refresh,
              tooltip: '刷新',
              icon: const Icon(Icons.refresh_rounded)),
        ],
        child: FutureBuilder<Map<int, List<AnnotationItem>>>(
          future: _future,
          builder: (context, snapshot) {
            if (snapshot.connectionState != ConnectionState.done) {
              return const Center(child: CircularProgressIndicator());
            }
            if (snapshot.hasError) {
              return EmptyHint(
                  icon: Icons.cloud_off_rounded,
                  text: '加载标注失败：${snapshot.error}',
                  actionLabel: '重试',
                  onAction: _refresh);
            }
            final grouped =
                snapshot.data ?? const <int, List<AnnotationItem>>{};
            final count =
                grouped.values.fold<int>(0, (sum, list) => sum + list.length);
            if (count == 0) {
              return const EmptyHint(
                  icon: Icons.format_quote_rounded, text: '当前会话暂无标注');
            }
            return RefreshIndicator(
              onRefresh: () async => _refresh(),
              child: ListView(
                padding: const EdgeInsets.only(bottom: 16),
                children: [
                  for (final entry in grouped.entries)
                    if (entry.value.isNotEmpty) ...[
                      SectionLabel('消息 #${entry.key}'),
                      ...entry.value.map((item) => _AnnotationCard(
                            item: item,
                            onDelete: () => _delete(item),
                          )),
                    ],
                ],
              ),
            );
          },
        ),
      );
}

class _AnnotationCard extends StatelessWidget {
  const _AnnotationCard({required this.item, required this.onDelete});
  final AnnotationItem item;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) => Card(
        margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 5),
        child: ListTile(
          leading:
              Icon(Icons.format_quote_rounded, color: _annotationColor(item)),
          title: Text(
              item.quote?.isNotEmpty == true
                  ? item.quote!
                  : '消息范围 ${item.start}–${item.end}',
              maxLines: 3,
              overflow: TextOverflow.ellipsis),
          subtitle: item.note?.isNotEmpty == true
              ? Text(item.note!, maxLines: 2, overflow: TextOverflow.ellipsis)
              : Text(_annotationLabel(item.type)),
          trailing: IconButton(
              tooltip: '删除标注',
              onPressed: onDelete,
              icon: const Icon(Icons.delete_outline_rounded)),
        ),
      );
}

class PptPreviewScreen extends StatefulWidget {
  const PptPreviewScreen(
      {required this.api, required this.sessionId, this.deckPath, super.key});
  final EthanApiService api;
  final String sessionId;
  final String? deckPath;

  @override
  State<PptPreviewScreen> createState() => _PptPreviewScreenState();
}

class _PptPreviewScreenState extends State<PptPreviewScreen> {
  late Future<_DeckData> _future;
  final PageController _pager = PageController();
  var _page = 0;

  @override
  void initState() {
    super.initState();
    _future = _load();
  }

  @override
  void dispose() {
    _pager.dispose();
    super.dispose();
  }

  Future<_DeckData> _load() async {
    final path = widget.deckPath;
    if (path == null || path.trim().isEmpty) {
      throw const FormatException('当前会话没有可预览的 PPT 交付文件');
    }
    final body = await widget.api.getDeck(path, sessionId: widget.sessionId);
    final pages = body['pages'] is List
        ? (body['pages'] as List).whereType<Map>().toList()
        : const <Map>[];
    return _DeckData(
      name: _text(body['name'], fallback: 'PPT 预览'),
      slides: pages.asMap().entries.map((entry) {
        final page = Map<String, dynamic>.from(entry.value);
        return DeckSlide(
          index: entry.key,
          title: _text(page['title'], fallback: '第 ${entry.key + 1} 页'),
          content: _text(page['content']),
        );
      }).toList(),
    );
  }

  void _refresh() {
    if (!mounted) return;
    setState(() {
      _future = _load();
    });
  }

  @override
  Widget build(BuildContext context) => FutureBuilder<_DeckData>(
        future: _future,
        builder: (context, snapshot) {
          final data = snapshot.data;
          return EthanPage(
            title: data?.name ?? 'PPT 预览',
            subtitle:
                data == null ? '正在读取会话交付的文件' : '共 ${data.slides.length} 页',
            actions: [
              IconButton(
                  onPressed: _refresh,
                  tooltip: '刷新',
                  icon: const Icon(Icons.refresh_rounded)),
            ],
            child: snapshot.connectionState != ConnectionState.done
                ? const Center(child: CircularProgressIndicator())
                : snapshot.hasError
                    ? EmptyHint(
                        icon: Icons.slideshow_rounded,
                        text: '加载 PPT 失败：${snapshot.error}',
                        actionLabel: '重试',
                        onAction: _refresh)
                    : data!.slides.isEmpty
                        ? const EmptyHint(
                            icon: Icons.slideshow_rounded,
                            text: '当前会话暂无 PPT 页面')
                        : Column(children: [
                            Expanded(
                              child: PageView.builder(
                                controller: _pager,
                                itemCount: data.slides.length,
                                onPageChanged: (index) =>
                                    setState(() => _page = index),
                                itemBuilder: (_, index) {
                                  final slide = data.slides[index];
                                  return SingleChildScrollView(
                                    padding: const EdgeInsets.all(20),
                                    child: Card(
                                      child: Padding(
                                        padding: const EdgeInsets.all(20),
                                        child: Column(
                                          crossAxisAlignment:
                                              CrossAxisAlignment.start,
                                          children: [
                                            Text(slide.title,
                                                style: Theme.of(context)
                                                    .textTheme
                                                    .headlineSmall
                                                    ?.copyWith(
                                                        fontWeight:
                                                            FontWeight.w800)),
                                            if (slide.content.isNotEmpty) ...[
                                              const SizedBox(height: 16),
                                              SelectableText(slide.content),
                                            ],
                                          ],
                                        ),
                                      ),
                                    ),
                                  );
                                },
                              ),
                            ),
                            Padding(
                              padding: const EdgeInsets.fromLTRB(16, 4, 16, 12),
                              child: Row(
                                mainAxisAlignment:
                                    MainAxisAlignment.spaceBetween,
                                children: [
                                  IconButton(
                                    tooltip: '上一页',
                                    onPressed: _page == 0
                                        ? null
                                        : () => _pager.animateToPage(_page - 1,
                                            duration: const Duration(
                                                milliseconds: 180),
                                            curve: Curves.easeOut),
                                    icon: const Icon(Icons.arrow_back_rounded),
                                  ),
                                  Text('${_page + 1} / ${data.slides.length}'),
                                  IconButton(
                                    tooltip: '下一页',
                                    onPressed: _page >= data.slides.length - 1
                                        ? null
                                        : () => _pager.animateToPage(_page + 1,
                                            duration: const Duration(
                                                milliseconds: 180),
                                            curve: Curves.easeOut),
                                    icon:
                                        const Icon(Icons.arrow_forward_rounded),
                                  ),
                                ],
                              ),
                            ),
                          ]),
          );
        },
      );
}

class VideoPreviewScreen extends StatefulWidget {
  const VideoPreviewScreen({
    required this.api,
    required this.sessionId,
    required this.path,
    this.title = '视频',
    super.key,
  });

  final EthanApiClient api;
  final String sessionId;
  final String path;
  final String title;

  @override
  State<VideoPreviewScreen> createState() => _VideoPreviewScreenState();
}

class _VideoPreviewScreenState extends State<VideoPreviewScreen> {
  VideoPlayerController? _controller;
  Object? _error;

  @override
  void initState() {
    super.initState();
    _init();
  }

  Future<void> _init() async {
    try {
      final uri = widget.api.mediaUri(widget.path, sessionId: widget.sessionId);
      final controller = VideoPlayerController.networkUrl(uri,
          httpHeaders: widget.api.headersFor(uri));
      await controller.initialize();
      if (!mounted) {
        await controller.dispose();
        return;
      }
      setState(() => _controller = controller);
    } catch (error) {
      if (mounted) setState(() => _error = error);
    }
  }

  @override
  void dispose() {
    _controller?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final controller = _controller;
    return Scaffold(
      appBar: AppBar(title: Text(widget.title)),
      body: Center(
        child: _error != null
            ? Text('视频加载失败：$_error')
            : controller == null
                ? const CircularProgressIndicator()
                : Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      AspectRatio(
                          aspectRatio: controller.value.aspectRatio,
                          child: VideoPlayer(controller)),
                      const SizedBox(height: 12),
                      IconButton.filled(
                        tooltip: controller.value.isPlaying ? '暂停' : '播放',
                        onPressed: () {
                          setState(() {
                            controller.value.isPlaying
                                ? controller.pause()
                                : controller.play();
                          });
                        },
                        icon: Icon(controller.value.isPlaying
                            ? Icons.pause
                            : Icons.play_arrow),
                      ),
                    ],
                  ),
      ),
    );
  }
}

class _DeckData {
  const _DeckData({required this.name, required this.slides});
  final String name;
  final List<DeckSlide> slides;
}

int _number(dynamic value) =>
    value is num ? value.toInt() : int.tryParse('$value') ?? 0;
String _text(dynamic value, {String fallback = ''}) {
  final text = value?.toString() ?? '';
  return text.isEmpty ? fallback : text;
}

String _annotationLabel(String type) => switch (type) {
      'underline' => '下划线',
      'strike' => '删除线',
      'comment' => '批注',
      _ => '高亮',
    };

Color _annotationColor(AnnotationItem item) =>
    switch (item.color ?? item.type) {
      'blue' || 'underline' => Colors.blue,
      'green' || 'comment' => Colors.green,
      'pink' || 'strike' => Colors.pink,
      _ => Colors.amber.shade700,
    };
