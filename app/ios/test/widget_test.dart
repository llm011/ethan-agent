import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:ethan_ios/app.dart';
import 'package:ethan_ios/screens/workspace_screens.dart';

void main() {
  testWidgets('requires login then accepts the development mock token',
      (WidgetTester tester) async {
    SharedPreferences.setMockInitialValues({});
    await tester.pumpWidget(const EthanApp());
    await tester.pump(const Duration(seconds: 1));

    expect(find.text('登录 Ethan'), findsOneWidget);
    final fields =
        tester.widgetList<TextField>(find.byType(TextField)).toList();
    expect(fields, hasLength(2));
    expect(fields[1].controller!.text, 'mock-token');

    await tester.tap(find.text('登录 Ethan'));
    await tester.pump(const Duration(seconds: 1));
    expect(find.text('工作台'), findsOneWidget);
    expect(find.text('对话'), findsOneWidget);
  });

  testWidgets('schedule page builds and can be popped without a tab assertion',
      (WidgetTester tester) async {
    await tester.pumpWidget(MaterialApp(
      home: Builder(
        builder: (context) => Scaffold(
          body: TextButton(
            onPressed: () => Navigator.of(context).push(MaterialPageRoute(
              builder: (_) => const ScheduleScreen(),
            )),
            child: const Text('open'),
          ),
        ),
      ),
    ));

    await tester.tap(find.text('open'));
    await tester.pumpAndSettle();
    expect(find.text('定时任务'), findsOneWidget);
    expect(tester.takeException(), isNull);

    await tester.pageBack();
    await tester.pumpAndSettle();
    expect(find.text('open'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
