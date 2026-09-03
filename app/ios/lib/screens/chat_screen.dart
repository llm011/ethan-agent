import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';
import 'package:file_picker/file_picker.dart';

import 'package:flutter/material.dart';

import '../data/api_client.dart';
import '../models/app_models.dart';
import '../services/api_service.dart';
import 'session_media_screens.dart';

class ChatScreen extends StatefulWidget {
  const ChatScreen(
      {required this.api,
      required this.workspaceApi,
      required this.onMenu,
      this.sessionId,
      super.key});
  final EthanApiClient api;
  final EthanApiService workspaceApi;
  final VoidCallback onMenu;
  final String? sessionId;
  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> with WidgetsBindingObserver {
  final input = TextEditingController();
  final scroll = ScrollController();
  List<ChatMessage> messages = [];
  List<ModelEntry> models = [];
  List<ModeEntry> modes = [];
  String? sessionId, selectedModel;
  String selectedMode = '';
  String title = '新对话';
  bool loading = false, streaming = false, resuming = false, stopping = false;
  String? error;
  ConsentInfo? consent;
  AskUserInfo? askUser;
  WaitForUserInfo? waitForUser;
  int askRemaining = 0, waitRemaining = 0;
  Timer? askTimer, waitTimer;
  int unread = 0;
  StreamSubscription<ChatEvent>? streamSub;
  List<MessageImage> pendingImages = [];
  QuoteInfo? quote;
  OnboardingStatus? onboarding;
  final agentName = TextEditingController();
  final userInfo = TextEditingController();

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    scroll.addListener(_onScroll);
    _load();
  }

