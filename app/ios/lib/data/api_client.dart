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

  Stream<ChatEvent> resumeStream(String id) =>
      _sse('chat/${Uri.encodeComponent(id)}/stream', method: 'GET');

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
