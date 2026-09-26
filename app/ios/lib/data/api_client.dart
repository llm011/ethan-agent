import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;

import '../models/app_models.dart';

class ApiException implements Exception {
  const ApiException(this.status, this.message);
  final int status;
  final String message;
  @override
  String toString() => message;
}

/// 单条 SSE 流内部最多连续重连几次。与 [ChatScreen] 自己的「跨流 resume 重连」
/// 叠加：单条流先自愈 4 次，全失败才把错误交给上层，由上层再走它自己的退避。
const int _maxSseRetries = 4;

/// SSE 断流重连的退避间隔（秒）：1s → 2s → 4s → 8s… 封顶 30s。
///
/// 封顶的理由：服务端真挂掉时，不封顶的退避会一直按「每秒一次」打请求，既耗电，
/// 又会在服务恢复的瞬间制造惊群。
Duration reconnectDelay(int attempt) {
  var seconds = 1;
  for (var i = 0; i < attempt; i++) {
    seconds *= 2;
    if (seconds >= 30) return const Duration(seconds: 30);
  }
  return Duration(seconds: seconds);
}

class ChatEvent {
  const ChatEvent({
    this.content,
    this.done = false,
    this.error,
    this.tool,
    this.args,
    this.state,
    this.id,
    this.durationMs,
    this.resultPreview,
    this.resultDetail,
    this.thought,
    this.intent,
    this.subSteps = const [],
    this.usage,
    this.consentRequest = false,
    this.askUserRequest = false,
    this.waitForUserRequest = false,
    this.requestId,
    this.description,
    this.detail,
    this.question,
    this.options = const [],
    this.defaultValue,
    this.timeout,
    this.prompt,
    this.inputType,
    this.placeholder,
    this.confirmLabel,
    this.cancelLabel,
    this.cards = const [],
  });
  final String? content;
  final bool done;
  final String? error;
  final String? tool;
  final String? args, state, id, resultPreview, resultDetail, thought, intent;
  final List<SubToolStep> subSteps;
  final UsageInfo? usage;
  final int? durationMs;
  final bool consentRequest, askUserRequest, waitForUserRequest;
  final String? requestId, description, detail, question, defaultValue;
  final List<AskUserOption> options;
  final int? timeout;
  final String? prompt, inputType, placeholder, confirmLabel, cancelLabel;
  final List<MediaCard> cards;
}

class EthanApiClient {
  EthanApiClient(this.config, {http.Client? client})
      : _client = client ?? http.Client();
  final ApiConfig config;
  final http.Client _client;

  Map<String, String> get _headers => {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        if (config.token.isNotEmpty) 'Authorization': 'Bearer ${config.token}',
      };

  /// Headers for an image loaded by Flutter. Authorization is only returned
  /// for this Ethan server; never leak the bearer token to third-party URLs.
  Map<String, String> headersFor(Uri uri) =>
      uri.origin == Uri.parse(config.origin).origin ? _headers : const {};

  Uri mediaUri(String path, {String? sessionId}) => _uri('files/view', {
        'path': path,
        if (sessionId != null && sessionId.isNotEmpty) 'session_id': sessionId,
      });

