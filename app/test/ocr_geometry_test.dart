import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:mediread_app/src/ingest/ocr/geometry.dart';
import 'package:mediread_app/src/ingest/ocr/ocr_engine.dart';
import 'package:mediread_app/src/ingest/ocr/page_classification.dart';
import 'package:mediread_app/src/ingest/ocr/page_source.dart';
import 'package:mediread_app/src/ingest/table_parser.dart';

List<Glyph> glyphs(String text, double x, double y, {double size = 10}) {
  final result = <Glyph>[];
  var cursor = x;
  for (final char in text.split('')) {
    final width = char == ' ' ? size * 0.3 : size * 0.55;
    result.add(Glyph(char, cursor, y, cursor + width, y + size));
    cursor += width;
  }
  return result;
}

RenderedPage rendered({
  double pixelWidth = 1000,
  double pixelHeight = 1414,
  double pointsPerPixelX = 0.595,
  double pointsPerPixelY = 0.595,
}) =>
    RenderedPage(
      pixels: Uint8List(0),
      pixelWidth: pixelWidth.round(),
      pixelHeight: pixelHeight.round(),
      pointsPerPixelX: pointsPerPixelX,
      pointsPerPixelY: pointsPerPixelY,
    );

void main() {
  group('page classification', () {
    test('a table page with a real text layer is digital', () {
      final page = [
        for (var row = 0; row < 20; row++)
          ...glyphs('TOTAL CHOLESTEROL 113 mg/dL <200', 40, 100 + row * 18),
      ];
      final stats = pageStats(page, 595, 842);
      expect(stats.characters, greaterThan(200));
      expect(stats.numericTokens, greaterThan(5));
      expect(classifyPage(stats), PageKind.digitalText);
    });

    test('a page with only a stamp or letterhead is not digital', () {
      final page = glyphs('Scanned by LabScanner 12', 40, 100);
      expect(classifyPage(pageStats(page, 595, 842)), PageKind.imageOnly);
    });

    test('a page with a header but no table is hybrid', () {
      final page = [
        ...glyphs('CITY DIAGNOSTIC LABORATORY', 40, 100),
        ...glyphs('Patient report page 2', 40, 120),
        ...glyphs('Date 12/03/2024', 40, 140),
      ];
      final stats = pageStats(page, 595, 842);
      expect(classifyPage(stats), PageKind.hybrid);
    });

    test('a page with no text layer needs OCR', () {
      expect(classifyPage(pageStats(const [], 595, 842)), PageKind.imageOnly);
    });

    test('a page that produced nothing after OCR is unusable', () {
      expect(resolvePageKind(PageKind.imageOnly, mergedWords: 1), PageKind.unusable);
      expect(resolvePageKind(PageKind.imageOnly, mergedWords: 40), PageKind.imageOnly);
    });
  });

  group('coordinate conversion', () {
    test('pixel boxes become PDF points with the render scale', () {
      final page = rendered(pointsPerPixelX: 0.5, pointsPerPixelY: 0.25);
      final converted = ocrWordsToGlyphs(
        const [
          OcrWord(text: '29.7', left: 1000, top: 200, right: 1100, bottom: 240),
        ],
        page,
      );
      final word = converted.firstWhere((glyph) => glyph.text == '29.7');
      expect(word.left, 500);
      expect(word.right, 550);
      expect(word.top, 50);
      expect(word.bottom, 60);
    });

    test('OCR words stay separate even when their boxes nearly touch', () {
      final page = rendered(pointsPerPixelX: 1, pointsPerPixelY: 1);
      final converted = ocrWordsToGlyphs(
        const [
          OcrWord(text: '9.0', left: 0, top: 10, right: 20, bottom: 24),
          OcrWord(text: 'g/dL', left: 20.2, top: 10, right: 50, bottom: 24),
        ],
        page,
      );
      final words = buildWords(converted);
      expect(words.map((word) => word.text), ['9.0', 'g/dL']);
    });
  });

  group('hybrid merging', () {
    test('OCR words that duplicate embedded text are dropped', () {
      final embedded = glyphs('TOTAL CHOLESTEROL', 40, 100);
      final page = rendered(pointsPerPixelX: 1, pointsPerPixelY: 1);
      final ocr = ocrWordsToGlyphs(
        const [
          OcrWord(text: 'TOTAL', left: 40, top: 100, right: 65, bottom: 110),
          OcrWord(text: 'CHOLESTEROL', left: 66, top: 100, right: 117, bottom: 110),
          OcrWord(text: '113', left: 200, top: 100, right: 220, bottom: 110),
        ],
        page,
      );
      final merged = mergeOcrGlyphs(embedded, ocr);
      expect(merged.addedWords, 1);
      expect(merged.droppedWords, 2);
      final words = buildWords(merged.glyphs).map((word) => word.text).toList();
      expect(words, contains('113'));
      expect(words.where((word) => word.startsWith('TOTAL')).length, 1);
    });

    test('an empty embedded layer keeps every OCR word', () {
      final page = rendered(pointsPerPixelX: 1, pointsPerPixelY: 1);
      final ocr = ocrWordsToGlyphs(
        const [
          OcrWord(text: 'HAEMOGLOBIN', left: 0, top: 0, right: 60, bottom: 10),
          OcrWord(text: '9.0', left: 70, top: 0, right: 90, bottom: 10),
        ],
        page,
      );
      final merged = mergeOcrGlyphs(const [], ocr);
      expect(merged.addedWords, 2);
      expect(merged.droppedWords, 0);
    });
  });
}
