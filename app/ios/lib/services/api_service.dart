import 'dart:async';
import 'dart:convert';
import 'dart:io';

import '../models/app_models.dart';

/// HTTP client for the same `/api` contract used by the Android Ktor client.
///
/// The client intentionally owns no cached data: every page asks the server for
/// its current state and therefore never falls back to fixture or mock content.
class EthanApiService {
  EthanApiService(this._config);

  final ApiConfig _config;

  Future<List<ResourceItem>> fetchResources(String kind,
      {String query = ''}) async {
    switch (kind) {
      case 'memory':
        final body = await getJson('memory/facts');
        return _asList(body['facts']).map((value) {
          final item = _asMap(value);
          return ResourceItem(
            title: _string(item['content'], fallback: '未命名记忆'),
            subtitle: [
              _string(item['category']),
              _string(item['source']),
              _number(item['confidence']) == null
                  ? ''
                  : '置信度 ${_number(item['confidence'])!.toStringAsFixed(2)}',
            ].where((part) => part.isNotEmpty).join(' · '),
            detail: _string(item['content']),
          );
        }).toList();
      case 'knowledge':
        final body = await getJson('knowledge',
            query: query.isEmpty ? null : {'q': query});
        return _asList(body['items']).map((value) {
          final item = _asMap(value);
          final tags = _asList(item['tags']).map((tag) => '$tag').join(' · ');
          return ResourceItem(
            title: _string(item['title'], fallback: '未命名知识'),
            subtitle: tags.isEmpty ? _string(item['source']) : tags,
            detail: _string(item['content']),
          );
        }).toList();
      case 'skills':
        final body = await getJson('skills');
        return _asList(body['skills']).map((value) {
          final item = _asMap(value);
          final trigger =
              _asList(item['trigger']).map((value) => '$value').join(' · ');
          return ResourceItem(
            title: _string(item['name'], fallback: '未命名技能'),
            subtitle: trigger.isEmpty ? _string(item['description']) : trigger,
            detail: _string(item['content'],
                fallback: _string(item['description'])),
          );
        }).toList();
      case 'docs':
        final body = await getJson('docs');
        return _asList(body['docs']).map((value) {
          final item = _asMap(value);
          final slug = _string(item['slug']);
          return ResourceItem(
            id: slug,
            title: _string(item['title'], fallback: slug),
            subtitle: _string(item['filename']),
          );
        }).toList();
      case 'logs':
        final body =
            await getJson('logs', query: query.isEmpty ? null : {'q': query});
        return _string(body['content'])
            .split('\n')
            .where((line) => line.trim().isNotEmpty)
            .map((line) =>
                ResourceItem(title: line, subtitle: 'backend', detail: line))
            .toList();
      default:
        throw ArgumentError.value(kind, 'kind', 'Unknown resource type');
    }
  }

  Future<String> fetchDoc(String slug) async =>
      _string((await getJson('docs/$slug'))['content']);

  Future<List<AgendaItem>> fetchAgenda() async {
    final body = await getJson('agenda');
    return _asList(body['events']).map((value) {
      final event = _asMap(value);
      return AgendaItem(
        id: _string(event['id']),
        title: _string(event['title'], fallback: '未命名日程'),
        when: _string(event['when']),
        note: _string(event['note']),
        repeat: _string(event['repeat']),
        weekdays: _asList(event['weekdays'])
            .map((day) => int.tryParse('$day'))
            .whereType<int>()
            .toList(),
        status: _string(event['status']),
        completion: _string(event['completion']),
        nextRunTime: _string(event['next_run_time']),
      );
    }).toList();
  }

  Future<List<ScheduleItem>> fetchSchedules() async {
    final body = await getJson('schedule');
    return _asList(body['jobs']).map((value) {
      final job = _asMap(value);
      return ScheduleItem(
        id: _string(job['id']),
        title: _string(job['title'], fallback: _string(job['id'])),
        trigger: _string(job['trigger']),
        nextRunTime: _string(job['next_run_time']),
        status: _string(job['status'], fallback: 'active'),
        sessionId: _string(job['session_id']),
      );
    }).toList();
  }

  Future<void> updateScheduleState(String id, bool enabled) => patchJson(
      'schedule/${_segment(id)}', {'state': enabled ? 'active' : 'paused'});

