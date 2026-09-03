import 'dart:async';
import 'dart:io';

import '../services/api_service.dart';

typedef RepositoryLoader<T> = Future<T> Function();

/// Thin stale-while-revalidate layer shared by screens that need repeatable
/// server state. It never invents a value: an empty cache always waits for the
/// real Ethan response, while a populated cache is returned immediately and
/// refreshed in the background.
class EthanRepository {
  EthanRepository(this.api);
  final EthanApiService api;
  final Map<String, Object?> _cache = {};
  final Map<String, Future<Object?>> _inFlight = {};

  T? peek<T>(String key) => _cache[key] as T?;

  Future<T> cached<T>(String key, RepositoryLoader<T> loader) async {
    final current = peek<T>(key);
    if (current != null) {
      unawaited(refresh(key, loader).catchError((_) => current));
      return current;
    }
    return refresh(key, loader);
  }

  Future<T> refresh<T>(String key, RepositoryLoader<T> loader) async {
    final existing = _inFlight[key];
    if (existing != null) return await existing as T;
    final request = loader().then((value) {
      _cache[key] = value;
      return value as Object?;
    });
    _inFlight[key] = request;
    try {
      return await request as T;
    } finally {
      _inFlight.remove(key);
    }
  }

  Future<List<AgendaItem>> agenda({bool force = false}) => force
      ? refresh('agenda', api.fetchAgenda)
      : cached('agenda', api.fetchAgenda);
  Future<List<ScheduleItem>> schedules({bool force = false}) => force
      ? refresh('schedules', api.fetchSchedules)
      : cached('schedules', api.fetchSchedules);
  Future<Map<String, dynamic>> models() => cached('models', api.getModels);
  Future<Map<String, dynamic>> modes() => cached('modes', api.getModes);
  Future<Map<String, dynamic>> sessions() =>
      cached('sessions', api.getSessions);
  Future<Map<String, dynamic>> facts({bool force = false}) =>
      force ? refresh('facts', api.getFacts) : cached('facts', api.getFacts);
  Future<Map<String, dynamic>> knowledge() =>
      cached('knowledge', () => api.getKnowledge());
  Future<Map<String, dynamic>> skills() => cached('skills', api.getSkills);
  Future<Map<String, dynamic>> agentSettings() =>
      cached('agent_settings', api.getAgentSettings);
  Future<Map<String, dynamic>> records(
          {String? type, String? status, String? domain}) =>
      refresh('records:${type ?? ''}:${status ?? ''}:${domain ?? ''}',
          () => api.getRecords(type: type, status: status, domain: domain));

  static RepositoryException normalize(Object error) {
    if (error is EthanApiException) {
      return RepositoryException(error.statusCode, error.message);
    }
    if (error is SocketException) {
      return RepositoryException(null, '无法连接服务器：${error.message}');
    }
    if (error is TimeoutException) {
      return const RepositoryException(null, '请求超时，请检查服务器连接');
    }
    return RepositoryException(null, error.toString());
  }
}

class RepositoryException implements Exception {
  const RepositoryException(this.statusCode, this.message);
  final int? statusCode;
  final String message;
  @override
  String toString() =>
      statusCode == null ? message : 'HTTP $statusCode：$message';
}
