import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:mediread_app/src/ingest/lab_pipeline.dart';
import 'package:mediread_app/src/ingest/pdf_text.dart';

/// Safety property over the real report corpus: whatever the extractor returns,
/// glyph garbage must never become a laboratory row. This does not assert that
/// extraction succeeds — the current Dart path cannot decode these reports, and
/// the test records that honestly instead of pretending otherwise.
void main() {
  final corpus = Directory('../medical reports');
  final pdfs = corpus.existsSync()
      ? (corpus
          .listSync()
          .whereType<File>()
          .where((f) => f.path.endsWith('.pdf'))
          .toList()
        ..sort((a, b) => a.path.compareTo(b.path)))
      : <File>[];

  test('no glyph garbage becomes a row on any real report', () async {
    for (final file in pdfs) {
      final extracted = await extractPdfTextAsync(await file.readAsBytes());
      final rows = const LabParser().parse(extracted.text);
      for (final row in rows) {
        final letters = RegExp(r'[A-Za-z ]').allMatches(row.name).length;
        expect(letters / row.name.length, greaterThanOrEqualTo(0.85),
            reason: 'garbage row name leaked from ${file.uri.pathSegments.last}');
        final explanation = buildExplanation(row);
        if (!row.referenceVerified) {
          expect(explanation.gates['range_comparison'], isFalse);
        }
        if (lookupKnownTest(row.name) == null) {
          expect(explanation.gates['identify_test'], isFalse);
        }
      }
    }
  }, skip: pdfs.isEmpty ? 'corpus not present' : null);

  test('extraction quality is reported, not assumed', () async {
    final file = pdfs.first;
    final extracted = await extractPdfTextAsync(await file.readAsBytes());
    expect(extracted.text, isNotEmpty);
    expect(extracted.quality, inInclusiveRange(0.0, 1.0));
  }, skip: pdfs.isEmpty ? 'corpus not present' : null);
}
