import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mediread_app/src/ai/orchestrator.dart';
import 'package:mediread_app/src/ingest/lab_pipeline.dart';
import 'package:mediread_app/src/ingest/pdf_table_source.dart';
import 'package:mediread_app/src/ui/import_page.dart';
import 'package:mediread_app/src/ui/report_source.dart';
import 'package:mediread_app/src/ui/theme.dart';

import 'fakes.dart';

ParsedLabRow row({
  required String name,
  required String value,
  String? unit,
  String? reference,
  double? low,
  double? high,
  String? operator,
  bool stratified = false,
  bool valueVerified = true,
  bool unitVerified = true,
  bool referenceVerified = true,
  int page = 3,
}) =>
    ParsedLabRow(
      name: name,
      panel: 'Screening (Female) New',
      valueText: value,
      valueKind: double.tryParse(value) == null ? 'qualitative' : 'numeric',
      unitText: unit,
      referenceText: reference,
      low: low,
      high: high,
      operator: operator,
      valueVerified: valueVerified,
      unitVerified: unitVerified,
      referenceVerified: referenceVerified,
      stratified: stratified,
      evidence: ExtractionEvidence(page: page),
    );

final sampleRows = <ParsedLabRow>[
  row(
    name: 'Ca-125',
    value: '29.7',
    unit: 'U/mL',
    reference: 'Less than 30.2',
    high: 30.2,
    operator: '<',
    page: 3,
  ),
  row(
    name: 'Iron',
    value: '33',
    unit: 'µg/dL',
    reference: 'Male : 65 - 175 | Female : 50 - 170',
    stratified: true,
    page: 6,
  ),
];

ReportLoader loaderWith(List<ParsedLabRow> rows) =>
    (bytes, {onProgress}) async => ReportExtraction(rows: rows, text: 'text', pages: 1);

Widget results(ReportLoader loader) => MaterialApp(
      theme: Clinical.theme(),
      home: ImportPage(
        orchestrator: ExplanationOrchestrator(
          runtimeProvider: () => FakeRuntime(),
          modelReady: () => false,
        ),
        modelReady: false,
        onSetupModel: () {},
        initial: PickedReport(bytes: Uint8List(1), name: 'report.pdf'),
        loader: loader,
      ),
    );

void main() {
  testWidgets('results open with the picked report and no chooser card', (tester) async {
    await tester.pumpWidget(results(loaderWith(sampleRows)));
    await tester.pumpAndSettle();

    // The file is already chosen: no "Choose a PDF report" step is rendered.
    expect(find.text('Choose a PDF report'), findsNothing);
    expect(find.text('Select PDF'), findsNothing);

    // The results screen shows the file, the counts and the cards.
    expect(find.text('report.pdf'), findsOneWidget);
    expect(find.text('2 results · 2 verified · 0 to review'), findsOneWidget);
    expect(find.text('Screening (Female) New'), findsOneWidget);
    expect(find.text('Ca-125'), findsOneWidget);
    expect(find.text('Iron'), findsOneWidget);
    expect(find.text('Download report PDF'), findsOneWidget);
  });

  testWidgets('cards expand inside the results screen', (tester) async {
    await tester.pumpWidget(results(loaderWith(sampleRows)));
    await tester.pumpAndSettle();

    expect(find.text('What this test measures'), findsNothing);
    await tester.tap(find.text('Details').first);
    await tester.pumpAndSettle();
    expect(find.text('What this test measures'), findsOneWidget);
  });

  testWidgets('a report with no rows says so and offers another PDF', (tester) async {
    await tester.pumpWidget(results(
        (bytes, {onProgress}) async =>
            const ReportExtraction(rows: [], text: 'some text', pages: 1)));
    await tester.pumpAndSettle();

    expect(find.textContaining('No laboratory rows were found'), findsOneWidget);
    expect(find.text('Choose another file'), findsOneWidget);
    expect(find.text('Download report PDF'), findsNothing);
  });

  testWidgets('an unreadable report offers PDF, gallery and camera again', (tester) async {
    await tester.pumpWidget(results((bytes, {onProgress}) async =>
        const ReportExtraction(rows: [], text: '', pages: 1)));
    await tester.pumpAndSettle();

    await tester.tap(find.text('Choose another file'));
    await tester.pumpAndSettle();

    expect(find.text('Import a PDF'), findsOneWidget);
    expect(find.text('Choose a photo from the gallery'), findsOneWidget);
    expect(find.text('Take a photo'), findsOneWidget);
  });

  testWidgets('a failed read is reported, not hidden', (tester) async {
    await tester.pumpWidget(results(
        (bytes, {onProgress}) async => throw StateError('broken pdf')));
    await tester.pumpAndSettle();

    expect(find.textContaining('Could not read this report'), findsOneWidget);
    expect(find.text('Choose another file'), findsOneWidget);
  });
}
