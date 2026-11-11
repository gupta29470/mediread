import 'dart:math' as math;

import '../table_parser.dart' show Glyph, Word, buildWords;
import 'ocr_engine.dart';
import 'page_source.dart';

/// Converts OCR words from rendered-image pixels into parser glyphs in PDF
/// points, one glyph per word plus a zero-width boundary glyph so the word
/// builder can never merge two OCR words together.
///
/// The conversion uses the actual bitmap size, so the chosen DPI, the render
/// scale and any crop are all accounted for: `point = pixel × (pageSize / bitmapSize)`.
List<Glyph> ocrWordsToGlyphs(List<OcrWord> words, RenderedPage page) {
  final glyphs = <Glyph>[];
  for (final word in words) {
    final left = page.toPointX(word.left);
    final top = page.toPointY(word.top);
    final right = page.toPointX(word.right);
    final bottom = page.toPointY(word.bottom);
    if (right - left <= 0.05 || bottom - top <= 0.05) continue;
    glyphs.add(Glyph(word.text.trim(), left, top, right, bottom));
    // A zero-area whitespace glyph flushes the word builder, so OCR word
    // boundaries are honoured even when a gap is narrower than the parser's
    // geometric tolerance.
    glyphs.add(Glyph(' ', right, top, right, top));
  }
  return glyphs;
}

/// Merges OCR glyphs into an embedded text layer.
///
/// An OCR word is dropped when it sits on top of embedded text (overlap of at
/// least [overlapThreshold] of the OCR word's area). Embedded text always wins:
/// it is exact, and keeping it preserves the digital token's provenance.
/// Returns the merged glyph list and how many OCR words survived.
({List<Glyph> glyphs, int addedWords, int droppedWords}) mergeOcrGlyphs(
  List<Glyph> embedded,
  List<Glyph> ocr, {
  double overlapThreshold = 0.5,
}) {
  if (embedded.isEmpty) {
    return (glyphs: ocr, addedWords: ocr.where(_isWordGlyph).length, droppedWords: 0);
  }
  final embeddedWords = buildWords(embedded);
  final kept = <Glyph>[];
  var added = 0;
  var dropped = 0;
  for (var index = 0; index < ocr.length; index++) {
    final glyph = ocr[index];
    if (!_isWordGlyph(glyph)) continue;
    final blocked = embeddedWords.any((word) => _overlaps(glyph, word) >= overlapThreshold);
    if (blocked) {
      dropped++;
      continue;
    }
    kept.add(glyph);
    kept.add(Glyph(' ', glyph.right, glyph.top, glyph.right, glyph.top));
    added++;
  }
  return (glyphs: [...embedded, ...kept], addedWords: added, droppedWords: dropped);
}

bool _isWordGlyph(Glyph glyph) => glyph.text.trim().isNotEmpty;

double _overlaps(Glyph glyph, Word word) {
  final left = math.max(glyph.left, word.left);
  final right = math.min(glyph.right, word.right);
  final top = math.max(glyph.top, word.top);
  final bottom = math.min(glyph.bottom, word.bottom);
  if (right <= left || bottom <= top) return 0;
  final intersection = (right - left) * (bottom - top);
  final area = (glyph.right - glyph.left) * (glyph.bottom - glyph.top);
  return area <= 0 ? 0 : intersection / area;
}

/// Number of word tokens in a glyph list (used for page-level reporting).
int countWords(List<Glyph> glyphs) => glyphs.where(_isWordGlyph).length;