  @override
  void didUpdateWidget(covariant ChatScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.sessionId != widget.sessionId) _load();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) _resume();
  }

  Future<void> _load() async {
    await streamSub?.cancel();
    final nextId = widget.sessionId;
    if (mounted)
      setState(() {
        sessionId = nextId;
        title = '新对话';
        messages = [];
        error = null;
        loading = nextId != null;
        streaming = false;
      });
    try {
      final results = await Future.wait([
        widget.api.models(),
        widget.api.modes(),
        widget.api.onboardingStatus(),
        widget.api.defaultModel(),
      ]);
      if (mounted)
        setState(() {
          models = results[0] as List<ModelEntry>;
          modes = results[1] as List<ModeEntry>;
          final serverDefault = results[3] as String?;
          ModelEntry? defaultEntry;
          if (serverDefault != null) {
            for (final model in models) {
              if (model.id == serverDefault ||
                  model.aliases.contains(serverDefault)) {
                defaultEntry = model;
                break;
              }
            }
          }
          selectedModel ??=
              defaultEntry?.id ?? (models.isEmpty ? null : models.first.id);
          onboarding = results[2] as OnboardingStatus;
        });
      if (onboarding?.firstTime == true && mounted) _showOnboarding();
      if (nextId != null) {
        final detail = await widget.api.session(nextId);
        if (mounted && sessionId == nextId)
          setState(() {
            title = detail.title;
            messages = detail.messages;
            selectedModel = detail.model.isEmpty ? selectedModel : detail.model;
            selectedMode = detail.mode ?? '';
            loading = false;
          });
        await _resume();
      }
    } catch (e) {
      if (mounted)
        setState(() {
          error = e.toString();
          loading = false;
        });
    }
    if (mounted && nextId == null) setState(() => loading = false);
  }

  Future<void> _resume() async {
    final id = sessionId;
    if (id == null || streaming || resuming) return;
    setState(() => resuming = true);
    await _consume(widget.api.resumeStream(id), resumed: true);
    if (mounted) setState(() => resuming = false);
  }

  Future<void> send() async {
    final text = input.text.trim();
    if (text.isEmpty && pendingImages.isEmpty) return;
    if (streaming) {
      input.clear();
      final id = sessionId;
      if (id != null) {
        try {
          await widget.api.inject(id, text);
        } on ApiException catch (e) {
          if (e.status == 409) {
            if (mounted)
              setState(() {
                streaming = false;
                input.text = text;
              });
            return send();
          }
          if (mounted) setState(() => error = e.toString());
        } catch (e) {
          if (mounted) setState(() => error = e.toString());
        }
      }
      return;
    }
    input.clear();
    if (text.startsWith('/') && pendingImages.isEmpty) {
      return _slash(text);
    }
    final user = ChatMessage(
        text: text,
        isUser: true,
        time: '现在',
        quote: quote,
        images: pendingImages);
    if (mounted)
      setState(() {
        messages = [
          ...messages,
          user,
          const ChatMessage(
              text: '', isUser: false, time: '', isStreaming: true)
        ];
        streaming = true;
        error = null;
        quote = null;
        pendingImages = [];
      });
    try {
      final active = sessionId ??
          (await widget.api.createSession(
                  model: selectedModel,
                  mode: selectedMode.isEmpty ? null : selectedMode))
              .id;
      if (mounted) setState(() => sessionId = active);
      await _consume(widget.api.chat(
          text: text,
          sessionId: active,
          model: selectedModel,
          mode: selectedMode.isEmpty ? null : selectedMode,
          history: messages.where((m) => !m.isStreaming).toList(),
          quote: user.quote,
          images: user.images));
    } catch (e) {
      if (mounted)
        setState(() {
          error = e.toString();
          if (messages.isNotEmpty && messages.last.isStreaming)
            messages = messages.sublist(0, messages.length - 1);
        });
    }
    if (mounted) setState(() => streaming = false);
  }

  Future<void> _consume(Stream<ChatEvent> events,
      {bool resumed = false}) async {
    var content = resumed && messages.isNotEmpty && messages.last.isStreaming
        ? messages.last.text
        : '';
    var steps = resumed && messages.isNotEmpty && messages.last.isStreaming
        ? [...messages.last.toolSteps]
        : <ToolStep>[];
    var cards = resumed && messages.isNotEmpty && messages.last.isStreaming
        ? [...messages.last.cards]
        : <MediaCard>[];
    final started = DateTime.now();
    DateTime? firstContent;
    UsageInfo? usage;
    if (resumed && (messages.isEmpty || !messages.last.isStreaming) && mounted)
      setState(() => messages = [
            ...messages,
            const ChatMessage(
                text: '', isUser: false, time: '', isStreaming: true)
          ]);
    await streamSub?.cancel();
    streamSub = events.listen((event) {
      if (!mounted) return;
      if (event.error != null) {
        setState(() => error = event.error);
        return;
      }
      if (event.consentRequest)
        setState(() => consent = ConsentInfo(
            requestId: event.requestId ?? '',
            tool: event.tool ?? '',
            description: event.description ?? '',
            detail: event.detail));
      if (event.askUserRequest) _showAsk(event);
      if (event.waitForUserRequest) _showWait(event);
      if (event.content != null) {
        firstContent ??= DateTime.now();
        content += event.content!;
      }
      if (event.tool != null) {
        final step = ToolStep(
            tool: event.tool!,
            id: event.id,
            args: event.args ?? '',
            state: event.state ?? 'start',
            durationMs: event.durationMs,
            resultPreview: event.resultPreview,
            resultDetail: event.resultDetail,
            thought: event.thought,
            intent: event.intent,
            subSteps: event.subSteps);
        final i =
            step.id == null ? -1 : steps.indexWhere((s) => s.id == step.id);
        if (i >= 0)
          steps[i] = step;
        else
          steps.add(step);
      }
      if (event.usage != null) usage = event.usage;
      for (final card in event.cards) {
        final duplicate = cards.any((existing) =>
            (card.path.isNotEmpty && existing.path == card.path) ||
            (card.url.isNotEmpty && existing.url == card.url));
        if (!duplicate) cards.add(card);
      }
      if (messages.isNotEmpty)
        setState(() => messages = [
              ...messages.sublist(0, messages.length - 1),
              ChatMessage(
                  text: content,
                  isUser: false,
                  time: event.done ? '现在' : '',
                  toolSteps: [...steps],
                  cards: [...cards],
                  isStreaming: !event.done,
                  usage: usage,
                  ttfbMs: firstContent?.difference(started).inMilliseconds,
                  totalDurationMs: event.done
                      ? DateTime.now().difference(started).inMilliseconds
                      : null,
                  generationDurationMs: event.done && firstContent != null
                      ? DateTime.now().difference(firstContent!).inMilliseconds
                      : null)
            ]);
      _messageArrived();
    }, onError: (Object e) {
      if (mounted) setState(() => error = e.toString());
    }, onDone: () {
      if (mounted && messages.isNotEmpty && messages.last.isStreaming)
        setState(() => messages = [
              ...messages.sublist(0, messages.length - 1),
              ChatMessage(
                  text: content,
                  isUser: false,
                  time: '现在',
                  toolSteps: _sanitizeSteps(steps),
                  cards: [...cards],
                  usage: usage,
                  ttfbMs: firstContent?.difference(started).inMilliseconds,
                  totalDurationMs:
                      DateTime.now().difference(started).inMilliseconds,
                  generationDurationMs: firstContent == null
                      ? null
                      : DateTime.now().difference(firstContent!).inMilliseconds)
            ]);
    });
    await streamSub!.asFuture<void>();
  }

  void _showAsk(ChatEvent e) {
    askTimer?.cancel();
    final info = AskUserInfo(
        requestId: e.requestId ?? '',
        question: e.question ?? '',
        options: e.options,
        defaultValue: e.defaultValue ?? '',
        timeout: e.timeout ?? 20);
    setState(() {
      askUser = info;
      askRemaining = info.timeout;
    });
    var n = info.timeout;
    askTimer = Timer.periodic(const Duration(seconds: 1), (t) {
      if (!mounted || askUser?.requestId != info.requestId) return t.cancel();
      if (mounted) setState(() => askRemaining = --n);
      if (n <= 0) {
        t.cancel();
        if (info.options.isNotEmpty)
          _answerAsk(info.defaultValue);
        else
          setState(() => askUser = null);
      }
    });
  }

  void _showWait(ChatEvent e) {
    waitTimer?.cancel();
    final info = WaitForUserInfo(
        requestId: e.requestId ?? '',
        prompt: e.prompt ?? '',
        inputType: e.inputType ?? 'confirm',
        placeholder: e.placeholder ?? '',
        confirmLabel: e.confirmLabel ?? '已完成',
        cancelLabel: e.cancelLabel ?? '取消',
        timeout: e.timeout ?? 300);
    setState(() {
      waitForUser = info;
      waitRemaining = info.timeout;
    });
    var n = info.timeout;
    waitTimer = Timer.periodic(const Duration(seconds: 1), (t) {
      if (!mounted || waitForUser?.requestId != info.requestId)
        return t.cancel();
      if (mounted) setState(() => waitRemaining = --n);
      if (n <= 0) {
        t.cancel();
        _answerWait('timeout');
      }
    });
  }

  Future<void> _answerAsk(String value) async {
    final i = askUser;
    if (i == null) return;
    setState(() {
      askUser = null;
      askRemaining = 0;
    });
    askTimer?.cancel();
    try {
      await widget.api.respondAskUser(i.requestId, value);
    } catch (e) {
      if (mounted)
        setState(() {
          askUser = i;
          error = e.toString();
        });
    }
  }

  Future<void> _answerWait(String value) async {
    final i = waitForUser;
    if (i == null) return;
    setState(() {
      waitForUser = null;
      waitRemaining = 0;
    });
    waitTimer?.cancel();
    try {
      await widget.api.respondWaitForUser(i.requestId, value);
    } catch (e) {
      if (mounted)
        setState(() {
          waitForUser = i;
          error = e.toString();
        });
    }
  }

  Future<void> stop() async {
    final id = sessionId;
    setState(() => stopping = true);
    try {
      if (id != null) await widget.api.stopChat(id);
    } catch (_) {}
    await streamSub?.cancel();
    if (mounted) {
      setState(() {
        streaming = false;
        stopping = false;
        if (messages.isNotEmpty && messages.last.isStreaming)
          messages = [
            ...messages.sublist(0, messages.length - 1),
            ChatMessage(
                text:
                    '${messages.last.text}${messages.last.text.isEmpty ? '' : ' '}[已停止]',
                isUser: false,
                time: '现在',
                toolSteps: _sanitizeSteps(messages.last.toolSteps),
                usage: messages.last.usage,
                ttfbMs: messages.last.ttfbMs,
                totalDurationMs: messages.last.totalDurationMs,
                generationDurationMs: messages.last.generationDurationMs)
          ];
      });
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    scroll.removeListener(_onScroll);
    streamSub?.cancel();
    askTimer?.cancel();
    waitTimer?.cancel();
    input.dispose();
    scroll.dispose();
    agentName.dispose();
    userInfo.dispose();
    super.dispose();
  }

  Future<void> _slash(String command) async {
    final cmd = command.trim().split(RegExp(r'\s+')).first.toLowerCase();
    if (mounted) input.clear();
    switch (cmd) {
      case '/new':
        await streamSub?.cancel();
        if (mounted)
          setState(() {
            sessionId = null;
            title = '新对话';
            messages = [];
            streaming = false;
            error = null;
          });
        return;
      case '/compact':
        if (sessionId == null) return;
        try {
          await widget.api.compactSession(sessionId!);
          await _load();
        } catch (e) {
          if (mounted) setState(() => error = e.toString());
        }
        return;
      case '/help':
        if (mounted)
          setState(() => messages = [
                ...messages,
                const ChatMessage(
                    text:
                        '可用命令：\n/new - 新建对话\n/compact - 压缩历史\n/sessions - 查看最近会话\n/help - 帮助',
                    isUser: false,
                    time: '现在')
              ]);
        return;
      case '/sessions':
        try {
          final rows = await widget.api.sessions();
          final text = rows
              .take(8)
              .map((s) =>
                  '• ${s.title} (${s.id.substring(0, s.id.length > 8 ? 8 : s.id.length)}…)')
              .join('\n');
          if (mounted)
            setState(() => messages = [
                  ...messages,
                  ChatMessage(text: '最近会话：\n$text', isUser: false, time: '现在')
                ]);
        } catch (e) {
          if (mounted) setState(() => error = e.toString());
        }
        return;
      default:
        if (mounted) setState(() => error = '未知命令：$command');
        return;
    }
  }

  List<ToolStep> _sanitizeSteps(List<ToolStep> steps) => steps.map((step) {
        final active = step.state == 'start' || step.state == 'running';
        final subSteps = step.subSteps
            .map((sub) => sub.state == 'start' || sub.state == 'running'
                ? sub.copyWith(state: 'cancelled')
                : sub)
            .toList();
        return active
            ? step.copyWith(state: 'cancelled', subSteps: subSteps)
            : step.copyWith(subSteps: subSteps);
      }).toList();

  Future<void> _pickAttachment() async {
    final result = await FilePicker.platform
        .pickFiles(type: FileType.any, withData: true, allowMultiple: true);
    if (result == null) return;
    final selected = <MessageImage>[];
    final uploads = <String>[];
    for (final file in result.files.where((file) => file.bytes != null)) {
      final mime = _mimeFor(file.extension);
      if (!mime.startsWith('image/')) {
        try {
          final uploaded =
              await widget.api.uploadFile(file.bytes!, file.name, mime);
          final path = uploaded['path']?.toString() ?? '';
          uploads.add(
              '[Uploaded file: ${file.name}${path.isEmpty ? '' : ' at $path'}]');
        } catch (e) {
          if (mounted) setState(() => error = '上传 ${file.name} 失败：$e');
        }
        continue;
      }
      final encoded = base64Encode(file.bytes!);
      selected.add(MessageImage(
          data: encoded,
          mediaType: mime,
          displayUrl: 'data:$mime;base64,$encoded'));
    }
    if (mounted)
      setState(() {
        pendingImages = [...pendingImages, ...selected];
        if (uploads.isNotEmpty) {
          input.text = [input.text.trim(), ...uploads]
              .where((text) => text.isNotEmpty)
              .join('\n');
        }
      });
  }

  String _mimeFor(String? extension) => switch (extension?.toLowerCase()) {
        'jpg' || 'jpeg' => 'image/jpeg',
        'png' => 'image/png',
        'gif' => 'image/gif',
        'webp' => 'image/webp',
        'heic' => 'image/heic',
        'pdf' => 'application/pdf',
        'txt' || 'md' => 'text/plain',
        _ => 'application/octet-stream',
      };

  Future<void> _showOnboarding() async {
    agentName.text = '';
    userInfo.text = '';
    await showDialog<void>(
        context: context,
        barrierDismissible: false,
        builder: (context) => AlertDialog(
              title: const Text('欢迎使用 Ethan'),
              content: Column(mainAxisSize: MainAxisSize.min, children: [
                TextField(
                    controller: agentName,
                    decoration: const InputDecoration(labelText: '给助手起个名字')),
                TextField(
                    controller: userInfo,
                    decoration: const InputDecoration(labelText: '如何称呼你（可选）')),
              ]),
              actions: [
                TextButton(
                    onPressed: () {
                      Navigator.pop(context);
                      if (mounted) {
                        setState(() => onboarding = const OnboardingStatus());
                      }
                    },
                    child: const Text('跳过')),
                FilledButton(
                    onPressed: () async {
                      try {
                        await widget.api.completeOnboarding(
                            agentName.text.trim(), userInfo.text.trim());
                        if (context.mounted) Navigator.pop(context);
                        if (mounted)
                          setState(() => onboarding = const OnboardingStatus());
                      } catch (e) {
                        if (mounted) setState(() => error = e.toString());
                      }
                    },
                    child: const Text('开始使用'))
              ],
            ));
  }

  void _bottom() => WidgetsBinding.instance.addPostFrameCallback((_) {
        if (scroll.hasClients)
          scroll.animateTo(scroll.position.maxScrollExtent,
              duration: const Duration(milliseconds: 160),
              curve: Curves.easeOut);
      });

  bool get _nearBottom =>
      !scroll.hasClients ||
      scroll.position.maxScrollExtent - scroll.offset < 72;

  void _onScroll() {
    if (_nearBottom && unread > 0 && mounted) setState(() => unread = 0);
  }

  void _messageArrived() {
    if (_nearBottom) {
      _bottom();
    } else if (mounted) {
      setState(() => unread++);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(
            leading: IconButton(
                onPressed: widget.onMenu, icon: const Icon(Icons.menu_rounded)),
            title:
                Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(title),
              if (streaming || resuming)
                const Text('正在生成…', style: TextStyle(fontSize: 12))
            ]),
            actions: [
              IconButton(
                  onPressed: streaming || loading ? null : _load,
                  icon: const Icon(Icons.refresh_rounded)),
              PopupMenuButton<String>(
                  onSelected: (v) {
                    if (v == 'model') _pickModel();
                    if (v == 'mode') _pickMode();
                    if (v == 'annotations') _openAnnotations();
                    if (v == 'ppt') _openPptPreview();
                  },
                  itemBuilder: (_) => [
                        const PopupMenuItem(
                            value: 'model', child: Text('选择模型')),
                        const PopupMenuItem(value: 'mode', child: Text('选择模式')),
                        if (sessionId != null) ...[
                          const PopupMenuDivider(),
                          const PopupMenuItem(
                              value: 'annotations', child: Text('查看标注')),
                          const PopupMenuItem(
                              value: 'ppt', child: Text('PPT 预览')),
                        ],
                      ])
            ]),
        body: Stack(
          children: [
            Column(
              children: [
                if (error != null)
                  MaterialBanner(content: Text('请求失败：$error'), actions: [
                    TextButton(
                        onPressed: loading || streaming ? null : _load,
                        child: const Text('重试')),
                    TextButton(
                        onPressed: () => setState(() => error = null),
                        child: const Text('关闭'))
                  ]),
                Expanded(
                  child: loading
                      ? const Center(child: CircularProgressIndicator())
                      : messages.isEmpty
                          ? _ChatEmptyState(onOpenSessions: widget.onMenu)
                          : ListView.builder(
                              controller: scroll,
                              padding:
                                  const EdgeInsets.fromLTRB(16, 12, 16, 20),
                              itemCount: messages.length,
                              itemBuilder: (_, i) => _Bubble(
                                  message: messages[i],
                                  onQuote: messages[i].text.isEmpty
                                      ? null
                                      : () => setState(() => quote = QuoteInfo(
                                          role: messages[i].isUser
                                              ? 'user'
                                              : 'assistant',
                                          content: messages[i].text)),
                                  api: widget.api,
                                  workspaceApi: widget.workspaceApi,
                                  sessionId: sessionId)),
                ),
                _Composer(
                    controller: input,
                    busy: streaming,
                    stopping: stopping,
                    pendingImages: pendingImages,
                    quote: quote,
                    onClearQuote: () => setState(() => quote = null),
                    onRemoveImage: (index) => setState(() => pendingImages = [
                          ...pendingImages.take(index),
                          ...pendingImages.skip(index + 1)
                        ]),
                    onAttach: _pickAttachment,
                    onSend: send,
                    onStop: stop)
              ],
            ),
            if (unread > 0 && !_nearBottom)
              Positioned(
                  right: 18,
                  bottom: 82,
                  child: FilledButton.tonalIcon(
                      onPressed: () {
                        setState(() => unread = 0);
                        _bottom();
                      },
                      icon: const Icon(Icons.keyboard_arrow_down_rounded),
                      label: Text('新消息 $unread'))),
            if (consent != null || askUser != null || waitForUser != null)
              Positioned.fill(
                child: ColoredBox(
                  color: Colors.black26,
                  child: Center(
                    child: Card(
                      margin: const EdgeInsets.all(24),
                      child: Padding(
                        padding: const EdgeInsets.all(20),
                        child: consent != null
                            ? _ConsentCard(
                                info: consent!,
                                onAnswer: (v) async {
                                  final i = consent!;
                                  setState(() => consent = null);
                                  try {
                                    await widget.api
                                        .respondConsent(i.requestId, v);
                                  } catch (e) {
                                    if (mounted)
                                      setState(() {
                                        consent = i;
                                        error = e.toString();
                                      });
                                  }
                                })
                            : askUser != null
                                ? _AskCard(
                                    info: askUser!,
                                    secondsLeft: askRemaining,
                                    onAnswer: _answerAsk)
                                : _WaitCard(
                                    info: waitForUser!,
                                    secondsLeft: waitRemaining,
                                    onAnswer: _answerWait),
                      ),
                    ),
                  ),
                ),
              ),
          ],
        ),
      );
  Future<void> _pickModel() async {
    if (models.isEmpty) return;
    final v = await showModalBottomSheet<String>(
        context: context,
        builder: (_) => ListView(
            children: models
                .map((m) => ListTile(
                    title: Text(m.id),
                    subtitle: Text(m.provider),
                    onTap: () => Navigator.pop(context, m.id)))
                .toList()));
    if (v != null) setState(() => selectedModel = v);
  }

  Future<void> _pickMode() async {
    if (modes.isEmpty) return;
    final v = await showModalBottomSheet<String>(
        context: context,
        builder: (_) => ListView(children: [
              ListTile(
                  title: const Text('默认模式'),
                  onTap: () => Navigator.pop(context, '')),
              ...modes.map((m) => ListTile(
                  title: Text(m.label),
                  subtitle: Text(m.blurb),
                  onTap: () => Navigator.pop(context, m.key)))
            ]));
    if (v != null) setState(() => selectedMode = v);
  }

  void _openAnnotations() {
    final ids = messages
        .map((message) => int.tryParse(message.id ?? ''))
        .whereType<int>()
        .toList();
    Navigator.of(context).push(MaterialPageRoute(
        builder: (_) =>
            AnnotationsScreen(api: widget.workspaceApi, messageIds: ids)));
  }

  void _openPptPreview() {
    final id = sessionId;
    if (id == null) return;
    Navigator.of(context).push(MaterialPageRoute(
        builder: (_) => PptPreviewScreen(
            api: widget.workspaceApi, sessionId: id, deckPath: _pptPath())));
  }

  String? _pptPath() {
    for (final message in messages.reversed) {
      for (final card in message.cards.reversed) {
        if (card.isPpt && card.path.isNotEmpty) return card.path;
      }
    }
    return null;
  }
}

