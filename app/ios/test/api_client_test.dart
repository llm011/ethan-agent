import 'dart:convert';

import 'package:ethan_ios/data/api_client.dart';
import 'package:ethan_ios/models/app_models.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  const config = ApiConfig(baseUrl: 'http://127.0.0.1:8900/api', token: 't');

  test('chat serializes Android-compatible quote and inline image payloads',
      () async {
    late http.Request captured;
    final client = MockClient((request) async {
      captured = request;
      return http.Response.bytes(
          utf8.encode('data: {"content":"完成"}\n'
              'data: {"done":true,"usage":{"input":12,"output":3}}\n'),
          200,
          headers: {'content-type': 'text/event-stream'});
    });
    final api = EthanApiClient(config, client: client);

    final events = await api.chat(
      text: '看图',
      sessionId: 's-1',
      model: 'provider/model',
      mode: 'plan',
      quote: const QuoteInfo(role: 'assistant', content: '被引用内容'),
      images: const [
        MessageImage(data: 'aGVsbG8=', mediaType: 'image/png'),
      ],
      history: const [
        ChatMessage(text: '看图', isUser: true, time: '现在'),
      ],
    ).toList();

    expect(captured.method, 'POST');
    expect(captured.url.path, '/api/chat');
    expect(captured.headers['authorization'], 'Bearer t');
    final body = jsonDecode(captured.body) as Map<String, dynamic>;
    expect(body['session_id'], 's-1');
    expect(body['model'], 'provider/model');
    expect(body['mode'], 'plan');
    expect(body['quote'], {'role': 'assistant', 'content': '被引用内容'});
    final messages = body['messages'] as List<dynamic>;
    expect((messages.single as Map<String, dynamic>)['images'], [
      {'data': 'aGVsbG8=', 'media_type': 'image/png'}
    ]);
    expect(events.last.usage?.output, 3);
  });

  test('session restores images, quotes, usage and nested tool steps',
      () async {
    final client = MockClient((request) async => http.Response.bytes(
        utf8.encode(jsonEncode({
          'id': 's-1',
          'title': '会话',
          'model': 'm',
          'messages': [
            {
              'id': 42,
              'role': 'assistant',
              'content': '结果',
              'quote': {'role': 'user', 'content': '问题'},
              'usage': {'input': 9, 'output': 4, 'cache': 2},
              'images': [
                {
                  'url': 'assets/images/s-1/chart.png',
                  'media_type': 'image/png'
                }
              ],
              'cards': [
                {
                  'type': 'file',
                  'path': '/tmp/deck/deck.pptx',
                  'filename': 'deck.pptx',
                  'kind': 'pptx',
                  'project_dir': '/tmp/deck'
                },
                {'type': 'file', 'path': '/tmp/video.mp4', 'kind': 'mp4'}
              ],
              'tool_steps': [
                {
                  'tool': 'search',
                  'state': 'done',
                  'sub_steps': [
                    {'tool': 'fetch', 'state': 'done'}
                  ]
                }
              ]
            }
          ]
        })),
        200));
    final detail = await EthanApiClient(config, client: client).session('s-1');
    final message = detail.messages.single;

    expect(message.id, '42');
    expect(message.quote?.content, '问题');
    expect(message.usage?.cache, 2);
    expect(message.images.single.displayUrl,
        'http://127.0.0.1:8900/api/assets/images/s-1/chart.png');
    expect(message.cards, hasLength(2));
    expect(message.cards.first.isPpt, isTrue);
    expect(message.cards.last.isVideo, isTrue);
    expect(message.toolSteps.single.subSteps.single.tool, 'fetch');
  });

  test('media requests follow files/view contract and keep bearer auth',
      () async {
    late http.Request request;
    final api = EthanApiClient(config, client: MockClient((value) async {
      request = value;
      return http.Response.bytes([1, 2, 3], 200);
    }));
    final bytes = await api.fetchMediaBytes('/tmp/video.mp4', sessionId: 's-1');
    expect(bytes, [1, 2, 3]);
    expect(request.url.path, '/api/files/view');
    expect(request.url.queryParameters['path'], '/tmp/video.mp4');
    expect(request.url.queryParameters['session_id'], 's-1');
    expect(request.headers['authorization'], 'Bearer t');
  });

  test('resume treats 204 as no active Android-equivalent chat run', () async {
    final client = MockClient((_) async => http.Response('', 204));
    final events = await EthanApiClient(config, client: client)
        .resumeStream('s-1')
        .toList();
    expect(events, isEmpty);
  });

  test('consent and interactive answers use the server request identifiers',
      () async {
    final requests = <http.Request>[];
    final client = MockClient((request) async {
      requests.add(request);
      return http.Response('{}', 200);
    });
    final api = EthanApiClient(config, client: client);

    await api.respondConsent('consent/1', true);
    await api.respondAskUser('ask 1', 'yes');
    await api.respondWaitForUser('wait 1', 'done');

    expect(requests.map((request) => request.url.path), [
      '/api/consent/consent%2F1',
      '/api/ask-user/ask%201',
      '/api/wait-for-user/wait%201',
    ]);
    expect(jsonDecode(requests[0].body), {'allowed': true});
    expect(jsonDecode(requests[1].body), {'value': 'yes'});
    expect(jsonDecode(requests[2].body), {'value': 'done'});
  });

  test('session controls use Android API routes', () async {
    final requests = <http.Request>[];
    final client = MockClient((request) async {
      requests.add(request);
      return http.Response('{}', 200);
    });
    final api = EthanApiClient(config, client: client);
    await api.pinSession('s/1');
    await api.unpinSession('s/1');
    await api.regenerateTitle('s/1');
    await api.summarizeSession('s/1');
    await api.deleteMessage('s/1', 3);

    expect(requests.map((r) => '${r.method} ${r.url.path}'), [
      'POST /api/sessions/s%2F1/pin',
      'DELETE /api/sessions/s%2F1/pin',
      'POST /api/sessions/s%2F1/regen-title',
      'POST /api/sessions/s%2F1/summary',
      'DELETE /api/sessions/s%2F1/messages/3',
    ]);
  });

  test('Track 8 annotation and deck endpoints preserve Android paths',
      () async {
    final requests = <http.Request>[];
    final client = MockClient((request) async {
      requests.add(request);
      if (request.url.path.endsWith('/annotations/batch')) {
        return http.Response('{}', 200);
      }
      if (request.url.path.endsWith('/files/deck')) {
        return http.Response('{"pages":[]}', 200);
      }
      return http.Response('{}', 200);
    });
    final api = EthanApiClient(config, client: client);

    await api.batchGetAnnotations('1,2');
    await api.deleteAnnotation(7);
    await api.getDeck('', sessionId: 'session/1');

    expect(requests.map((r) => '${r.method} ${r.url.path}'), [
      'GET /api/annotations/batch',
      'DELETE /api/annotations/7',
      'GET /api/files/deck',
    ]);
    expect(requests.first.url.queryParameters['ids'], '1,2');
    expect(requests.last.url.queryParameters['session_id'], 'session/1');
  });
}
