import 'package:flutter_test/flutter_test.dart';
import 'package:mediread_app/src/ingest/lab_pipeline.dart';

void main() {
  const parser = LabParser();

  test('parses a verified row with unit and range', () {
    final row = parser.parseLine('HEMOGLOBIN 9.0 g/dL 12.0 - 15.0')!;
    expect(row.name, 'HEMOGLOBIN');
    expect(row.valueText, '9.0');
    expect(row.unitText, 'g/dL');
    expect(row.low, 12);
    expect(row.high, 15);
    expect(row.valueVerified, isTrue);
    expect(row.unitVerified, isTrue);
    expect(row.referenceVerified, isTrue);
    final explanation = buildExplanation(row);
    expect(explanation.gates['identify_test'], isTrue);
    expect(explanation.gates['range_comparison'], isTrue);
    expect(explanation.status, 'explained');
    expect(explanation.facts.valueText, '9.0');
  });

  test('missing unit blocks the range comparison', () {
    final row = parser.parseLine('HEMOGLOBIN 9.0 12.0 - 15.0')!;
    expect(row.unitVerified, isFalse);
    final explanation = buildExplanation(row);
    expect(explanation.gates['unit_comparison'], isFalse);
    expect(explanation.gates['range_comparison'], isFalse);
    expect(explanation.section('comparison_with_reference')!.permitted, isFalse);
    expect(explanation.status, 'partially_explained');
  });

  test('unknown test is not explained', () {
    final row = parser.parseLine('MYSTERY MARKER 4.2 U/L 1.0 - 2.0')!;
    final explanation = buildExplanation(row);
    expect(explanation.gates['identify_test'], isFalse);
    expect(explanation.section('what_this_test_measures')!.permitted, isFalse);
    expect(explanation.section('sources')!.permitted, isFalse);
  });

  test('missing reference blocks comparison but keeps the fact', () {
    final row = parser.parseLine('FASTING BLOOD SUGAR 92.9 mg/dL')!;
    final explanation = buildExplanation(row);
    expect(explanation.gates['range_comparison'], isFalse);
    expect(explanation.section('your_reported_result')!.permitted, isTrue);
  });

  test('qualitative rows keep the value without needing a unit', () {
    final row = parser.parseLine('URINE PROTEIN POSITIVE')!;
    expect(row.valueKind, 'qualitative');
    expect(row.valueVerified, isTrue);
    expect(buildExplanation(row).gates['interpret_value'], isTrue);
  });

  test('comparison states are computed, not guessed', () {
    expect(comparisonState(parser.parseLine('HEMOGLOBIN 13.0 g/dL 12.0 - 15.0')!), 'within_range');
    expect(comparisonState(parser.parseLine('HEMOGLOBIN 9.0 g/dL 12.0 - 15.0')!), 'below_range');
    expect(comparisonState(parser.parseLine('HEMOGLOBIN 16.0 g/dL 12.0 - 15.0')!), 'above_range');
    expect(comparisonState(parser.parseLine('TSH 4.1 mIU/L < 5.0')!), 'satisfies_one_sided_reference');
  });

  test('panel headings group rows and printed order is preserved', () {
    const parser = LabParser();
    final rows = parser.parse('''
COMPLETE BLOOD COUNT
HEMOGLOBIN 9.0 g/dL 12.0 - 15.0
PLATELET COUNT 250 X10^3/uL 150 - 410

LIVER FUNCTION
ALBUMIN 4.1 g/dL 3.5 - 5.0
TOTAL PROTEIN 7.2 g/dL 6.0 - 8.3
''');
    expect(rows.map((row) => row.name).toList(),
        ['HEMOGLOBIN', 'PLATELET COUNT', 'ALBUMIN', 'TOTAL PROTEIN']);
    expect(rows[0].panel, 'Complete Blood Count');
    expect(rows[1].panel, 'Complete Blood Count');
    expect(rows[2].panel, 'Liver Function');
    expect(rows[3].panel, 'Liver Function');
  });

  test('glyph-id garbage never becomes a row', () {
    const parser = LabParser();
    for (final junk in [
      '+?GP@ 9',
      'SLN!/@BMSTQ@MJ?!<#"YJ!" <8',
      '.TOA@N@SK!TOVOTO@SO! T N@AO 3',
      'XX!,>! 8',
      '/RLN^JQRPQ@A!, TQHORLOT!RUOS 0',
    ]) {
      expect(parser.parseLine(junk), isNull, reason: junk);
    }
  });

  test('header and prose lines are rejected', () {
    expect(parser.parseLine('Test Name Result Reference Range'), isNull);
    expect(parser.parseLine('Patient Name'), isNull);
    expect(parser.parseLine('This is a short note'), isNull);
  });
}