  // Complete Android EthanApiService surface.  The payloads intentionally stay
  // as JSON maps: the server owns these schemas and this avoids lossy iOS-only
  // DTO conversions when new backend fields are added.
  Future<Map<String, dynamic>> auth(Map<String, dynamic> body) =>
      postJson('auth', body);
  Future<Map<String, dynamic>> health() => getJson('health');
  Future<Map<String, dynamic>> getSessions() => getJson('sessions');
  Future<Map<String, dynamic>> getModels() => getJson('models');
  Future<Map<String, dynamic>> addModel(Map<String, dynamic> model) =>
      postJson('models', model);
  Future<Map<String, dynamic>> updateModel(
          String provider, String modelId, Map<String, dynamic> model) =>
      putJson('models/${_segment(provider)}/${_segment(modelId)}', model);
  Future<Map<String, dynamic>> deleteModel(String provider, String modelId) =>
      deleteJson('models/${_segment(provider)}/${_segment(modelId)}');
  Future<Map<String, dynamic>> discoverModels(Map<String, dynamic> body) =>
      postJson('models/discover', body);
  Future<Map<String, dynamic>> getModes() => getJson('modes');

  Future<Map<String, dynamic>> poll() => getJson('poll');
  Future<Map<String, dynamic>> respondConsent(
          String requestId, Map<String, dynamic> body) =>
      postJson('consent/${_segment(requestId)}', body);
  Future<Map<String, dynamic>> pinSession(String id) =>
      postJson('sessions/${_segment(id)}/pin');
  Future<Map<String, dynamic>> unpinSession(String id) =>
      deleteJson('sessions/${_segment(id)}/pin');
  Future<Map<String, dynamic>> getPinnedSessions() =>
      getJson('sessions/pinned');
  Future<Map<String, dynamic>> respondAskUser(
          String requestId, Map<String, dynamic> body) =>
      postJson('ask-user/${_segment(requestId)}', body);
  Future<Map<String, dynamic>> respondWaitForUser(
          String requestId, Map<String, dynamic> body) =>
      postJson('wait-for-user/${_segment(requestId)}', body);

  Future<Map<String, dynamic>> getAgentSettings() => getJson('settings/agent');
  Future<Map<String, dynamic>> updateAgentSettings(
          Map<String, dynamic> patch) =>
      patchJsonResult('settings/agent', patch);
  Future<Map<String, dynamic>> getProviderSettings() =>
      getJson('settings/providers');
  Future<Map<String, dynamic>> updateProviderSettings(
          Map<String, dynamic> patch) =>
      patchJsonResult('settings/providers', patch);
  Future<Map<String, dynamic>> getSystemSettings() =>
      getJson('settings/system');
  Future<Map<String, dynamic>> updateSystemSettings(
          Map<String, dynamic> patch) =>
      patchJsonResult('settings/system', patch);
  Future<Map<String, dynamic>> getUserProfile() => getJson('settings/profile');
  Future<Map<String, dynamic>> updateUserProfile(Map<String, dynamic> patch) =>
      patchJsonResult('settings/profile', patch);
  Future<Map<String, dynamic>> getSystemPromptPreview() =>
      getJson('system-prompt-preview');

  Future<Map<String, dynamic>> getFacts() => getJson('memory/facts');
  Future<Map<String, dynamic>> updateFact(
          String id, Map<String, dynamic> body) =>
      patchJsonResult('memory/facts/${_segment(id)}', body);
  Future<Map<String, dynamic>> deleteFact(String id) =>
      deleteJson('memory/facts/${_segment(id)}');
  Future<Map<String, dynamic>> getEpisodes() => getJson('memory/episodes');
  Future<Map<String, dynamic>> deleteEpisode(String id) =>
      deleteJson('memory/episodes/${_segment(id)}');
  Future<Map<String, dynamic>> getProcedures() => getJson('memory/procedures');
  Future<Map<String, dynamic>> deleteProcedure(String id) =>
      deleteJson('memory/procedures/${_segment(id)}');
  Future<Map<String, dynamic>> getInsights({int limit = 20, int offset = 0}) =>
      getJson('memory/insights',
          query: {'limit': '$limit', 'offset': '$offset'});
  Future<Map<String, dynamic>> getInsightsByDate(String date) =>
      getJson('memory/insights/date/${_segment(date)}');
  Future<Map<String, dynamic>> consolidateMemory() =>
      postJson('memory/consolidate');
  Future<Map<String, dynamic>> getRecords(
          {String? type,
          String? status,
          String? domain,
          int limit = 50,
          int offset = 0}) =>
      getJson('memory/records',
          query: _query({
            'type': type,
            'status': status,
            'domain': domain,
            'limit': '$limit',
            'offset': '$offset'
          }));
  Future<Map<String, dynamic>> searchRecords(String text,
          {String? type, String? domain, String? status, int limit = 20}) =>
      getJson('memory/records/search',
          query: _query({
            'q': text,
            'type': type,
            'domain': domain,
            'status': status,
            'limit': '$limit'
          }));
  Future<Map<String, dynamic>> getRecord(String id) =>
      getJson('memory/records/${_segment(id)}');
  Future<Map<String, dynamic>> getRecordEvidence(String id) =>
      getJson('memory/records/${_segment(id)}/evidence');
  Future<Map<String, dynamic>> updateRecord(
          String id, Map<String, dynamic> body) =>
      patchJsonResult('memory/records/${_segment(id)}', body);
  Future<Map<String, dynamic>> deleteRecord(String id) =>
      deleteJson('memory/records/${_segment(id)}');
  Future<Map<String, dynamic>> confirmRecord(String id) =>
      postJson('memory/records/${_segment(id)}/confirm');
  Future<Map<String, dynamic>> consolidateRecords({String? targetDate}) =>
      postJson('memory/records/consolidate', null,
          _query({'target_date': targetDate}));
  Future<Map<String, dynamic>> getDailySummaries(
          {String? domain, int limit = 30}) =>
      getJson('memory/records/summaries',
          query: _query({'domain': domain, 'limit': '$limit'}));
  Future<Map<String, dynamic>> getDailySummaryByDate(String date,
          {String? domain}) =>
      getJson('memory/records/summaries/${_segment(date)}',
          query: _query({'domain': domain}));

