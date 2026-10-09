import 'dart:async';
import 'dart:io';

import '../services/api_service.dart';

typedef RepositoryLoader<T> = Future<T> Function();

/// Thin stale-while-revalidate layer shared by screens that need repeatable
/// server state. It never invents a value: an empty cache always waits for the
/// real Ethan response, while a populated cache is returned immediately and
/// refreshed in the background.
///
/// 「立刻返回旧值」只允许在 [staleAfter] 窗口内发生：窗口外的命中照样立即返回，
/// 但一定会补一次后台刷新。此前这个后台刷新只把结果写进 [_cache]，没人重新读就
/// 永远看不见 —— 表现就是「刷新请求明明发了，界面却一直不动，过很久才突然变新」。
/// 现在 [refresh] 落地后会按 key 通知 [watch] 注册的监听者，由各页面把新数据接回
/// 自己的 FutureBuilder。
class EthanRepository {
  EthanRepository(this.api,
      {this.staleAfter = const Duration(seconds: 30), DateTime Function()? now})
      : now = now ?? DateTime.now;
  final EthanApiService api;

  /// 缓存被当作「新鲜」的时长；超时后的下一次读取会触发后台重校验。
  final Duration staleAfter;
  final DateTime Function() now;

  final Map<String, Object?> _cache = {};
  final Map<String, Future<Object?>> _inFlight = {};
  final Map<String, DateTime> _fetchedAt = {};
  final Map<String, Set<void Function()>> _listeners = {};

  T? peek<T>(String key) => _cache[key] as T?;

  /// 订阅某个 key 的「后台刷新已落地」通知。监听者通常会重新走一遍
  /// [cached] —— 刚落地的数据在 [staleAfter] 内必然命中且不再发起请求，
  /// 因此 通知 → 重读 → 再通知 的环路在这里自然终止。
  void watch(String key, void Function() listener) =>
      _listeners.putIfAbsent(key, () => {}).add(listener);

  void unwatch(String key, void Function() listener) =>
      _listeners[key]?.remove(listener);

  Future<T> cached<T>(String key, RepositoryLoader<T> loader) async {
    final current = peek<T>(key);
    if (current != null) {
      final fetchedAt = _fetchedAt[key];
      final stale =
          fetchedAt == null || now().difference(fetchedAt) > staleAfter;
      // 只有过期才补后台刷新：新鲜期内反复进页面不再打请求（也杜绝
      // 「监听者重读 → 再触发刷新 → 再通知」的自我放大）。
      if (stale) {
        unawaited(refresh(key, loader).catchError((_) => current));
      }
      return current;
    }
    return refresh(key, loader);
  }

  Future<T> refresh<T>(String key, RepositoryLoader<T> loader) async {
    final existing = _inFlight[key];
    if (existing != null) return await existing as T;
    final request = loader().then((value) {
      _cache[key] = value;
      _fetchedAt[key] = now();
      return value as Object?;
    });
    _inFlight[key] = request;
    try {
      final value = await request as T;
      // 成功落地才通知：失败时缓存维持旧值，页面不需要（也没法）拿到新数据。
      for (final listener in (_listeners[key] ?? const {}).toList()) {
        listener();
      }
      return value;
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
