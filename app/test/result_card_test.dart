import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mediread_app/src/ingest/lab_pipeline.dart';
import 'package:mediread_app/src/ui/result_card.dart';
import 'package:mediread_app/src/ui/theme.dart';

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
      evidence: ExtractionEvidence(page: page, notes: const []),
    );

Widget wrap(List<ParsedLabRow> rows) => MaterialApp(
      theme: Clinical.theme(),
      home: Scaffold(
        body: ListView(
          children: [
            for (final item in rows)
              ResultCard(result: buildExplanation(item), evidence: item.evidence),
          ],
        ),
      ),
    );

void main() {
  testWidgets('collapsed card shows the facts and hides the explanation', (tester) async {
    await tester.pumpWidget(wrap([
      row(
        name: 'Total Cholesterol',
        value: '113',
        unit: 'mg/dL',
        reference: '<200',
        high: 200,
        operator: '<',
        page: 7,
      ),
    ]));

    expect(find.text('Total Cholesterol'), findsOneWidget);
    expect(find.text('113'), findsOneWidget);
    expect(find.text('mg/dL'), findsOneWidget);
    expect(find.text('Printed range: <200'), findsOneWidget);
    expect(find.text('Meets printed bound'), findsOneWidget);
    expect(find.text('Verified'), findsOneWidget);
    expect(find.text('Page 7'), findsOneWidget);
    expect(find.text('Details'), findsOneWidget);

    // Nothing from the expanded section is visible yet.
    expect(find.text('What this test measures'), findsNothing);
    expect(find.text('From your report'), findsNothing);
  });

  testWidgets('expanding reveals explanation, limitations, sources and provenance', (tester) async {
    await tester.pumpWidget(wrap([
      row(
        name: 'Vitamin B12',
        value: '211',
        unit: 'pg/mL',
        reference: '211-911',
        low: 211,
        high: 911,
        page: 4,
      ),
    ]));

    await tester.tap(find.text('Details'));
    await tester.pumpAndSettle();

    expect(find.text('What this test measures'), findsOneWidget);
    expect(find.text('What the comparison means'), findsOneWidget);
    expect(find.text('Important limitations'), findsOneWidget);
    expect(find.text('Sources'), findsOneWidget);
    expect(find.text('From your report'), findsOneWidget);
    expect(find.text('Test'), findsOneWidget);
    expect(find.text('Value'), findsOneWidget);
    expect(find.text('Unit'), findsOneWidget);
    expect(find.text('Range'), findsOneWidget);
    expect(find.text('Hide details'), findsOneWidget);

    // Collapse again.
    await tester.tap(find.text('Hide details'));
    await tester.pumpAndSettle();
    expect(find.text('What this test measures'), findsNothing);
  });

  testWidgets('each card expands independently', (tester) async {
    tester.view.physicalSize = const Size(900, 2600);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(wrap([
      row(name: 'Haemoglobin', value: '10.3', unit: 'g/dL', reference: '12.0-15.0', low: 12, high: 15),
      row(name: 'Platelet Count', value: '344', unit: '10^3/uL', reference: '150-410', low: 150, high: 410),
    ]));

    expect(find.text('What this test measures'), findsNothing);
    await tester.tap(find.text('Details').first);
    await tester.pumpAndSettle();

    expect(find.text('What this test measures'), findsOneWidget);
    expect(find.text('Details'), findsOneWidget); // second card still collapsed

    await tester.tap(find.text('Details'));
    await tester.pumpAndSettle();
    expect(find.text('What this test measures'), findsNWidgets(2));
  });

  testWidgets('a censored value is flagged for review and never compared', (tester) async {
    await tester.pumpWidget(wrap([
      row(
        name: 'Rheumatoid Factor',
        value: '<10',
        unit: 'IU/mL',
        reference: 'ADULT : <= 18',
        stratified: true,
        valueVerified: false,
        page: 2,
      ),
    ]));

    expect(find.text('Review this result'), findsOneWidget);
    expect(find.text('Review'), findsOneWidget);
    expect(find.textContaining('Meets printed bound'), findsNothing);
    expect(find.textContaining('Within printed range'), findsNothing);

    await tester.tap(find.text('Details'));
    await tester.pumpAndSettle();
    expect(find.textContaining('extracted details need confirmation'), findsWidgets);
  });

  testWidgets('a missing range is reported, never fabricated', (tester) async {
    await tester.pumpWidget(wrap([
      row(
        name: 'Specific Gravity',
        value: '1.02',
        unit: '-',
        reference: null,
        unitVerified: false,
        referenceVerified: false,
      ),
    ]));

    expect(find.text('Range not provided'), findsOneWidget);
    expect(find.textContaining('Printed range'), findsNothing);
    expect(find.text('Below printed range'), findsNothing);
    expect(find.text('Within printed range'), findsNothing);
  });

  testWidgets('a stratified range is withheld but still printed verbatim', (tester) async {
    await tester.pumpWidget(wrap([
      row(
        name: 'Iron',
        value: '33',
        unit: 'µg/dL',
        reference: 'Male : 65 - 175 | Female : 50 - 170',
        stratified: true,
      ),
    ]));

    expect(find.text('Cannot compare'), findsOneWidget);
    expect(find.text('Printed range: Male : 65 - 175 | Female : 50 - 170'), findsOneWidget);

    await tester.tap(find.text('Details'));
    await tester.pumpAndSettle();
    expect(find.text('What the comparison means'), findsOneWidget);
    expect(
      find.textContaining('printed range depends on information that is not available'),
      findsWidgets,
    );
  });

  testWidgets('verification is distinct from knowledge coverage', (tester) async {
    await tester.pumpWidget(wrap([
      row(
        name: 'Mystery Marker',
        value: '4.2',
        unit: 'U/L',
        reference: '1.0-2.0',
        low: 1,
        high: 2,
      ),
    ]));

    expect(find.text('Verified'), findsOneWidget);
    expect(find.text('No knowledge entry'), findsOneWidget);
  });
}