class _Bubble extends StatelessWidget {
  const _Bubble(
      {required this.message,
      required this.api,
      required this.workspaceApi,
      this.sessionId,
      this.onQuote});
  final ChatMessage message;
  final EthanApiClient api;
  final EthanApiService workspaceApi;
  final String? sessionId;
  final VoidCallback? onQuote;
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final color = message.isUser
        ? theme.colorScheme.primaryContainer
        : theme.colorScheme.surfaceContainerLow;
    final isActive = message.isStreaming;
    return GestureDetector(
        onLongPress: onQuote,
        child: Align(
            alignment:
                message.isUser ? Alignment.centerRight : Alignment.centerLeft,
            child: Container(
                constraints: BoxConstraints(
                    maxWidth: MediaQuery.sizeOf(context).width >= 600
                        ? 640
                        : MediaQuery.sizeOf(context).width * .86),
                margin: const EdgeInsets.only(bottom: 16),
                padding: const EdgeInsets.fromLTRB(15, 12, 15, 11),
                decoration: BoxDecoration(
                    color: color,
                    borderRadius: BorderRadius.circular(18),
                    border: message.isUser
                        ? null
                        : Border.all(
                            color: theme.dividerColor.withOpacity(.45))),
                child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Icon(
                              message.isUser
                                  ? Icons.person_outline_rounded
                                  : Icons.auto_awesome_rounded,
                              size: 16,
                              color: message.isUser
                                  ? theme.colorScheme.primary
                                  : theme.colorScheme.secondary),
                          const SizedBox(width: 6),
                          Text(message.isUser ? '你' : 'Ethan',
                              style: theme.textTheme.labelMedium
                                  ?.copyWith(fontWeight: FontWeight.w700)),
                          if (isActive) ...[
                            const SizedBox(width: 8),
                            _StatusPill(
                                label: '生成中', color: theme.colorScheme.primary),
                          ],
                          const Spacer(),
                          if (message.time.isNotEmpty)
                            Text(message.time,
                                style: theme.textTheme.labelSmall),
                        ],
                      ),
                      const SizedBox(height: 8),
                      if (message.text.isEmpty && message.isStreaming)
                        Row(children: [
                          SizedBox(
                              width: 16,
                              height: 16,
                              child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                  color: theme.colorScheme.primary)),
                          const SizedBox(width: 8),
                          Text('正在准备回复…', style: theme.textTheme.bodySmall),
                        ])
                      else if (message.text.isNotEmpty)
                        _MarkdownText(text: message.text),
                      if (message.toolSteps.isNotEmpty)
                        _ToolTimeline(steps: message.toolSteps),
                      if (message.quote != null)
                        Text('引用：${message.quote!.content}',
                            style: Theme.of(context).textTheme.bodySmall),
                      if (message.images.isNotEmpty)
                        Wrap(
                            spacing: 6,
                            runSpacing: 6,
                            children: message.images
                                .map((image) =>
                                    _MessageImageView(image: image, api: api))
                                .toList()),
                      if (message.cards.isNotEmpty)
                        _MediaCards(
                            cards: message.cards,
                            api: api,
                            workspaceApi: workspaceApi,
                            sessionId: sessionId),
                      if (message.usage != null || message.toolSteps.isNotEmpty)
                        Padding(
                          padding: const EdgeInsets.only(top: 10),
                          child: Row(children: [
                            if (message.usage != null)
                              Text(
                                  'Tokens ${message.usage!.input}/${message.usage!.output}',
                                  style: theme.textTheme.labelSmall),
                            if (message.usage != null &&
                                message.toolSteps.isNotEmpty)
                              const Padding(
                                  padding: EdgeInsets.symmetric(horizontal: 6),
                                  child: Text('·')),
                            if (message.toolSteps.isNotEmpty)
                              Text('${message.toolSteps.length} 个步骤',
                                  style: theme.textTheme.labelSmall),
                          ]),
                        ),
                    ]))));
  }
}

