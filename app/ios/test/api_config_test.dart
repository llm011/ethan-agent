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

  test('session link points at the web page, not the API base', () {
    // 必须是给人看的页面地址：带 /api 的地址在浏览器里只会吐 JSON。
    expect(
        const ApiConfig(baseUrl: 'http://127.0.0.1:8900', token: '')
            .sessionWebUrl('s_20260923_0028_5bc7'),
        'http://127.0.0.1:8900/chat/s_20260923_0028_5bc7/');
    // 粘错的服务器地址（带 /api/chat/）归一化后仍然是干净的 origin。
    expect(
        const ApiConfig(
                baseUrl: 'https://remote.example:9443/api/chat/', token: '')
            .sessionWebUrl('s_1'),
        'https://remote.example:9443/chat/s_1/');
  });

  test('session link is null when there is no session yet', () {
    const config = ApiConfig(baseUrl: 'http://127.0.0.1:8900', token: '');
    expect(config.sessionWebUrl(''), isNull);
    expect(config.sessionWebUrl('   '), isNull);
    expect(config.sessionWebUrl('  s_1  '),
        'http://127.0.0.1:8900/chat/s_1/');
  });
}
