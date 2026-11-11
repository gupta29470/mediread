import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:mediread_app/src/ingest/lab_pipeline.dart';
import 'package:mediread_app/src/ingest/table_parser.dart';

/// Replays the geometry of a real report through the host parser.
///
/// pdfium cannot load inside `flutter test`, so the raw text path only exercises
/// the byte parser and never the real extraction. This test reads a glyph
/// fixture produced by `tooling/export_layout_fixture.py` — the same character
/// rectangles pdfrx returns on a device — and asserts what the parser must and
/// must not do with it.
///
/// The fixture is derived from a patient report and is therefore git-ignored.
/// When it is absent the test skips, and says how to produce it:
///
///   .venv/bin/python tooling/export_layout_fixture.py \
///       "medical reports/report.pdf" --out .cache/layout/report.glyphs.json
void main() {
  final directory = Directory('../.cache/layout');
  final fixtures = directory.existsSync()
      ? (directory.listSync().whereType<File>().where((file) => file.path.endsWith('.glyphs.json')).toList()
        ..sort((a, b) => a.path.compareTo(b.path)))
      : <File>[];

  bool isSixteenPageReport(Map<String, dynamic> fixture) =>
      (fixture['pageSizes'] as List<dynamic>).length == 16;

  List<List<Glyph>> glyphPages(Map<String, dynamic> fixture) => [
        for (final page in fixture['pages'] as List<dynamic>)
          [
            for (final entry in page as List<dynamic>)
              Glyph(
                (entry as List<dynamic>)[0] as String,
                (entry[1] as num).toDouble(),
                (entry[2] as num).toDouble(),
                (entry[3] as num).toDouble(),
                (entry[4] as num).toDouble(),
              ),
          ],
      ];

  test('the real report yields lab rows, not glyph garbage', () {
    for (final file in fixtures) {
      final fixture = jsonDecode(file.readAsStringSync()) as Map<String, dynamic>;
      final glyphs = glyphPages(fixture);
      final glyphCount = glyphs.fold<int>(0, (sum, page) => sum + page.length);
      final rows = const TableParser().parsePages(glyphs);
      // A report with a real result table must yield something. Very short
      // reports (a single blood-group page) legitimately have no numeric rows.
      if (glyphCount >= 1500) {
        expect(rows, isNotEmpty, reason: 'no rows at all from ${file.path}');
      }
      for (final row in rows) {
        // Glyph garbage shows up as control or replacement characters, or as a
        // name with no real words in it. Digits, hyphens and brackets are
        // legitimate parts of test names (Ca-125, 25-OH Vitamin D, (TIBC)).
        expect(RegExp(r'[^\x20-\x7E\u00B5]').allMatches(row.name), isEmpty,
            reason: 'undecodable row name "${row.name}" from ${file.path}');
        expect(RegExp(r'[A-Za-z]{2,}').hasMatch(row.name), isTrue,
            reason: 'row name "${row.name}" has no word in it');
        expect(row.name, isNot(contains('<')), reason: 'reference leaked: ${row.name}');
        expect(row.valueText, isNotEmpty);
        // A reference is either comparable (with parsed bounds) or explicitly
        // withheld; never a half-parsed string that would be compared anyway.
        if (row.referenceText != null && !row.stratified) {
          expect(row.low != null || row.high != null || row.operator != null, isTrue,
              reason: '"${row.name}" has an unparsed comparable reference');
        }
        if (row.stratified) {
          expect(gatesFor(row, lookupKnownTest(row.name))['range_comparison'], isFalse,
              reason: '"${row.name}" compared a stratified reference');
        }
      }
    }
  }, skip: fixtures.isEmpty ? 'no layout fixture in .cache/layout' : null);

  test('the 16-page report binds the ranges it actually prints', () {
    for (final file in fixtures) {
      final fixture = jsonDecode(file.readAsStringSync()) as Map<String, dynamic>;
      if (!isSixteenPageReport(fixture)) continue;
      final rows = const TableParser().parsePages(glyphPages(fixture));
      ParsedLabRow row(String name) =>
          rows.firstWhere((row) => row.name.toLowerCase().contains(name.toLowerCase()),
              orElse: () => throw StateError('no row matching "$name"; got ${rows.map((r) => r.name).toList()}'));

      // 1. A one-sided reference printed below the result is comparable.
      final ca125 = row('Ca-125');
      expect(ca125.valueText, '29.7');
      expect(ca125.high, 30.2);
      expect(ca125.operator, '<');
      expect(gatesFor(ca125, lookupKnownTest(ca125.name))['range_comparison'], isTrue);

      // 2. A plain range printed below the result is comparable.
      final b12 = row('Vitamin B-12');
      expect(b12.valueText, '211');
      expect(b12.low, 211);
      expect(b12.high, 911);
      expect(b12.stratified, isFalse);
      expect(gatesFor(b12, lookupKnownTest(b12.name))['identify_test'], isTrue);

      // 3. A range printed in its own column never replaces the reported value.
      final cholesterol = row('Total Cholesterol');
      expect(cholesterol.valueText, '113');
      expect(cholesterol.high, 200);
      expect(cholesterol.numericValue, isNotNull);
      expect(cholesterol.numericValue! <= cholesterol.high!, isTrue);

      // 4. Sex-specific blocks are withheld, not collapsed into one interval.
      for (final name in ['Iron', 'Total Iron Binding Capacity', 'Erythrocyte Sedimentation Rate']) {
        final measured = row(name);
        expect(measured.stratified, isTrue, reason: '$name should be stratified');
        expect(measured.low, isNull);
        expect(measured.high, isNull);
        expect(gatesFor(measured, lookupKnownTest(measured.name))['range_comparison'], isFalse);
      }

      // 5. Cut-off tables are kept as printed and withheld.
      for (final name in ['Vitamin D', 'Hba1c', 'Average Blood Glucose', 'Glomerular Filtration']) {
        final measured = row(name);
        expect(measured.stratified, isTrue, reason: '$name should be stratified');
        expect(measured.referenceText, isNotNull);
        expect(gatesFor(measured, lookupKnownTest(measured.name))['range_comparison'], isFalse);
      }
      expect(row('Vitamin D').referenceText, contains('DEFICIENCY'));

      // 6. A range printed in a column, on a thyroid panel, is comparable.
      final tsh = row('Tsh');
      expect(tsh.low, 0.35);
      expect(tsh.high, 4.94);
      expect(tsh.stratified, isFalse);

      // 7. A censored reported value is shown as printed and never compared.
      final rheumatoid = row('Rheumatoid Factor');
      expect(rheumatoid.valueText, '<10');
      expect(rheumatoid.valueVerified, isFalse);
      expect(gatesFor(rheumatoid, lookupKnownTest(rheumatoid.name))['range_comparison'], isFalse);

      // 8. Other named acceptance cases from the same report.
      final creatinine = row('Creatinine - Serum');
      expect(creatinine.valueText, '0.54');
      expect(creatinine.low, 0.55);
      expect(creatinine.high, 1.02);

      final hemoglobin = row('Hemoglobin');
      expect(hemoglobin.valueText, '10.3');
      expect(hemoglobin.low, 12.0);
      expect(hemoglobin.high, 15.0);

      final rdw = row('Red Cell Distribution Width - Sd');
      expect(rdw.valueText, '33.1');
      expect(rdw.low, 39.0);
      expect(rdw.high, 46.0);

      final hdl = row('Hdl Cholesterol - Direct');
      expect(hdl.valueText, '39');
      expect(hdl.low, 40);
      expect(hdl.high, 60);

      final ldl = row('Ldl Cholesterol - Direct');
      expect(ldl.valueText, '73');
      expect(ldl.high, 100);

      final triglycerides = row('Triglycerides');
      expect(triglycerides.valueText, '64');
      expect(triglycerides.high, 150);

      // The vitamin D cut-off table is preserved textually, never flattened.
      final vitaminD = row('Vitamin D');
      expect(vitaminD.referenceText, contains('DEFICIENCY'));
      expect(vitaminD.referenceText, contains('SUFFICIENCY'));
      expect(vitaminD.low, isNull);
      expect(vitaminD.high, isNull);

      // 9. Known false positives must not appear as results.
      const junk = ['HOUSING', 'VIRAR', '1995', 'Available', 'DEFICIENCY', 'SUFFICIENCY', 'HEMOGRAM - 6'];
      for (final extracted in rows) {
        for (final needle in junk) {
          expect(extracted.name.toUpperCase(), isNot(contains(needle)),
              reason: 'junk "${extracted.name}" became a result');
        }
        expect(extracted.valueText, isNot('4.3'),
            reason: 'a precision figure became the value of "${extracted.name}"');
      }

      // 10. Coverage: the report prints 69 result rows on these pages.
      expect(rows.length, greaterThanOrEqualTo(60));
      expect(rows.where((row) => row.referenceText != null).length, greaterThanOrEqualTo(60));
    }
  }, skip: fixtures.isEmpty ? 'no layout fixture in .cache/layout' : null);
}