class _StatusPill extends StatelessWidget {
  const _StatusPill({required this.label, required this.color});
  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
        decoration: BoxDecoration(
            color: color.withOpacity(.12),
            borderRadius: BorderRadius.circular(20)),
        child: Text(label,
            style: Theme.of(context)
                .textTheme
                .labelSmall
                ?.copyWith(color: color, fontWeight: FontWeight.w700)),
      );
}

class _MarkdownText extends StatelessWidget {
  const _MarkdownText({required this.text});
  final String text;

  @override
  Widget build(BuildContext context) {
    final lines = text.split('\n');
    return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: lines.map((line) {
          final code = line.startsWith('```') || line.startsWith('    ');
          final bullet = RegExp(r'^[-*]\s+').hasMatch(line);
          final bold = RegExp(r'\*\*(.+?)\*\*').firstMatch(line);
          final content =
              bullet ? line.replaceFirst(RegExp(r'^[-*]\s+'), '') : line;
          return Padding(
              padding: const EdgeInsets.only(bottom: 3),
              child: code
                  ? Container(
                      width: double.infinity,
                      padding: const EdgeInsets.all(8),
                      color:
                          Theme.of(context).colorScheme.surfaceContainerHighest,
                      child: SelectableText(content,
                          style: const TextStyle(fontFamily: 'monospace')))
                  : RichText(
                      text: TextSpan(
                          style: DefaultTextStyle.of(context).style,
                          children: [
                          if (bullet) const TextSpan(text: '• '),
                          if (bold == null)
                            TextSpan(text: content)
                          else ...[
                            TextSpan(text: content.substring(0, bold.start)),
                            TextSpan(
                                text: bold.group(1),
                                style: const TextStyle(
                                    fontWeight: FontWeight.w700)),
                            TextSpan(text: content.substring(bold.end)),
                          ]
                        ])));
        }).toList());
  }
}

