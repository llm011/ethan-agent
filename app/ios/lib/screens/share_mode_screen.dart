import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';

import '../models/app_models.dart';

enum _ShareWidthPreset {
  compact('紧凑', 14.0),
  standard('标准', 18.0),
  wide('宽', 22.0);

  const _ShareWidthPreset(this.label, this.hPadding);
  final String label;
  final double hPadding;
}

class ShareModeScreen extends StatefulWidget {
  const ShareModeScreen({
    super.key,
    required this.messages,
    required this.defaultSelectedIndex,
  });

  final List<ChatMessage> messages;
  final int defaultSelectedIndex;

  @override
  State<ShareModeScreen> createState() => _ShareModeScreenState();
}

class _ShareModeScreenState extends State<ShareModeScreen> {
  static const _channel = MethodChannel('com.ethan.agent/share');

  late final List<int> _validIndices;
  late Set<int> _selectedIndices;
  final Map<int, String> _editedContents = {};
  int? _editingIndex;

  bool _includeMeta = true;
  bool _includeStats = true;
  bool _includeCards = true;
  bool _cardsOnly = false;
  _ShareWidthPreset _widthPreset = _ShareWidthPreset.standard;
  bool _showSelector = false;
  bool _exporting = false;

  final GlobalKey _repaintKey = GlobalKey();

  @override
  void initState() {
    super.initState();
    _validIndices = [
      for (var i = 0; i < widget.messages.length; i++)
        if (!widget.messages[i].isStreaming &&
            (widget.messages[i].text.trim().isNotEmpty ||
                widget.messages[i].cards.isNotEmpty))
          i,
    ];
    if (_validIndices.contains(widget.defaultSelectedIndex)) {
      _selectedIndices = {widget.defaultSelectedIndex};
    } else if (_validIndices.isNotEmpty) {
      _selectedIndices = {_validIndices.last};
    } else {
      _selectedIndices = {};
    }
  }

  List<MapEntry<int, ChatMessage>> get _selectedMessages => [
        for (final idx in _validIndices)
          if (_selectedIndices.contains(idx))
            MapEntry(idx, widget.messages[idx]),
      ];

  bool get _hasCards =>
      _selectedMessages.any((entry) => entry.value.cards.isNotEmpty);

  String _formatDuration(int ms) {
    if (ms < 1000) return '${ms}ms';
    if (ms < 60000) return '${(ms / 1000).toStringAsFixed(1)}s';
    return '${ms ~/ 60000}m${(ms % 60000) ~/ 1000}s';
  }

  String _snippet(String text, {int maxLen = 50}) {
    final oneLine = text.replaceAll(RegExp(r'\s+'), ' ').trim();
    if (oneLine.length <= maxLen) return oneLine;
    return '${oneLine.substring(0, maxLen)}…';
  }

  Future<Uint8List?> _capturePng() async {
    final boundary =
        _repaintKey.currentContext?.findRenderObject() as RenderRepaintBoundary?;
    if (boundary == null) return null;
    final image = await boundary.toImage(pixelRatio: 2.5);
    final byteData = await image.toByteData(format: ui.ImageByteFormat.png);
    return byteData?.buffer.asUint8List();
  }

