import 'package:ethan_ios/models/app_models.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('normalizes pasted server URLs like Android ServerUrlUtils', () {
    expect(
        const ApiConfig(
                baseUrl: 'http://server.example:8900/api/chat?x=1', token: '')
            .apiBase,
        'http://server.example:8900/api');
    expect(
        const ApiConfig(
                baseUrl:
                    'http://127.0.0.1:8900https://remote.example:9443/settings',
                token: '')
            .apiBase,
        'https://remote.example:9443/api');
  });

  test('rejects non HTTP(S) server URLs', () {
    expect(
        () =>
            const ApiConfig(baseUrl: 'ftp://server.example', token: '').apiBase,
        throwsFormatException);
  });
}