class _ToolTimeline extends StatelessWidget {
  const _ToolTimeline({required this.steps});
  final List<ToolStep> steps;

  @override
  Widget build(BuildContext context) => Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: steps.asMap().entries.map((entry) {
        final step = entry.value;
        final state = step.state.toLowerCase();
        final failed = state.contains('error') || state.contains('fail');
        final active = state == 'start' || state == 'running';
        final statusColor = failed
            ? Theme.of(context).colorScheme.error
            : active
                ? Theme.of(context).colorScheme.primary
                : Theme.of(context).colorScheme.tertiary;
        final statusText = failed
            ? '失败'
            : active
                ? '执行中'
                : state.contains('cancel')
                    ? '已取消'
                    : '完成';
        return Card(
          margin: const EdgeInsets.only(top: 7),
          elevation: 0,
          color: Theme.of(context).colorScheme.surface,
          shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(12),
              side: BorderSide(
                  color: Theme.of(context).dividerColor.withOpacity(.5))),
          child: ExpansionTile(
            dense: true,
            leading: Icon(
                failed
                    ? Icons.error_outline_rounded
                    : active
                        ? Icons.timelapse_rounded
                        : Icons.check_circle_outline_rounded,
                color: statusColor,
                size: 20),
            title: Text(step.tool.isEmpty ? '工具步骤 ${entry.key + 1}' : step.tool,
                style: const TextStyle(fontWeight: FontWeight.w700)),
            subtitle: Row(children: [
              _StatusPill(label: statusText, color: statusColor),
              if (step.durationMs != null) ...[
                const SizedBox(width: 7),
                Text('${step.durationMs} ms'),
              ],
            ]),
            childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 10),
            children: [
              if (step.args.isNotEmpty)
                Align(
                    alignment: Alignment.centerLeft,
                    child: SelectableText('参数：${step.args}')),
              if ((step.resultPreview ?? '').isNotEmpty)
                Align(
                    alignment: Alignment.centerLeft,
                    child: SelectableText('结果：${step.resultPreview}')),
              if ((step.resultDetail ?? '').isNotEmpty)
                Align(
                    alignment: Alignment.centerLeft,
                    child: SelectableText(step.resultDetail!)),
              ...step.subSteps.map((sub) => ListTile(
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    leading:
                        const Icon(Icons.subdirectory_arrow_right, size: 18),
                    title: Text(sub.tool),
                    subtitle: Text([
                      sub.state,
                      if (sub.durationMs != null) '${sub.durationMs} ms',
                      if ((sub.resultPreview ?? '').isNotEmpty)
                        sub.resultPreview!,
                    ].join(' · ')),
                  )),
            ],
          ),
        );
      }).toList());
}