  Future<Map<String, dynamic>> getSchedules() => getJson('schedule');
  Future<Map<String, dynamic>> patchSchedule(
          String id, Map<String, dynamic> body) =>
      patchJsonResult('schedule/${_segment(id)}', body);
  Future<Map<String, dynamic>> deleteSchedule(String id) =>
      deleteJson('schedule/${_segment(id)}');
  Future<Map<String, dynamic>> createSchedule(Map<String, dynamic> body) =>
      postJson('schedule', body);
  Future<Map<String, dynamic>> triggerSchedule(String id) =>
      postJson('schedule/${_segment(id)}/trigger');
  Future<Map<String, dynamic>> getTimelineStatus() =>
      getJson('schedule/timeline-status');
  Future<Map<String, dynamic>> syncTimelines() =>
      postJson('schedule/sync-timelines');
  Future<Map<String, dynamic>> timelineLifecycle(String id, String action) =>
      postJson('schedule/timeline/${_segment(id)}/${_segment(action)}');
  Future<Map<String, dynamic>> exportTimeline(Map<String, dynamic> body) =>
      postJson('schedule/timeline-export', body);
  Future<Map<String, dynamic>> importTimeline(Map<String, dynamic> body) =>
      postJson('schedule/timeline-import', body);
  Future<Map<String, dynamic>> validateTimeline(Map<String, dynamic> body) =>
      postJson('schedule/timeline-validate', body);
  Future<Map<String, dynamic>> syncTimelineToLark(String id) =>
      postJson('schedule/timeline/${_segment(id)}/sync-lark');
  Future<Map<String, dynamic>> cleanupTimelineLark(String id) =>
      postJson('schedule/timeline/${_segment(id)}/cleanup-lark');

  Future<Map<String, dynamic>> getAgenda() => getJson('agenda');
  Future<Map<String, dynamic>> createAgenda(Map<String, dynamic> body) =>
      postJson('agenda', body);
  Future<Map<String, dynamic>> patchAgenda(
          String id, Map<String, dynamic> body) =>
      patchJsonResult('agenda/${_segment(id)}', body);
  Future<Map<String, dynamic>> deleteAgenda(String id) =>
      deleteJson('agenda/${_segment(id)}');
  Future<Map<String, dynamic>> setAgendaEnabled(Map<String, dynamic> body) =>
      putJson('agenda/enabled', body);

  Future<Map<String, dynamic>> getKnowledge({String? query, String? mode}) =>
      getJson('knowledge', query: _query({'q': query, 'mode': mode}));
  Future<Map<String, dynamic>> searchKnowledge(String query,
          {int limit = 10, bool semantic = true}) =>
      getJson('knowledge/search',
          query: {'q': query, 'limit': '$limit', 'semantic': '$semantic'});
  Future<Map<String, dynamic>> addKnowledge(Map<String, dynamic> body) =>
      postJson('knowledge', body);
  Future<Map<String, dynamic>> updateKnowledge(
          String source, Map<String, dynamic> body) =>
      putJson('knowledge/${_segment(source)}', body);
  Future<Map<String, dynamic>> deleteKnowledge(String source) =>
      deleteJson('knowledge/${_segment(source)}');
  Future<Map<String, dynamic>> validateKnowledgeBackend(
          Map<String, dynamic> body) =>
      postJson('settings/knowledge/validate', body);

