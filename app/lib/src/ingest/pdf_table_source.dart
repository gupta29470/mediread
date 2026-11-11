import 'dart:typed_data';

import 'package:flutter/foundation.dart' show kDebugMode;
import 'package:pdfrx/pdfrx.dart';

import 'lab_pipeline.dart';
import 'ocr/page_outcome.dart';
import 'table_parser.dart';

class ReportExtraction {
  const ReportExtraction({
    required this.rows,
    required this.text,
    required this.pages,
    this.debugLines = '',
    this.pageOutcomes = const [],
    this.warnings = const [],
    this.usedOcr = false,
    this.ocrProvider = '',
    this.debugOcrTokens = '',
  });

  final List<ParsedLabRow> rows;
  final String text;
  final int pages;

  /// Per-page classification and OCR cost. Empty for the digital-only path.
  final List<PageOutcome> pageOutcomes;

  /// Page-level problems the user must be told about (unreadable page, OCR
  /// unavailable, rotated page skipped). Never swallowed.
  final List<String> warnings;

  /// True when OCR contributed text that became part of the extracted rows.
  final bool usedOcr;

  final String ocrProvider;

  /// Debug-only dump of recognised tokens (page|text|box) for evaluation.
  final String debugOcrTokens;

  /// Debug-only dump of the lines and words the parser built, with coordinates.
  /// The host fixture is PyMuPDF geometry; this is what pdfium actually produced
  /// on the device, which is the only way to diagnose a device-only layout.
  final String debugLines;

  double get quality {
    if (text.isEmpty) return 0;
    final printable = text.runes.where((r) => r == 10 || (r >= 32 && r < 127)).length;
    return printable / text.length;
  }
}

/// Extracts result rows using pdfium character geometry, one page at a time.
Future<ReportExtraction> extractReportRows(Uint8List bytes) async {
  PdfDocument? document;
  final allRows = <ParsedLabRow>[];
  final pageGlyphs = <List<Glyph>>[];
  final buffer = StringBuffer();
  var pages = 0;
  try {
    document = await PdfDocument.openData(bytes);
    for (final page in document.pages) {
      final raw = await page.loadText();
      if (raw == null || raw.fullText.isEmpty) continue;
      pages++;
      buffer.writeln(raw.fullText);
      final glyphs = <Glyph>[];
      final text = raw.fullText;
      final rects = raw.charRects;
      final count = text.length < rects.length ? text.length : rects.length;
      for (var i = 0; i < count; i++) {
        final rect = rects[i];
        // pdfium y grows upward; convert to a top-down system.
        glyphs.add(Glyph(text[i], rect.left, -rect.top, rect.right, -rect.bottom));
      }
      pageGlyphs.add(glyphs);
    }
  } catch (_) {
    return ReportExtraction(rows: allRows, text: buffer.toString(), pages: pages);
  } finally {
    document?.dispose();
  }
  allRows.addAll(const TableParser().parsePages(pageGlyphs));
  return ReportExtraction(
    rows: allRows,
    text: buffer.toString(),
    pages: pages,
    debugLines: kDebugMode ? dumpLines(pageGlyphs) : '',
  );
}

/// Debug-only: render the visual lines and words with their x/y coordinates.
String dumpLines(List<List<Glyph>> pages) {
  final buffer = StringBuffer();
  for (var index = 0; index < pages.length; index++) {
    buffer.writeln('===== page ${index + 1}');
    for (final line in buildLines(buildWords(pages[index]))) {
      final words = line.words
          .map((word) => '${word.text.replaceAll('\n', '')}'
              '[${word.left.toStringAsFixed(0)}-${word.right.toStringAsFixed(0)}]')
          .join('  ');
      buffer.writeln('y=${line.top.toStringAsFixed(1)} | $words');
    }
  }
  return buffer.toString();
}