class _MessageImageView extends StatelessWidget {
  const _MessageImageView({required this.image, this.api, this.size = 64});
  final MessageImage image;
  final EthanApiClient? api;
  final double size;

  void _open(BuildContext context, String source) {
    showDialog<void>(
      context: context,
      builder: (_) => Dialog(
        child: InteractiveViewer(
          child: source.startsWith('data:')
              ? Image.memory(base64Decode(source.split(',').last),
                  fit: BoxFit.contain)
              : Image.network(source,
                  fit: BoxFit.contain,
                  headers: Uri.tryParse(source) == null || api == null
                      ? const {}
                      : api!.headersFor(Uri.parse(source))),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final source = image.displayUrl ?? image.url;
    if (source == null || source.isEmpty) {
      return SizedBox(
          width: size, height: size, child: const Icon(Icons.image_outlined));
    }
    if (source.startsWith('data:')) {
      try {
        return GestureDetector(
          onTap: () => _open(context, source),
          child: Image.memory(base64Decode(source.split(',').last),
              width: size,
              height: size,
              fit: BoxFit.cover,
              errorBuilder: (_, __, ___) => const Icon(Icons.broken_image)),
        );
      } catch (_) {
        return const Icon(Icons.broken_image);
      }
    }
    final uri = Uri.tryParse(source);
    return GestureDetector(
      onTap: () => _open(context, source),
      child: Image.network(source,
          width: size,
          height: size,
          fit: BoxFit.cover,
          headers: uri == null || api == null ? const {} : api!.headersFor(uri),
          errorBuilder: (_, __, ___) => const Icon(Icons.broken_image)),
    );
  }
}

class _MediaCards extends StatelessWidget {
  const _MediaCards(
      {required this.cards,
      required this.api,
      required this.workspaceApi,
      this.sessionId});
  final List<MediaCard> cards;
  final EthanApiClient api;
  final EthanApiService workspaceApi;
  final String? sessionId;

  @override
  Widget build(BuildContext context) => Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: const EdgeInsets.only(top: 12, bottom: 2),
            child: Row(children: [
              Icon(Icons.inventory_2_outlined,
                  size: 16, color: Theme.of(context).colorScheme.secondary),
              const SizedBox(width: 6),
              Text('交付内容',
                  style: Theme.of(context).textTheme.labelLarge?.copyWith(
                      fontWeight: FontWeight.w700,
                      color: Theme.of(context).colorScheme.secondary)),
            ]),
          ),
          ...cards.map((card) {
            if (card.isImage) {
              final source = card.url.isNotEmpty ? card.url : card.path;
              if (source.startsWith('data:')) {
                try {
                  return GestureDetector(
                    onTap: () => showDialog<void>(
                      context: context,
                      builder: (_) => Dialog(
                        child: InteractiveViewer(
                            child: Image.memory(
                                base64Decode(source.split(',').last),
                                fit: BoxFit.contain)),
                      ),
                    ),
                    child: Padding(
                      padding: const EdgeInsets.only(top: 8),
                      child: Image.memory(base64Decode(source.split(',').last),
                          height: 180, fit: BoxFit.contain),
                    ),
                  );
                } catch (_) {}
              }
              if (card.isFile && sessionId != null && sessionId!.isNotEmpty) {
                return FutureBuilder<Uint8List>(
                  future: api.fetchMediaBytes(card.path, sessionId: sessionId),
                  builder: (_, snapshot) => Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: snapshot.hasData
                        ? Image.memory(snapshot.data!,
                            height: 180, fit: BoxFit.contain)
                        : snapshot.hasError
                            ? const Icon(Icons.broken_image_outlined)
                            : const SizedBox(
                                height: 120,
                                child:
                                    Center(child: CircularProgressIndicator())),
                  ),
                );
              }
              final uri = Uri.tryParse(source);
              if (uri != null && source.startsWith('http')) {
                return GestureDetector(
                  onTap: () => showDialog<void>(
                    context: context,
                    builder: (_) => Dialog(
                      child: InteractiveViewer(
                          child: Image.network(source,
                              fit: BoxFit.contain,
                              headers: api.headersFor(uri))),
                    ),
                  ),
                  child: Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: Image.network(source,
                        height: 180,
                        fit: BoxFit.contain,
                        headers: api.headersFor(uri),
                        errorBuilder: (_, __, ___) =>
                            const Icon(Icons.broken_image_outlined)),
                  ),
                );
              }
            }
            return Card(
              margin: const EdgeInsets.only(top: 8),
              child: ListTile(
                leading: Icon(card.isVideo
                    ? Icons.movie_outlined
                    : card.isPpt
                        ? Icons.slideshow_outlined
                        : Icons.insert_drive_file_outlined),
                title: Text(card.title.isEmpty
                    ? card.path.split('/').last
                    : card.title),
                subtitle: Text(card.isVideo
                    ? '视频文件'
                    : card.isPpt
                        ? 'PPT 文件'
                        : '已交付文件'),
                trailing: card.isVideo || card.isPpt
                    ? const Icon(Icons.chevron_right_rounded)
                    : null,
                onTap: card.isVideo
                    ? () => Navigator.of(context).push(MaterialPageRoute(
                          builder: (_) => VideoPreviewScreen(
                              api: api,
                              sessionId: sessionId ?? '',
                              path: card.path,
                              title: card.title),
                        ))
                    : card.isPpt && sessionId != null
                        ? () => Navigator.of(context).push(MaterialPageRoute(
                              builder: (_) => PptPreviewScreen(
                                  api: workspaceApi,
                                  sessionId: sessionId!,
                                  deckPath: card.path),
                            ))
                        : null,
              ),
            );
          }).toList(),
        ],
      );
}

