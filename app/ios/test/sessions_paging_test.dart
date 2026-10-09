import 'dart:convert';

import 'package:ethan_ios/data/api_client.dart';
import 'package:ethan_ios/models/app_models.dart';
import 'package:ethan_ios/screens/sessions_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 会话列表分页（上滑加载更多 + footer + 下拉刷新单飞）的 widget 测试。
///
/// 服务端契约：`GET /sessions?limit&offset&q` → `{sessions: [...], total: n}`。
void main() {
  const config = ApiConfig(baseUrl: 'http://127.0.0.1:8900/api', token: 't');

  /// 造一个可分页的 mock 后端：total = 75，每页 50 → 第二页只有 25 条。
  EthanApiClient mockApi({
    required List<http.Request> captured,
    Duration delay = Duration.zero,
  }) =>
      EthanApiClient(
        config,
        client: MockClient((request) async {
          captured.add(request);
          if (delay > Duration.zero) await Future<void>.delayed(delay);
          final offset =
              int.parse(request.url.queryParameters['offset'] ?? '0');
          final limit = int.parse(request.url.queryParameters['limit'] ?? '50');
          if (request.url.path.endsWith('/sessions/pinned')) {
            return http.Response('{"sessions": []}', 200);
          }
          const total = 75;
          final start = offset;
          final end = (offset + limit).clamp(0, total);
          final sessions = [
            for (var i = start; i < end; i++)
              {
                'id': 's-$i',
                'title': '会话 $i',
                'snippet': '',
                'updated_at': 1700000000,
                'source': 'web',
              }
          ];
          return http.Response.bytes(
              utf8.encode(jsonEncode({'sessions': sessions, 'total': total})),
              200,
              headers: {'content-type': 'application/json'});
        }),
      );

  Future<Widget> host(EthanApiClient api) async {
    SharedPreferences.setMockInitialValues({});
    return MaterialApp(home: SessionsScreen(api: api, onOpen: (_) {}));
  }

  testWidgets('loads more on scroll near bottom and shows footer states',
      (tester) async {
    final captured = <http.Request>[];
    final api = mockApi(captured: captured);
    await tester.pumpWidget(await host(api));
    await tester.pumpAndSettle();

    // 首屏：50 条 + footer 提示还有更多（无「没有更多了」）。
    expect(find.text('会话 0'), findsOneWidget);
    expect(find.text('加载中…'), findsNothing);
    expect(find.text('没有更多了'), findsNothing);

    // ListView 惰性构建视口外子项，一次 drag 到不了底：反复上滚直到到底提示出现。
    for (var i = 0; i < 12; i++) {
      await tester.drag(find.byType(ListView).last, const Offset(0, -700));
      await tester.pumpAndSettle();
      if (find.text('没有更多了').evaluate().isNotEmpty) break;
    }

    // 第二页到达：出现第 50 条之后的内容，且不再继续触发（单飞 + 到底判定）。
    expect(find.text('会话 74'), findsOneWidget);
    expect(find.text('没有更多了'), findsOneWidget);
    final sessionCalls =
        captured.where((r) => r.url.path.endsWith('/sessions')).length;
    expect(sessionCalls, 2);
    final pageRequest =
        captured.where((r) => r.url.path.endsWith('/sessions')).toList();
    expect(pageRequest.last.url.queryParameters['offset'], '50');
    expect(pageRequest.last.url.queryParameters['limit'], '50');
  });

  testWidgets(
      'refresh indicator awaits the real load and duplicate pulls are debounced',
      (tester) async {
    final captured = <http.Request>[];
    // delay 让刷新窗口足够宽，可以在请求在飞时再拉一次。
    final api =
        mockApi(captured: captured, delay: const Duration(milliseconds: 300));
    await tester.pumpWidget(await host(api));
    await tester.pumpAndSettle();

    // 模拟下拉刷新（RefreshIndicator 触发 load()）。
    await tester.fling(find.byType(ListView).last, const Offset(0, 300), 1200);
    await tester.pump(const Duration(milliseconds: 100)); // 指示器出现 + 请求在飞

    // 请求在飞期间再次下拉：load() 的单飞守卫应丢弃第二次触发。
    await tester.fling(find.byType(ListView).last, const Offset(0, 300), 1200);
    await tester.pump(const Duration(milliseconds: 100));
    await tester.pump(const Duration(seconds: 1));
    await tester.pumpAndSettle();

    final sessionCalls =
        captured.where((r) => r.url.path.endsWith('/sessions')).length;
    // 1（首屏）+ 1（刷新）——第二次下拉被防抖掉。
    expect(sessionCalls, 2);
  });

  testWidgets('load-more failure keeps the list and offers retry',
      (tester) async {
    var failNextPage = true;
    final captured = <http.Request>[];
    final api = EthanApiClient(
      config,
      client: MockClient((request) async {
        captured.add(request);
        final offset = int.parse(request.url.queryParameters['offset'] ?? '0');
        if (offset > 0 && failNextPage) {
          return http.Response('{"detail":"boom"}', 500);
        }
        if (request.url.path.endsWith('/sessions/pinned')) {
          return http.Response('{"sessions": []}', 200);
        }
        final limit = int.parse(request.url.queryParameters['limit'] ?? '50');
        final end = (offset + limit).clamp(0, 75);
        final sessions = [
          for (var i = offset; i < end; i++)
            {'id': 's-$i', 'title': '会话 $i', 'updated_at': 1700000000}
        ];
        return http.Response.bytes(
            utf8.encode(jsonEncode({'sessions': sessions, 'total': 75})), 200,
            headers: {'content-type': 'application/json'});
      }),
    );
    await tester.pumpWidget(await host(api));
    await tester.pumpAndSettle();

    // 反复上滚直到触发加载更多（惰性构建，一次 drag 到不了底）。
    for (var i = 0; i < 12; i++) {
      await tester.drag(find.byType(ListView).last, const Offset(0, -700));
      await tester.pumpAndSettle();
      if (find.textContaining('加载更多失败').evaluate().isNotEmpty) break;
    }

    // 失败：footer 出现重试入口，且按钮就在当前视口内可点。
    expect(find.textContaining('加载更多失败'), findsOneWidget);
    expect(find.text('重试').hitTestable(), findsOneWidget);

    // 恢复后点重试：第二页补齐，footer 变成「没有更多了」（列表已含全部
    // 75 条 —— 会话 74 在视口外，惰性构建查不到，用滚动范围判断）。
    failNextPage = false;
    await tester.tap(find.text('重试'));
    await tester.pumpAndSettle();
    final position =
        tester.state<ScrollableState>(find.byType(Scrollable).last).position;
    expect(position.maxScrollExtent, greaterThan(6000.0));
    // 滚到底部，footer 应显示「没有更多了」。
    for (var i = 0; i < 15; i++) {
      await tester.drag(find.byType(ListView).last, const Offset(0, -600));
      await tester.pumpAndSettle();
      if (find.text('没有更多了').hitTestable().evaluate().isNotEmpty) break;
    }
    expect(find.text('没有更多了'), findsOneWidget);

    // 滚回顶部：第 0 条仍在列表里 —— 加载失败从未动过已有数据。
    await tester.drag(find.byType(ListView).last, const Offset(0, 20000));
    await tester.pumpAndSettle();
    expect(find.text('会话 0'), findsOneWidget);
  });
}
