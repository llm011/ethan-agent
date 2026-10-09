import 'package:flutter_test/flutter_test.dart';

import 'package:ethan_ios/data/ethan_repository.dart';
import 'package:ethan_ios/models/app_models.dart';
import 'package:ethan_ios/services/api_service.dart';

void main() {
  test('returns cached value immediately and refreshes stale data', () async {
    // 注入固定时钟：TTL 判定不再依赖真实时间流逝。
    var timestamp = DateTime(2026, 1, 1);
    final repository = _TestRepository(now: () => timestamp);
    var calls = 0;
    final first = await repository.cached('value', () async => ++calls);
    expect(first, 1);
    // 新鲜期内重读：命中缓存，不发起后台刷新。
    final second = await repository.cached('value', () async => ++calls);
    expect(second, 1);
    await Future<void>.delayed(Duration.zero);
    expect(calls, 1);
    // 越过 staleAfter 后重读：立即返回旧值，同时补一次后台刷新。
    timestamp = timestamp.add(const Duration(minutes: 1));
    final third = await repository.cached('value', () async => ++calls);
    expect(third, 1);
    await Future<void>.delayed(Duration.zero);
    expect(calls, 2);
    expect(repository.peek<int>('value'), 2);
  });

  test('notifies watchers only when a refresh lands', () async {
    var timestamp = DateTime(2026, 1, 1);
    final repository = _TestRepository(now: () => timestamp);
    var notified = 0;
    repository.watch('value', () => notified++);
    // 首次加载（缓存为空 → refresh）：落地后通知一次。
    await repository.cached('value', () async => 1);
    await Future<void>.delayed(Duration.zero);
    expect(notified, 1);
    // 新鲜期内命中缓存：不刷新、不再通知 —— 避免监听者重读造成自我放大。
    await repository.cached('value', () async => 2);
    await Future<void>.delayed(Duration.zero);
    expect(notified, 1);
    // 过期后命中：立即返回旧值，后台刷新落地后再通知。
    timestamp = timestamp.add(const Duration(minutes: 1));
    final stale = await repository.cached('value', () async => 2);
    expect(stale, 1);
    await Future<void>.delayed(Duration.zero);
    expect(repository.peek<int>('value'), 2);
    expect(notified, 2);
  });

  test('normalizes backend errors without fabricating a response', () {
    final error =
        EthanRepository.normalize(const EthanApiException(503, '服务暂不可用'));
    expect(error.statusCode, 503);
    expect(error.message, '服务暂不可用');
  });
}

class _TestRepository extends EthanRepository {
  _TestRepository({super.now})
      : super(EthanApiService(const ApiConfig(
            baseUrl: 'http://127.0.0.1:8900', token: 'test')));
}
