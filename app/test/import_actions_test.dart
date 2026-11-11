import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mediread_app/src/ui/import_actions.dart';
import 'package:mediread_app/src/ui/theme.dart';

Widget host(Widget child) => MaterialApp(
      theme: Clinical.theme(),
      home: Scaffold(body: child),
    );

void main() {
  testWidgets('the three actions replace the old upload button', (tester) async {
    await tester.pumpWidget(host(ImportActions(
      enabled: true,
      onPdf: () {},
      onCamera: () {},
      onGallery: () {},
    )));

    expect(find.text('Import PDF'), findsOneWidget);
    expect(find.text('Take photo'), findsOneWidget);
    expect(find.text('Gallery'), findsOneWidget);
    expect(find.text('Upload a report'), findsNothing);
    expect(find.byType(FilledButton), findsNothing);
  });

  testWidgets('each action invokes its own callback immediately', (tester) async {
    final calls = <String>[];
    await tester.pumpWidget(host(ImportActions(
      enabled: true,
      onPdf: () => calls.add('pdf'),
      onCamera: () => calls.add('camera'),
      onGallery: () => calls.add('gallery'),
    )));

    await tester.tap(find.text('Import PDF'));
    await tester.tap(find.text('Take photo'));
    await tester.tap(find.text('Gallery'));
    await tester.pump();
    expect(calls, ['pdf', 'camera', 'gallery']);
  });

  testWidgets('actions are inert until the model is ready', (tester) async {
    final calls = <String>[];
    await tester.pumpWidget(host(ImportActions(
      enabled: false,
      onPdf: () => calls.add('pdf'),
      onCamera: () => calls.add('camera'),
      onGallery: () => calls.add('gallery'),
    )));

    await tester.tap(find.text('Import PDF'), warnIfMissed: false);
    await tester.tap(find.text('Take photo'), warnIfMissed: false);
    await tester.pump();
    expect(calls, isEmpty);
  });
}