class _ConsentCard extends StatelessWidget {
  const _ConsentCard({required this.info, required this.onAnswer});
  final ConsentInfo info;
  final ValueChanged<bool> onAnswer;
  @override
  Widget build(BuildContext context) => Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(children: [
              Icon(Icons.verified_user_outlined,
                  color: Theme.of(context).colorScheme.primary),
              const SizedBox(width: 8),
              Expanded(
                  child: Text('需要你的授权',
                      style: Theme.of(context)
                          .textTheme
                          .titleMedium
                          ?.copyWith(fontWeight: FontWeight.w800))),
            ]),
            const SizedBox(height: 6),
            Text(info.tool,
                style: Theme.of(context)
                    .textTheme
                    .labelLarge
                    ?.copyWith(color: Theme.of(context).colorScheme.primary)),
            const SizedBox(height: 10),
            Text(info.description),
            if (info.detail != null)
              Text(info.detail!, style: Theme.of(context).textTheme.bodySmall),
            const SizedBox(height: 16),
            Row(mainAxisAlignment: MainAxisAlignment.end, children: [
              TextButton(
                  onPressed: () => onAnswer(false), child: const Text('拒绝')),
              FilledButton(
                  onPressed: () => onAnswer(true), child: const Text('允许'))
            ])
          ]);
}

class _AskCard extends StatelessWidget {
  const _AskCard(
      {required this.info, required this.secondsLeft, required this.onAnswer});
  final AskUserInfo info;
  final int secondsLeft;
  final ValueChanged<String> onAnswer;
  @override
  Widget build(BuildContext context) => Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(children: [
              Icon(Icons.question_mark_rounded,
                  color: Theme.of(context).colorScheme.primary),
              const SizedBox(width: 8),
              Expanded(
                  child: Text('请确认下一步',
                      style: Theme.of(context)
                          .textTheme
                          .titleMedium
                          ?.copyWith(fontWeight: FontWeight.w800))),
              Text('$secondsLeft 秒',
                  style: Theme.of(context).textTheme.labelSmall),
            ]),
            const SizedBox(height: 8),
            Text(info.question),
            const SizedBox(height: 10),
            if (info.options.isEmpty)
              const Text('无可选项，服务端将按超时策略处理。')
            else
              ...info.options.map((o) => ListTile(
                  title: Text(o.label),
                  trailing:
                      o.value == info.defaultValue ? const Text('默认') : null,
                  onTap: () => onAnswer(o.value)))
          ]);
}