  Future<Uint8List> fetchMediaBytes(String path, {String? sessionId}) async {
    final response = await _client.get(mediaUri(path, sessionId: sessionId),
        headers: _headers);
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw ApiException(response.statusCode, '媒体加载失败（${response.statusCode}）');
    }
    return response.bodyBytes;
  }

  Uri _uri(String path, [Map<String, String>? query]) =>
      Uri.parse('${config.apiBase}/${path.replaceFirst(RegExp(r'^/+'), '')}')
          .replace(queryParameters: query);

  Future<dynamic> _request(String method, String path,
      {Object? body, Map<String, String>? query}) async {
    final request = http.Request(method, _uri(path, query))
      ..headers.addAll(_headers);
    if (body != null) request.body = jsonEncode(body);
    final response = await _client.send(request);
    final text = await response.stream.bytesToString();
    dynamic data;
    try {
      data = text.isEmpty ? <String, dynamic>{} : jsonDecode(text);
    } catch (_) {
      data = text;
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      final detail = data is Map ? (data['detail'] ?? data['error']) : null;
      throw ApiException(response.statusCode,
          detail?.toString() ?? '请求失败（${response.statusCode}）');
    }
    return data;
  }

  Future<void> authenticate() async {
    await _request('POST', 'auth', body: {'token': config.token});
  }

  Future<void> health() async => _request('GET', 'health');

  Future<List<ModelEntry>> models() async {
    final data = await _request('GET', 'models');
    final rows = (data is Map ? data['models'] : null) as List? ?? const [];
    return rows
        .whereType<Map>()
        .map((m) => ModelEntry(
              id: m['id']?.toString() ?? '',
              provider: m['provider']?.toString() ?? '',
              description: m['description']?.toString() ?? '',
              aliases:
                  (m['alias'] as List? ?? const []).map((e) => '$e').toList(),
            ))
        .where((m) => m.id.isNotEmpty)
        .toList();
  }

  /// Returns Ethan's server-side default model. Chat requests should honor
  /// this value instead of assuming the first item in `/models` is default.
  Future<String?> defaultModel() async {
    final data = await _request('GET', 'settings/agent');
    if (data is! Map) return null;
    final value = data['default_model']?.toString().trim();
    return value == null || value.isEmpty ? null : value;
  }

  Future<List<ModeEntry>> modes() async {
    final data = await _request('GET', 'modes');
    final rows = (data is Map ? data['modes'] : null) as List? ?? const [];
    return rows
        .whereType<Map>()
        .map((m) => ModeEntry(
              key: m['key']?.toString() ?? '',
              label: m['label']?.toString() ?? '',
              icon: m['icon']?.toString() ?? '',
              accent: m['accent']?.toString() ?? '',
              blurb: m['blurb']?.toString() ?? '',
            ))
        .where((m) => m.key.isNotEmpty)
        .toList();
  }

  Future<List<Session>> sessions({String query = ''}) async {
    final data = await _request('GET', 'sessions', query: {
      'limit': '50',
      'offset': '0',
      if (query.trim().isNotEmpty) 'q': query.trim(),
    });
    final rows = (data is Map ? data['sessions'] : null) as List? ?? const [];
    return rows.whereType<Map>().map(_session).toList();
  }

  Future<Session> createSession({String? model, String? mode}) async {
    final data = await _request('POST', 'sessions', query: {
      if (model != null && model.isNotEmpty) 'model': model,
      if (mode != null && mode.isNotEmpty) 'mode': mode,
    });
    return _session(data as Map);
  }

  Future<SessionDetail> session(String id) async {
    final data =
        await _request('GET', 'sessions/${Uri.encodeComponent(id)}') as Map;
    final messages =
        (data['messages'] as List? ?? const []).whereType<Map>().map((m) {
      final role = m['role']?.toString() ?? 'assistant';
      final steps = m['tool_steps'] as List? ?? const [];
      return ChatMessage(
        text: m['content']?.toString() ?? '',
        isUser: role == 'user',
        time: _time(m['created_at']),
        id: m['id']?.toString(),
        toolSteps: steps
            .whereType<Map>()
            .map((s) => ToolStep(
                  tool: s['tool']?.toString() ?? '',
                  id: s['id']?.toString(),
                  args: s['args']?.toString() ?? '',
                  state: s['state']?.toString() ?? 'done',
                  durationMs: (s['duration_ms'] as num?)?.toInt(),
                  resultPreview: s['result_preview']?.toString(),
                  resultDetail: s['result_detail']?.toString(),
                  thought: s['thought']?.toString(),
                  intent: s['intent']?.toString(),
                  subSteps: (s['sub_steps'] as List? ?? const [])
                      .whereType<Map>()
                      .map((sub) => SubToolStep(
                            tool: sub['tool']?.toString() ?? '',
                            args: sub['args']?.toString() ?? '',
                            state: sub['state']?.toString() ?? 'done',
                            durationMs: (sub['duration_ms'] as num?)?.toInt(),
                            resultPreview: sub['result_preview']?.toString(),
                          ))
                      .toList(),
                ))
            .toList(),
        quote: _quote(m['quote']),
        images:
            (m['images'] as List? ?? const []).whereType<Map>().map((image) {
          final url = image['url']?.toString();
          return MessageImage(
            data: image['data']?.toString(),
            mediaType: image['media_type']?.toString(),
            url: url,
            displayUrl: image['display_url']?.toString() ??
                (url == null
                    ? null
                    : url.startsWith('http')
                        ? url
                        : '${config.apiBase}/${url.replaceFirst(RegExp(r'^/+'), '')}'),
          );
        }).toList(),
        cards: _cards(m['cards']),
        usage: _usage(m['usage']),
      );
    }).toList();
    return SessionDetail(
      id: data['id']?.toString() ?? id,
      title: data['title']?.toString() ?? '新对话',
      model: data['model']?.toString() ?? '',
      mode: data['mode']?.toString(),
      messages: messages,
    );
  }

  Future<void> renameSession(String id, String title) async => _request(
        'PATCH',
        'sessions/${Uri.encodeComponent(id)}',
        body: {'title': title},
      );

  Future<void> deleteSession(String id) async =>
      _request('DELETE', 'sessions/${Uri.encodeComponent(id)}');

  Future<void> pinSession(String id) async =>
      _request('POST', 'sessions/${Uri.encodeComponent(id)}/pin');

  Future<void> unpinSession(String id) async =>
      _request('DELETE', 'sessions/${Uri.encodeComponent(id)}/pin');

  Future<List<Session>> pinnedSessions() async {
    final data = await _request('GET', 'sessions/pinned');
    final rows = (data is Map ? data['sessions'] : null) as List? ?? const [];
    return rows.whereType<Map>().map(_session).toList();
  }

  // Android EthanApiService parity: sessions and chat controls.
  Future<Map<String, dynamic>> compactSession(String id) async =>
      Map<String, dynamic>.from(
          await _request('POST', 'sessions/${Uri.encodeComponent(id)}/compact')
              as Map);
  Future<Map<String, dynamic>> regenerateTitle(String id) async =>
      Map<String, dynamic>.from(await _request(
          'POST', 'sessions/${Uri.encodeComponent(id)}/regen-title') as Map);
  Future<Map<String, dynamic>> summarizeSession(String id) async =>
      Map<String, dynamic>.from(
          await _request('POST', 'sessions/${Uri.encodeComponent(id)}/summary')
              as Map);
  Future<Map<String, dynamic>> deleteMessage(String id, int messageId) async =>
      Map<String, dynamic>.from(await _request('DELETE',
          'sessions/${Uri.encodeComponent(id)}/messages/$messageId') as Map);
  Future<Map<String, dynamic>> batchGetAnnotations(String ids) async =>
      Map<String, dynamic>.from(
          await _request('GET', 'annotations/batch', query: {'ids': ids})
              as Map);
  Future<Map<String, dynamic>> deleteAnnotation(int id) async =>
      Map<String, dynamic>.from(
          await _request('DELETE', 'annotations/$id') as Map);
  Future<Map<String, dynamic>> getDeck(String path,
          {String sessionId = ''}) async =>
      Map<String, dynamic>.from(await _request('GET', 'files/deck', query: {
        'path': path,
        'session_id': sessionId,
      }) as Map);
  Future<Map<String, dynamic>> stopChat(String id) async =>
      Map<String, dynamic>.from(await _request('POST', 'chat/$id/stop') as Map);
  Future<Map<String, dynamic>> injectMessage(
          String id, Map<String, dynamic> body) async =>
      Map<String, dynamic>.from(
          await _request('POST', 'chat/$id/inject', body: body) as Map);

  Future<Map<String, dynamic>> getJson(String path,
          {Map<String, String>? query}) async =>
      Map<String, dynamic>.from(
          await _request('GET', path, query: query) as Map);
  Future<Map<String, dynamic>> postJson(String path,
          [Map<String, dynamic>? body, Map<String, String>? query]) async =>
      Map<String, dynamic>.from(
          await _request('POST', path, body: body, query: query) as Map);
  Future<Map<String, dynamic>> patchJson(String path,
          [Map<String, dynamic>? body]) async =>
      Map<String, dynamic>.from(
          await _request('PATCH', path, body: body) as Map);
  Future<Map<String, dynamic>> putJson(String path,
          [Map<String, dynamic>? body]) async =>
      Map<String, dynamic>.from(await _request('PUT', path, body: body) as Map);
  Future<Map<String, dynamic>> deleteJson(String path) async =>
      Map<String, dynamic>.from(await _request('DELETE', path) as Map);

  Future<Map<String, dynamic>> uploadFile(
      List<int> bytes, String fileName, String mimeType) async {
    final request = http.MultipartRequest('POST', _uri('upload'))
      ..headers.addAll(_headers)
      ..files.add(http.MultipartFile.fromBytes('file', bytes,
          filename: fileName, contentType: _mediaType(mimeType)));
    final response = await _client.send(request);
    final text = await response.stream.bytesToString();
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw ApiException(response.statusCode, text.isEmpty ? '上传失败' : text);
    }
    final value = text.trim().isEmpty ? <String, dynamic>{} : jsonDecode(text);
    return Map<String, dynamic>.from(value as Map);
  }

  http.MediaType? _mediaType(String value) {
    final parts = value.split('/');
    return parts.length == 2 ? http.MediaType(parts[0], parts[1]) : null;
  }

  /// 发起一轮生成（POST /chat + SSE 响应）。
  ///
  /// **刻意不套 [_resilientSse]**：POST /chat 不是幂等的 —— 它「创建并运行一轮生成」。
  /// 响应中途丢掉时服务端其实已经开跑了，重发会开出第二轮（重复回复、工具重复执行、
  /// token 重复计费）。这种「请求可能已生效」的失败只能由上层核对会话状态来处理
  /// （先 resumeStream 看有没有活跃 run，再决定要不要重发），传输层不能盲重试。
  /// 需要自动重连的是 [resumeStream]，那个端点是幂等的「从头回放」。
  Stream<ChatEvent> chat(
      {required String text,
      required String sessionId,
      String? model,
      String? mode,
      List<ChatMessage>? history,
      QuoteInfo? quote,
      List<MessageImage> images = const []}) async* {
    final request = http.Request('POST', _uri('chat'))
      ..headers.addAll({..._headers, 'Accept': 'text/event-stream'})
      ..body = jsonEncode({
        'messages': (history == null || history.isEmpty)
            ? [
                _messagePayload(ChatMessage(text: text, isUser: true, time: ''),
                    images: images)
              ]
            : history
                .map((m) => _messagePayload(m,
                    images: m == history.last ? images : const []))
                .toList(),
        'stream': true,
        'session_id': sessionId,
        if (quote != null)
          'quote': {'role': quote.role, 'content': quote.content},
        if (model != null && model.isNotEmpty) 'model': model,
        if (mode != null && mode.isNotEmpty) 'mode': mode,
      });
    final response = await _client.send(request);
    if (response.statusCode < 200 || response.statusCode >= 300) {
      final body = await response.stream.bytesToString();
      throw ApiException(response.statusCode,
          body.isEmpty ? '发送失败（${response.statusCode}）' : body);
    }
    var pending = '';
    await for (final chunk in response.stream.transform(utf8.decoder)) {
      pending += chunk;
      final lines = pending.split('\n');
      pending = lines.removeLast();
      for (final line in lines) {
        if (!line.startsWith('data:')) continue;
        final payload = line.substring(5).trim();
        if (payload.isEmpty || payload == '[DONE]') continue;
        try {
          final value = jsonDecode(payload);
          if (value is! Map) continue;
          yield _event(value);
        } catch (_) {}
      }
    }
  }

  /// 重连一个仍在进行的生成。
  ///
  /// [hasProgress] 告诉客户端「这是一次接续，不是新建一条空流」：本地已经有渲染进度时，
  /// 首连失败也值得在流内部自动重试一次 —— 刚切回前台那几秒网络常常还没就绪。
  ///
  /// 该端点每次都是「从头回放 + 继续推」，天然幂等，所以重试是安全的。
  Stream<ChatEvent> resumeStream(String id, {bool hasProgress = false}) =>
      _resilientSse(
        () => _sse('chat/${Uri.encodeComponent(id)}/stream', method: 'GET'),
        hasEmittedContent: hasProgress,
      );

  /// 单次健康检查（`GET /health`）。
  ///
  /// 用于「切回前台主动探活」：长连接被系统挂起后客户端收不到任何断线通知，
  /// 只能主动问一次服务端还在不在。失败一律返回 false，调用方据此判定离线。
  ///
  /// 不用 `_request`（它会解析 body 且把非 2xx 抛异常）：探活只关心「通没通」，
  /// 一个 500 响应同样说明**服务端是活的**，不该被判成离线 —— 用 `_request` 会把
  /// 「服务器活着但内部报错」误报成网络断开，把用户引向错误的排查方向。
  Future<bool> health() async {
    try {
      final request = http.Request('GET', _uri('health'))..headers.addAll(_headers);
      final response = await _client.send(request);
      await response.stream.drain<void>();
      return response.statusCode >= 200 && response.statusCode < 300;
    } catch (_) {
      return false;
    }
  }

  Future<void> inject(String id, String content) async {
    await injectMessage(id, {'content': content});
  }

  Future<void> respondConsent(String requestId, bool allowed) async =>
      _request('POST', 'consent/${Uri.encodeComponent(requestId)}',
          body: {'allowed': allowed});

  Future<void> respondAskUser(String requestId, String value) async =>
      _request('POST', 'ask-user/${Uri.encodeComponent(requestId)}',
          body: {'value': value});

  Future<void> respondWaitForUser(String requestId, String value) async =>
      _request('POST', 'wait-for-user/${Uri.encodeComponent(requestId)}',
          body: {'value': value});

  /// 断线后按指数退避重连（1s / 2s / 4s… 封顶 30s），**同一条流内**完成，
  /// 调用方感知不到中间断过。
  ///
  /// 为什么必须做：移动端的长连接会在服务端重启、Wi-Fi↔蜂窝 切换、App 进后台被系统
  /// 冻结时断开。没有自动重连时，断点之后的流就是一条干流 —— 界面永久停在「离线」，
  /// 除非用户手动点重连。
  ///
  /// 只对「已经产出过内容」的流生效（首连就失败更像配置错误 —— 地址填错、服务没起，
  /// 无限重试会把用户锁在一个永远转圈的界面里，报错更诚实）。[hasEmittedContent]
  /// 让调用方把「本地已有进度」也算作已产出，覆盖「切回前台接续」这种首连即失败但
  /// 确实有活跃 run 的场景。
  Stream<ChatEvent> _resilientSse(
    Stream<ChatEvent> Function() open, {
    bool hasEmittedContent = false,
  }) async* {
    var attempt = 0;
    var emitted = hasEmittedContent;
    while (true) {
      try {
        await for (final event in open()) {
          emitted = true;
          yield event;
        }
        return;
      } catch (e) {
        // 拿到 HTTP 响应说明服务端在工作，4xx/5xx 是业务语义，重连只会再拿一遍。
        // 例外是 5xx/408/429 —— 服务端自己的临时状态，值得退避重试。
        final retryable = e is ApiException
            ? (e.status >= 500 || e.status == 408 || e.status == 429)
            : true;
        if (!retryable || !emitted || attempt >= _maxSseRetries) rethrow;
        await Future<void>.delayed(reconnectDelay(attempt));
        attempt += 1;
      }
    }
  }

  Stream<ChatEvent> _sse(String path,
      {String method = 'GET', Map<String, dynamic>? body}) async* {
    final request = http.Request(method, _uri(path))
      ..headers.addAll({..._headers, 'Accept': 'text/event-stream'});
    if (body != null) request.body = jsonEncode(body);
    final response = await _client.send(request);
    if (response.statusCode == 204) return;
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw ApiException(response.statusCode, '流式请求失败（${response.statusCode}）');
    }
    var pending = '';
    await for (final chunk in response.stream.transform(utf8.decoder)) {
      pending += chunk;
      final lines = pending.split('\n');
      pending = lines.removeLast();
      for (final line in lines) {
        if (!line.startsWith('data:')) continue;
        final payload = line.substring(5).trim();
        if (payload.isEmpty || payload == '[DONE]') continue;
        try {
          final value = jsonDecode(payload);
          if (value is Map) yield _event(value);
        } catch (_) {}
      }
    }
  }

  ChatEvent _event(Map value) => ChatEvent(
        content: value['content']?.toString(),
        done: value['done'] == true,
        error: value['error']?.toString(),
        tool: value['tool']?.toString(),
        args: value['args']?.toString(),
        state: value['state']?.toString(),
        id: value['id']?.toString(),
        durationMs: (value['duration_ms'] as num?)?.toInt(),
        resultPreview: value['result_preview']?.toString(),
        resultDetail: value['result_detail']?.toString(),
        thought: value['thought']?.toString(),
        intent: value['intent']?.toString(),
        subSteps: (value['sub_steps'] as List? ?? const [])
            .whereType<Map>()
            .map((sub) => SubToolStep(
                  tool: sub['tool']?.toString() ?? '',
                  args: sub['args']?.toString() ?? '',
                  state: sub['state']?.toString() ?? 'done',
                  durationMs: (sub['duration_ms'] as num?)?.toInt(),
                  resultPreview: sub['result_preview']?.toString(),
                ))
            .toList(),
        usage: _usage(value['usage']),
        consentRequest: value['consent_request'] == true,
        askUserRequest: value['ask_user_request'] == true,
        waitForUserRequest: value['wait_for_user_request'] == true,
        requestId: value['request_id']?.toString(),
        description: value['description']?.toString(),
        detail: value['detail']?.toString(),
        question: value['question']?.toString(),
        options: (value['options'] as List? ?? const [])
            .whereType<Map>()
            .map((o) => AskUserOption(
                label: o['label']?.toString() ?? '',
                value: o['value']?.toString() ?? ''))
            .toList(),
        defaultValue: value['default']?.toString(),
        timeout: (value['timeout'] as num?)?.toInt(),
        prompt: value['prompt']?.toString(),
        inputType: value['input_type']?.toString(),
        placeholder: value['placeholder']?.toString(),
        confirmLabel: value['confirm_label']?.toString(),
        cancelLabel: value['cancel_label']?.toString(),
        cards: _cards(value['cards']),
      );

  Session _session(Map row) => Session(
        id: row['id']?.toString() ?? '',
        title: row['title']?.toString() ?? '新对话',
        summary: row['snippet']?.toString() ?? '',
        time: _time(row['updated_at']),
        model: row['model']?.toString() ?? '',
        source: row['source']?.toString() ?? 'web',
        mode: row['mode']?.toString(),
        pinnedAt: (row['pinned_at'] as num?)?.toInt() ?? 0,
      );

  Map<String, dynamic> _messagePayload(ChatMessage message,
          {List<MessageImage> images = const []}) =>
      {
        'role': message.isUser ? 'user' : 'assistant',
        'content': message.text,
        if (message.quote != null)
          'quote': {
            'role': message.quote!.role,
            'content': message.quote!.content
          },
        if (images.isNotEmpty)
          'images': images
              .map((image) => {
                    if (image.data != null) 'data': image.data,
                    if (image.mediaType != null) 'media_type': image.mediaType,
                  })
              .toList(),
      };

  QuoteInfo? _quote(Object? value) => value is Map && value['content'] != null
      ? QuoteInfo(
          role: value['role']?.toString() ?? 'user',
          content: value['content'].toString())
      : null;

  UsageInfo? _usage(Object? value) => value is Map
      ? UsageInfo(
          input: (value['input'] as num?)?.toInt() ?? 0,
          output: (value['output'] as num?)?.toInt() ?? 0,
          cache: (value['cache'] as num?)?.toInt() ?? 0)
      : null;

  List<MediaCard> _cards(Object? value) => (value as List? ?? const [])
      .whereType<Map>()
      .map((raw) => MediaCard(
            type: raw['type']?.toString() ?? '',
            path: raw['path']?.toString() ?? '',
            title: raw['title']?.toString() ??
                raw['filename']?.toString() ??
                raw['name']?.toString() ??
                '',
            mime:
                raw['mime']?.toString() ?? raw['media_type']?.toString() ?? '',
            kind: raw['kind']?.toString() ?? '',
            projectDir: raw['project_dir']?.toString(),
            url: raw['url']?.toString() ?? '',
            localPath: raw['local_path']?.toString() ?? '',
          ))
      .where((card) => card.type.isNotEmpty)
      .toList();

  Future<OnboardingStatus> onboardingStatus() async {
    final value = await getJson('onboarding/status');
    return OnboardingStatus(
        firstTime: value['first_time'] == true,
        message: value['message']?.toString() ?? '');
  }

  Future<Map<String, dynamic>> completeOnboarding(
          String agentName, String userInfo) =>
      postJson('onboarding/complete',
          {'agent_name': agentName, 'user_info': userInfo});

  String _time(Object? value) {
    final seconds = value is num ? value.toInt() : int.tryParse('$value');
    if (seconds == null || seconds <= 0) return '';
    final date = DateTime.fromMillisecondsSinceEpoch(seconds * 1000);
    final now = DateTime.now();
    if (date.year == now.year &&
        date.month == now.month &&
        date.day == now.day) {
      return '${date.hour.toString().padLeft(2, '0')}:${date.minute.toString().padLeft(2, '0')}';
    }
    return '${date.month}月${date.day}日';
  }

  void close() => _client.close();
}