  Future<void> _handleShare() async {
    if (_selectedMessages.isEmpty || _exporting) return;
    if (_editingIndex != null) {
      setState(() => _editingIndex = null);
      await Future<void>.delayed(const Duration(milliseconds: 50));
    }
    setState(() => _exporting = true);
    try {
      final bytes = await _capturePng();
      if (bytes == null) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('生成分享图片失败')),
          );
        }
        return;
      }
      await _channel.invokeMethod('shareImage', {'bytes': bytes});
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('分享失败: $e')),
        );
      }
    } finally {
      if (mounted) setState(() => _exporting = false);
    }
  }

  Future<void> _handleSave() async {
    if (_selectedMessages.isEmpty || _exporting) return;
    if (_editingIndex != null) {
      setState(() => _editingIndex = null);
      await Future<void>.delayed(const Duration(milliseconds: 50));
    }
    setState(() => _exporting = true);
    try {
      final bytes = await _capturePng();
      if (bytes == null) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('生成图片失败')),
          );
        }
        return;
      }
      await _channel.invokeMethod('saveImageToPhotos', {'bytes': bytes});
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('已保存到相册')),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('保存失败: $e')),
        );
      }
    } finally {
      if (mounted) setState(() => _exporting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final selected = _selectedMessages;
    final hasCards = _hasCards;
    if (!hasCards && _cardsOnly) {
      _cardsOnly = false;
    }

    final now = DateTime.now();
    final nowStr =
        '${now.year}-${now.month.toString().padLeft(2, '0')}-${now.day.toString().padLeft(2, '0')} '
        '${now.hour.toString().padLeft(2, '0')}:${now.minute.toString().padLeft(2, '0')}';

    return Scaffold(
      appBar: AppBar(
        title: const Text('分享对话'),
        actions: [
          TextButton.icon(
            onPressed: () => setState(() => _showSelector = !_showSelector),
            icon: Icon(
              _showSelector ? Icons.expand_less : Icons.expand_more,
              size: 18,
            ),
            label: Text('已选 ${_selectedIndices.length}/${_validIndices.length}'),
          ),
        ],
      ),
      body: Column(
        children: [
          if (_showSelector)
            Container(
              color: Theme.of(context).colorScheme.surfaceContainerHighest.withValues(alpha: 0.4),
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text(
                        '选择要分享的消息',
                        style: Theme.of(context).textTheme.labelMedium,
                      ),
                      Row(
                        children: [
                          TextButton(
                            onPressed: () => setState(
                              () => _selectedIndices = _validIndices.toSet(),
                            ),
                            child: const Text('全选'),
                          ),
                          TextButton(
                            onPressed: () => setState(
                              () => _selectedIndices = {},
                            ),
                            child: const Text('清空'),
                          ),
                        ],
                      ),
                    ],
                  ),
                  SizedBox(
                    height: 170,
                    child: ListView.builder(
                      itemCount: _validIndices.length,
                      itemBuilder: (context, pos) {
                        final idx = _validIndices[pos];
                        final msg = widget.messages[idx];
                        final checked = _selectedIndices.contains(idx);
                        final text = _editedContents[idx] ?? msg.text;
                        return CheckboxListTile(
                          dense: true,
                          contentPadding: EdgeInsets.zero,
                          controlAffinity: ListTileControlAffinity.leading,
                          value: checked,
                          onChanged: (v) {
                            setState(() {
                              if (v == true) {
                                _selectedIndices.add(idx);
                              } else {
                                _selectedIndices.remove(idx);
                              }
                            });
                          },
                          title: Row(
                            children: [
                              SizedBox(
                                width: 44,
                                child: Text(
                                  msg.isUser ? '你' : 'Ethan',
                                  style: TextStyle(
                                    fontSize: 12,
                                    fontWeight: FontWeight.w600,
                                    color: msg.isUser
                                        ? const Color(0xFF0969DA)
                                        : Theme.of(context).colorScheme.onSurface,
                                  ),
                                ),
                              ),
                              Expanded(
                                child: Text(
                                  _snippet(text),
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: const TextStyle(fontSize: 13),
                                ),
                              ),
                            ],
                          ),
                        );
                      },
                    ),
                  ),
                ],
              ),
            ),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
            child: Row(
              children: [
                FilterChip(
                  label: const Text('角色与时间'),
                  selected: _includeMeta,
                  onSelected: (v) => setState(() => _includeMeta = v),
                ),
                const SizedBox(width: 8),
                FilterChip(
                  label: const Text('统计信息'),
                  selected: _includeStats,
                  onSelected: (v) => setState(() => _includeStats = v),
                ),
                if (hasCards) ...[
                  const SizedBox(width: 8),
                  FilterChip(
                    label: const Text('附件卡片'),
                    selected: _includeCards,
                    onSelected: (v) => setState(() => _includeCards = v),
                  ),
                  const SizedBox(width: 8),
                  FilterChip(
                    label: const Text('仅导出卡片'),
                    selected: _cardsOnly,
                    onSelected: (v) => setState(() => _cardsOnly = v),
                  ),
                ],
                for (final preset in _ShareWidthPreset.values) ...[
                  const SizedBox(width: 8),
                  FilterChip(
                    label: Text(preset.label),
                    selected: _widthPreset == preset,
                    onSelected: (_) => setState(() => _widthPreset = preset),
                  ),
                ],
              ],
            ),
          ),
          Expanded(
            child: Container(
              width: double.infinity,
              color: const Color(0xFFF3F4F6),
              child: selected.isEmpty
                  ? const Center(
                      child: Text(
                        '请至少选择一条消息',
                        style: TextStyle(color: Color(0xFF6B7280)),
                      ),
                    )
                  : SingleChildScrollView(
                      padding: const EdgeInsets.all(16),
                      child: RepaintBoundary(
                        key: _repaintKey,
                        child: Container(
                          width: double.infinity,
                          decoration: BoxDecoration(
                            color: Colors.white,
                            borderRadius: BorderRadius.circular(14),
                            border: Border.all(color: const Color(0xFFE5E7EB)),
                          ),
                          padding: EdgeInsets.symmetric(
                            horizontal: _widthPreset.hPadding,
                            vertical: 20,
                          ),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              for (var pos = 0; pos < selected.length; pos++) ...[
                                _buildMessageItem(
                                  selected[pos].key,
                                  selected[pos].value,
                                ),
                                if (pos < selected.length - 1)
                                  const Padding(
                                    padding: EdgeInsets.symmetric(vertical: 14),
                                    child: Divider(
                                      height: 1,
                                      color: Color(0xFFEAEEF2),
                                    ),
                                  ),
                              ],
                              const SizedBox(height: 16),
                              const Divider(height: 1, color: Color(0xFFEAEEF2)),
                              const SizedBox(height: 12),
                              Row(
                                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                                children: [
                                  const Text(
                                    'Ethan',
                                    style: TextStyle(
                                      fontSize: 15,
                                      fontWeight: FontWeight.w700,
                                      color: Color(0xFF1F2328),
                                    ),
                                  ),
                                  Text(
                                    nowStr,
                                    style: const TextStyle(
                                      fontSize: 11,
                                      color: Color(0xFF8B949E),
                                    ),
                                  ),
                                ],
                              ),
                            ],
                          ),
                        ),
                      ),
                    ),
            ),
          ),
          const Divider(height: 1),
          SafeArea(
            top: false,
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
              child: Row(
                children: [
                  Expanded(
                    child: OutlinedButton.icon(
                      onPressed: selected.isEmpty || _exporting ? null : _handleSave,
                      icon: const Icon(Icons.download_outlined, size: 18),
                      label: const Text('保存图片'),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: FilledButton.icon(
                      onPressed: selected.isEmpty || _exporting ? null : _handleShare,
                      icon: _exporting
                          ? const SizedBox(
                              width: 16,
                              height: 16,
                              child: CircularProgressIndicator(
                                strokeWidth: 2,
                                color: Colors.white,
                              ),
                            )
                          : const Icon(Icons.share_outlined, size: 18),
                      label: const Text('分享图片'),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildMessageItem(int idx, ChatMessage msg) {
    final displayContent = _editedContents[idx] ?? msg.text;
    final isEditing = _editingIndex == idx;

    final statChips = <String>[];
    if (_includeStats && !msg.isUser && !_cardsOnly) {
      if (msg.usage?.model != null && msg.usage!.model!.isNotEmpty) {
        statChips.add(msg.usage!.model!);
      }
      final totalTokens =
          (msg.usage?.inputTokens ?? 0) + (msg.usage?.outputTokens ?? 0);
      if (totalTokens > 0) statChips.add('$totalTokens tokens');
      if (msg.ttfbMs != null) {
        statChips.add('首字 ${_formatDuration(msg.ttfbMs!)}');
      }
      if (msg.totalDurationMs != null) {
        statChips.add('总计 ${_formatDuration(msg.totalDurationMs!)}');
      }
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (_includeMeta || !_cardsOnly)
          Row(
            children: [
              if (_includeMeta) ...[
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                  decoration: BoxDecoration(
                    color: msg.isUser
                        ? const Color(0xFFDDF4FF)
                        : const Color(0xFFEAEEF2),
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text(
                    msg.isUser ? '你' : 'Ethan',
                    style: TextStyle(
                      fontSize: 11,
                      fontWeight: FontWeight.w600,
                      color: msg.isUser
                          ? const Color(0xFF0969DA)
                          : const Color(0xFF1F2328),
                    ),
                  ),
                ),
                if (msg.time.isNotEmpty) ...[
                  const SizedBox(width: 8),
                  Text(
                    msg.time,
                    style: const TextStyle(
                      fontSize: 11,
                      color: Color(0xFF8B949E),
                    ),
                  ),
                ],
              ],
              const Spacer(),
              if (!_cardsOnly)
                InkWell(
                  onTap: () => setState(
                    () => _editingIndex = isEditing ? null : idx,
                  ),
                  borderRadius: BorderRadius.circular(12),
                  child: Padding(
                    padding: const EdgeInsets.all(4),
                    child: Icon(
                      isEditing ? Icons.check : Icons.edit_outlined,
                      size: 15,
                      color: const Color(0xFF6B7280),
                    ),
                  ),
                ),
            ],
          ),
        if (!_cardsOnly) ...[
          const SizedBox(height: 6),
          if (isEditing)
            TextFormField(
              initialValue: displayContent,
              maxLines: null,
              onChanged: (v) => _editedContents[idx] = v,
              decoration: const InputDecoration(
                border: OutlineInputBorder(),
                isDense: true,
              ),
              style: const TextStyle(fontSize: 14, height: 1.5),
            )
          else if (displayContent.isNotEmpty)
            Text(
              displayContent,
              style: const TextStyle(
                fontSize: 14,
                height: 1.6,
                color: Color(0xFF1F2328),
              ),
            ),
        ],
        if (_includeCards && msg.cards.isNotEmpty) ...[
          const SizedBox(height: 8),
          for (final card in msg.cards)
            Container(
              width: double.infinity,
              margin: const EdgeInsets.only(bottom: 4),
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
              decoration: BoxDecoration(
                color: const Color(0xFFF6F8FA),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: const Color(0xFFE5E7EB)),
              ),
              child: Text(
                card.name.isNotEmpty ? card.name : (card.path.isNotEmpty ? card.path : '附件'),
                style: const TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w500,
                  color: Color(0xFF1F2328),
                ),
              ),
            ),
        ],
        if (statChips.isNotEmpty) ...[
          const SizedBox(height: 8),
          Wrap(
            spacing: 6,
            runSpacing: 4,
            children: [
              for (final chip in statChips)
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                  decoration: BoxDecoration(
                    color: const Color(0xFFF1F3F5),
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: Text(
                    chip,
                    style: const TextStyle(
                      fontSize: 10,
                      color: Color(0xFF57606A),
                    ),
                  ),
                ),
            ],
          ),
        ],
      ],
    );
  }
}