class _WaitCard extends StatefulWidget {
  const _WaitCard(
      {required this.info, required this.secondsLeft, required this.onAnswer});
  final WaitForUserInfo info;
  final int secondsLeft;
  final ValueChanged<String> onAnswer;
  @override
  State<_WaitCard> createState() => _WaitCardState();
}

class _WaitCardState extends State<_WaitCard> {
  final controller = TextEditingController();
  @override
  void dispose() {
    controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final text = widget.info.inputType == 'text';
    return Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            Icon(Icons.pause_circle_outline_rounded,
                color: Theme.of(context).colorScheme.primary),
            const SizedBox(width: 8),
            Expanded(
                child: Text('等待你的输入',
                    style: Theme.of(context)
                        .textTheme
                        .titleMedium
                        ?.copyWith(fontWeight: FontWeight.w800))),
            Text('${widget.secondsLeft} 秒',
                style: Theme.of(context).textTheme.labelSmall),
          ]),
          const SizedBox(height: 8),
          Text(widget.info.prompt),
          if (text)
            Padding(
                padding: const EdgeInsets.only(top: 12),
                child: TextField(
                    controller: controller,
                    decoration:
                        InputDecoration(hintText: widget.info.placeholder))),
          const SizedBox(height: 12),
          Row(mainAxisAlignment: MainAxisAlignment.end, children: [
            TextButton(
                onPressed: () => widget.onAnswer('cancel'),
                child: Text(widget.info.cancelLabel)),
            FilledButton(
                onPressed: () => widget.onAnswer(
                    text && controller.text.trim().isNotEmpty
                        ? controller.text.trim()
                        : 'done'),
                child: Text(widget.info.confirmLabel))
          ])
        ]);
  }
}

class _Composer extends StatelessWidget {
  const _Composer(
      {required this.controller,
      required this.busy,
      required this.stopping,
      required this.pendingImages,
      required this.quote,
      required this.onClearQuote,
      required this.onRemoveImage,
      required this.onAttach,
      required this.onSend,
      required this.onStop});
  final TextEditingController controller;
  final bool busy, stopping;
  final List<MessageImage> pendingImages;
  final QuoteInfo? quote;
  final VoidCallback onClearQuote;
  final ValueChanged<int> onRemoveImage;
  final VoidCallback onAttach;
  final VoidCallback onSend, onStop;
  @override
  Widget build(BuildContext context) => SafeArea(
      top: false,
      child: Padding(
          padding: const EdgeInsets.fromLTRB(14, 4, 14, 10),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            if (quote != null)
              Row(children: [
                Expanded(
                    child: Text('引用：${quote!.content}',
                        maxLines: 1, overflow: TextOverflow.ellipsis)),
                IconButton(
                    onPressed: onClearQuote,
                    icon: const Icon(Icons.close_rounded))
              ]),
            if (pendingImages.isNotEmpty)
              SizedBox(
                  height: 48,
                  child: ListView.separated(
                      scrollDirection: Axis.horizontal,
                      itemCount: pendingImages.length,
                      separatorBuilder: (_, __) => const SizedBox(width: 6),
                      itemBuilder: (_, index) => Stack(children: [
                            _MessageImageView(
                                image: pendingImages[index], size: 48),
                            Positioned(
                                right: -8,
                                top: -8,
                                child: IconButton(
                                    visualDensity: VisualDensity.compact,
                                    onPressed: () => onRemoveImage(index),
                                    icon: const Icon(Icons.cancel_rounded,
                                        size: 18)))
                          ]))),
            Row(children: [
              IconButton(
                  onPressed: busy ? null : onAttach,
                  tooltip: '添加图片或文件',
                  icon: const Icon(Icons.attach_file_rounded)),
              Expanded(
                  child: TextField(
                      controller: controller,
                      minLines: 1,
                      maxLines: 4,
                      textInputAction: TextInputAction.send,
                      onSubmitted: (_) => onSend(),
                      decoration: InputDecoration(
                          hintText: pendingImages.isEmpty
                              ? '给 Ethan 发消息…'
                              : '已附加 ${pendingImages.length} 张图片'))),
              const SizedBox(width: 6),
              IconButton(
                  onPressed: busy ? onStop : onSend,
                  tooltip: busy ? '停止生成' : '发送消息',
                  style: IconButton.styleFrom(
                      backgroundColor: Theme.of(context).colorScheme.primary,
                      foregroundColor: Theme.of(context).colorScheme.onPrimary),
                  icon: busy
                      ? (stopping
                          ? const SizedBox(
                              width: 18,
                              height: 18,
                              child: CircularProgressIndicator(strokeWidth: 2))
                          : const Icon(Icons.stop_rounded))
                      : const Icon(Icons.arrow_upward_rounded))
            ])
          ])));
}

class _ChatEmptyState extends StatelessWidget {
  const _ChatEmptyState({required this.onOpenSessions});
  final VoidCallback onOpenSessions;

  @override
  Widget build(BuildContext context) => Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 360),
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              CircleAvatar(
                radius: 32,
                backgroundColor: Theme.of(context).colorScheme.primaryContainer,
                child: Icon(Icons.auto_awesome_rounded,
                    size: 30, color: Theme.of(context).colorScheme.primary),
              ),
              const SizedBox(height: 16),
              Text('从一句话开始',
                  style: Theme.of(context)
                      .textTheme
                      .titleLarge
                      ?.copyWith(fontWeight: FontWeight.w800)),
              const SizedBox(height: 8),
              Text('输入你的目标、问题或待办，Ethan 会从这里建立一段新对话。',
                  textAlign: TextAlign.center,
                  style: Theme.of(context).textTheme.bodyMedium),
              const SizedBox(height: 16),
              TextButton.icon(
                  onPressed: onOpenSessions,
                  icon: const Icon(Icons.history_rounded),
                  label: const Text('打开最近对话')),
            ]),
          ),
        ),
      );
}