  Future<Map<String, dynamic>> getSkills() => getJson('skills');
  Future<Map<String, dynamic>> getSkill(String name) =>
      getJson('skills/${_segment(name)}');
  Future<Map<String, dynamic>> saveSkill(Map<String, dynamic> body) =>
      postJson('skills', body);
  Future<Map<String, dynamic>> deleteSkill(String name) =>
      deleteJson('skills/${_segment(name)}');

  Future<Map<String, dynamic>> getOnboardingStatus() =>
      getJson('onboarding/status');
  Future<Map<String, dynamic>> completeOnboarding(Map<String, dynamic> body) =>
      postJson('onboarding/complete', body);
  Future<Map<String, dynamic>> getChannels() => getJson('channels');
  Future<Map<String, dynamic>> patchChannel(Map<String, dynamic> body) =>
      patchJsonResult('channels', body);
  Future<Map<String, dynamic>> getLarkDepsStatus() =>
      getJson('channels/lark/deps-status');
  Future<Map<String, dynamic>> installLarkDeps() =>
      postJson('channels/lark/install-deps');
  Future<Map<String, dynamic>> getDocsList() => getJson('docs');
  Future<Map<String, dynamic>> getDoc(String slug) =>
      getJson('docs/${_segment(slug)}');
  Future<Map<String, dynamic>> getApiKeys() => getJson('api-keys');
  Future<Map<String, dynamic>> createApiKey(Map<String, dynamic> body) =>
      postJson('api-keys', body);
  Future<Map<String, dynamic>> deleteApiKey(String id) =>
      deleteJson('api-keys/${_segment(id)}');
  Future<Map<String, dynamic>> getLogs(
          {String type = 'backend', int lines = 500, String? query}) =>
      getJson('logs',
          query: _query({'type': type, 'lines': '$lines', 'q': query}));
  Future<Map<String, dynamic>> getToolTiers({String? model}) =>
      getJson('tool-tiers', query: _query({'model': model}));
  Future<Map<String, dynamic>> getFastRules() => getJson('fast-rules');
  Future<Map<String, dynamic>> getFastRuleOptions({String? model}) =>
      getJson('fast-rules/options', query: _query({'model': model}));
  Future<Map<String, dynamic>> updateFastRules(Map<String, dynamic> body) =>
      patchJsonResult('fast-rules', body);
  Future<Map<String, dynamic>> getBackgroundTasks() =>
      getJson('background-tasks');
  Future<Map<String, dynamic>> stopBackgroundTask(String id) =>
      postJson('background-tasks/${_segment(id)}/stop');
  Future<Map<String, dynamic>> batchGetAnnotations(String ids) =>
      getJson('annotations/batch', query: {'ids': ids});
  Future<Map<String, dynamic>> getAnnotations(int messageId) =>
      getJson('annotations/$messageId');
  Future<Map<String, dynamic>> createAnnotation(Map<String, dynamic> body) =>
      postJson('annotations', body);
  Future<Map<String, dynamic>> deleteAnnotation(int id) =>
      deleteJson('annotations/$id');
  Future<Map<String, dynamic>> signFiles(Map<String, dynamic> body) =>
      postJson('files/sign', body);
  Future<Map<String, dynamic>> getDeck(String path, {String sessionId = ''}) =>
      getJson('files/deck', query: {'path': path, 'session_id': sessionId});

  Future<List<BackgroundTaskItem>> fetchBackgroundTasks() async {
    final body = await getJson('background-tasks');
    return _asList(body['tasks']).map((value) {
      final task = _asMap(value);
      return BackgroundTaskItem(
        id: _string(task['id']),
        title: _string(task['title'],
            fallback: _string(task['id'], fallback: '未命名任务')),
        status: _string(task['status']),
        result: _string(task['result'] ?? task['output'] ?? task['message']),
        error: _string(task['error']),
        sessionId: _string(task['session_id'] ?? task['sessionId']),
      );
    }).toList();
  }

  Future<Map<String, dynamic>> getJson(String path,
          {Map<String, String>? query}) =>
      _requestJson('GET', path, query: query);

  Future<void> patchJson(String path, Map<String, dynamic> body) async {
    await _requestJson('PATCH', path, body: body);
  }

