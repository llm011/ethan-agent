import 'package:flutter_test/flutter_test.dart';

import 'package:ethan_ios/data/ethan_repository.dart';
import 'package:ethan_ios/models/app_models.dart';
import 'package:ethan_ios/services/api_service.dart';

void main() {
  test('returns cached value immediately and refreshes stale data', () async {
    final repository = _TestRepository();
    var calls = 0;
    final first = await repository.cached('value', () async => ++calls);
    expect(first, 1);
    final second = await repository.cached('value', () async => ++calls);
    expect(second, 1);
    await Future<void>.delayed(Duration.zero);
    expect(calls, 2);
    expect(repository.peek<int>('value'), 2);
  });

  test('normalizes backend errors without fabricating a response', () {
    final error =
        EthanRepository.normalize(const EthanApiException(503, '服务暂不可用'));
    expect(error.statusCode, 503);
    expect(error.message, '服务暂不可用');
  });
}

class _TestRepository extends EthanRepository {
  _TestRepository()
      : super(EthanApiService(
            const ApiConfig(baseUrl: 'http://127.0.0.1:8900', token: 'test')));
}
