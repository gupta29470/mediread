import '../table_parser.dart' show Glyph, Word, buildWords;

/// What a page's text layer can be trusted for.
enum PageKind {
  /// Enough embedded text, digits and coverage to run the digital parser.
  digitalText,

  /// Some embedded text, but not enough to be the whole page: OCR the page and
  /// keep the embedded text where the two overlap.
  hybrid,

  /// No usable text layer (a scan, or a few stray characters).
  imageOnly,

  /// Nothing readable after OCR: blank, corrupt or unreadable scan.
  unusable,
}

extension PageKindLabel on PageKind {
  String get label => switch (this) {
        PageKind.digitalText => 'embedded text',
        PageKind.hybrid => 'partial text + OCR',
        PageKind.imageOnly => 'scanned page',
        PageKind.unusable => 'unreadable',
      };
}

/// Cheap statistics of the embedded text layer of one page.
class PageStats {
  const PageStats({
    required this.characters,
    required this.words,
    required this.numericTokens,
    required this.coverage,
    required this.width,
    required this.height,
  });

  final int characters;
  final int words;
  final int numericTokens;

  /// Fraction of the page area covered by character boxes, 0..1.
  final double coverage;
  final double width;
  final double height;

  bool get isEmpty => characters == 0;
}

/// Counts the embedded text a page actually carries.
///
/// [glyphs] are character rectangles in PDF points. Coverage is an area
/// approximation on purpose: it only has to separate "a stamp or a header" from
/// "a printed table".
PageStats pageStats(List<Glyph> glyphs, double pageWidth, double pageHeight) {
  if (glyphs.isEmpty) {
    return PageStats(
      characters: 0,
      words: 0,
      numericTokens: 0,
      coverage: 0,
      width: pageWidth,
      height: pageHeight,
    );
  }
  var characters = 0;
  var covered = 0.0;
  for (final glyph in glyphs) {
    if (glyph.text.trim().isEmpty) continue;
    characters++;
    final width = (glyph.right - glyph.left).clamp(0, pageWidth);
    final height = (glyph.bottom - glyph.top).clamp(0, pageHeight);
    covered += width * height;
  }
  final words = buildWords(glyphs);
  final pageArea = (pageWidth <= 0 || pageHeight <= 0) ? 1.0 : pageWidth * pageHeight;
  return PageStats(
    characters: characters,
    words: words.length,
    // Character-level digit count overstates tokens; word-level is what the
    // classifier should see.
    numericTokens: _numericWordCount(words),
    coverage: (covered / pageArea).clamp(0, 1),
    width: pageWidth,
    height: pageHeight,
  );
}

int _numericWordCount(List<Word> words) {
  var count = 0;
  for (final word in words) {
    if (RegExp(r'\d').hasMatch(word.text)) count++;
  }
  return count;
}

/// Classifies a page from its embedded text alone.
///
/// The thresholds are deliberately conservative: a page is only trusted as
/// digital when it carries a substantial table-sized amount of text with digits.
/// A few characters (a letterhead, a stamp, a page number) are never enough.
PageKind classifyPage(PageStats stats) {
  if (stats.characters == 0) return PageKind.imageOnly;
  final substantial = stats.characters >= 200 &&
      stats.numericTokens >= 5 &&
      stats.coverage >= 0.02;
  if (substantial) return PageKind.digitalText;
  // Enough text that part of the page is real, but not enough to trust that it is
  // the whole page: OCR it and keep the embedded text where they overlap.
  if (stats.characters >= 40) return PageKind.hybrid;
  return PageKind.imageOnly;
}

/// After OCR, a page that produced almost nothing is reported as unusable rather
/// than as an empty result.
PageKind resolvePageKind(PageKind initial, {required int mergedWords}) {
  if (mergedWords < 3) return PageKind.unusable;
  return initial;
}