  Future<Map<String, dynamic>> _requestJson(
    String method,
    String path, {
    Map<String, String>? query,
    Map<String, dynamic>? body,
  }) async {
    final base =
        _config.apiBase.endsWith('/') ? _config.apiBase : '${_config.apiBase}/';
    final uri = Uri.parse(base).resolve(path).replace(queryParameters: query);
    final client = HttpClient();
    try {
      final request = await client
          .openUrl(method, uri)
          .timeout(const Duration(seconds: 30));
      request.headers.set(HttpHeaders.acceptHeader, 'application/json');
      if (_config.token.isNotEmpty) {
        request.headers
            .set(HttpHeaders.authorizationHeader, 'Bearer ${_config.token}');
      }
      if (body != null) {
        request.headers.contentType = ContentType.json;
        request.write(jsonEncode(body));
      }
      final response =
          await request.close().timeout(const Duration(seconds: 30));
      final text = await response.transform(utf8.decoder).join();
      if (response.statusCode < 200 || response.statusCode >= 300) {
        throw EthanApiException(response.statusCode, _errorMessage(text));
      }
      final decoded =
          text.trim().isEmpty ? <String, dynamic>{} : jsonDecode(text);
      if (decoded is! Map) throw const FormatException('服务端返回的 JSON 不是对象');
      return Map<String, dynamic>.from(decoded);
    } on SocketException catch (error) {
      throw EthanApiException(null, '无法连接服务器：${error.message}');
    } on TimeoutException {
      throw const EthanApiException(null, '请求超时，请检查服务器连接');
    } finally {
      client.close(force: true);
    }
  }

  static String _errorMessage(String text) {
    try {
      final body = jsonDecode(text);
      if (body is Map) return _string(body['detail'], fallback: text);
    } catch (_) {}
    return text.isEmpty ? '请求失败' : text;
  }

  static Map<String, dynamic> _asMap(dynamic value) =>
      value is Map ? Map<String, dynamic>.from(value) : const {};
  static List<dynamic> _asList(dynamic value) =>
      value is List ? value : const [];
  static String _string(dynamic value, {String fallback = ''}) =>
      value is String && value.isNotEmpty ? value : fallback;
  static num? _number(dynamic value) =>
      value is num ? value : num.tryParse('$value');

  static String _segment(String value) => Uri.encodeComponent(value);
  static Map<String, String> _query(Map<String, String?> values) =>
      values.entries
          .where((entry) => entry.value != null && entry.value!.isNotEmpty)
          .fold(<String, String>{}, (result, entry) {
        result[entry.key] = entry.value!;
        return result;
      });

  Future<Map<String, dynamic>> patchJsonResult(
          String path, Map<String, dynamic> body) =>
      _requestJson('PATCH', path, body: body);
  Future<Map<String, dynamic>> postJson(String path,
          [Map<String, dynamic>? body, Map<String, String>? query]) =>
      _requestJson('POST', path, body: body, query: query);
  Future<Map<String, dynamic>> putJson(String path,
          [Map<String, dynamic>? body]) =>
      _requestJson('PUT', path, body: body);
  Future<Map<String, dynamic>> deleteJson(String path) =>
      _requestJson('DELETE', path);
}

class EthanApiException implements Exception {
  const EthanApiException(this.statusCode, this.message);
  final int? statusCode;
  final String message;
  @override
  String toString() =>
      statusCode == null ? message : 'HTTP $statusCode：$message';
}

class ResourceItem {
  const ResourceItem(
      {this.id = '',
      required this.title,
      this.subtitle = '',
      this.detail = ''});
  final String id;
  final String title;
  final String subtitle;
  final String detail;
}

class AgendaItem {
  const AgendaItem(
      {required this.id,
      required this.title,
      required this.when,
      required this.note,
      required this.repeat,
      this.weekdays = const [],
      required this.status,
      required this.completion,
      this.nextRunTime = ''});
  final String id, title, when, note, repeat, status, completion, nextRunTime;
  final List<int> weekdays;
}

class ScheduleItem {
  const ScheduleItem(
      {required this.id,
      required this.title,
      required this.trigger,
      required this.nextRunTime,
      required this.status,
      this.sessionId = ''});
  final String id, title, trigger, nextRunTime, status, sessionId;
}

class BackgroundTaskItem {
  const BackgroundTaskItem(
      {required this.id,
      required this.title,
      required this.status,
      this.result = '',
      this.error = '',
      this.sessionId = ''});
  final String id, title, status, result, error, sessionId;
}
