import 'lab_pipeline.dart';

/// Geometry-first table reconstruction.
///
/// Words and visual lines come from character rectangles; columns come from the
/// printed table header; a line only becomes a result when a test name and an
/// observed value occupy their own columns. Prose, citations, kit specifications
/// and reference blocks are classified before any row is emitted.
///
/// Reference ranges appear in two different shapes in real reports, and both are
/// handled here:
///
///  * **printed in a dedicated column** (`TEST NAME … VALUE UNITS Bio. Ref. Interval.`),
///    where the range is read from that column of the same line;
///  * **printed as a block below the result** (`Bio. Ref. Interval. :-` followed by
///    one or more lines), which is terminated by the next heading (`Method`,
///    `Clinical Significance`, `Specifications`, …), the next result, a page
///    break, or a line that is neither a range nor a labelled category.
///
/// A block with exactly one plain range is comparable. Anything else — two
/// labelled strata (`Male : 65 - 175` / `Female : 50 - 170`), several ranges on a
/// line, or a cut-off/category table (`DEFICIENCY : <20 || SUFFICIENCY : 30-100`)
/// — is kept as printed but marked stratified, so the comparison gate withholds
/// it instead of flattening it into a made-up interval.
class Glyph {
  const Glyph(this.text, this.left, this.top, this.right, this.bottom);

  final String text;
  final double left;
  final double top;
  final double right;
  final double bottom;

  double get width => right - left;
  double get height => bottom - top;
  double get centerX => (left + right) / 2;
}

class Word {
  const Word(this.text, this.left, this.top, this.right, this.bottom);

  final String text;
  final double left;
  final double top;
  final double right;
  final double bottom;

  double get centerX => (left + right) / 2;
  @override
  String toString() => text;
}

class VisualLine {
  const VisualLine(this.words);

  final List<Word> words;

  String get text => joinWords(words);
  double get top => words.map((w) => w.top).reduce((a, b) => a < b ? a : b);
  double get bottom => words.map((w) => w.bottom).reduce((a, b) => a > b ? a : b);
  double get left => words.map((w) => w.left).reduce((a, b) => a < b ? a : b);
}

List<Word> buildWords(List<Glyph> glyphs) {
  // Characters arrive in text order. Geometry only decides where a word breaks;
  // re-sorting by y interleaves columns and destroys the reading order.
  final words = <Word>[];
  var current = <Glyph>[];

  void flush() {
    if (current.isEmpty) return;
    words.add(Word(
      current.map((g) => g.text).join(),
      current.map((g) => g.left).reduce((a, b) => a < b ? a : b),
      current.map((g) => g.top).reduce((a, b) => a < b ? a : b),
      current.map((g) => g.right).reduce((a, b) => a > b ? a : b),
      current.map((g) => g.bottom).reduce((a, b) => a > b ? a : b),
    ));
    current = <Glyph>[];
  }

  for (final glyph in glyphs) {
    if (glyph.width <= 0.1 || glyph.height <= 0.1) {
      if (glyph.text.trim().isEmpty) flush();
      continue;
    }
    if (current.isEmpty) {
      current.add(glyph);
      continue;
    }
    final last = current.last;
    final sameLine = (glyph.bottom - last.bottom).abs() <=
        (0.3 * last.height > 2 ? 0.3 * last.height : 2);
    final gap = glyph.left - last.right;
    final threshold = 0.25 * ((last.height + glyph.height) / 2) + 1.5;
    if (sameLine && gap <= threshold && gap > -2 * threshold) {
      current.add(glyph);
    } else {
      flush();
      current.add(glyph);
    }
  }
  flush();
  return words;
}

List<VisualLine> buildLines(List<Word> words) {
  // pdfium splits a printed line into several text runs whose baselines can
  // differ by 1-3 pt, and emits a hyphen or a bullet as a run of its own. Group
  // by vertical overlap rather than by an exact baseline: runs of one visual
  // line overlap heavily, while consecutive printed lines do not overlap at all.
  final sorted = [...words]..sort((a, b) => a.top.compareTo(b.top));
  final lines = <VisualLine>[];
  var current = <Word>[];
  var groupTop = 0.0;
  var groupBottom = 0.0;

  for (final word in sorted) {
    if (current.isEmpty) {
      current.add(word);
      groupTop = word.top;
      groupBottom = word.bottom;
      continue;
    }
    final overlap = (word.bottom < groupBottom ? word.bottom : groupBottom) -
        (word.top > groupTop ? word.top : groupTop);
    final groupHeight = groupBottom - groupTop;
    final wordHeight = word.bottom - word.top;
    final shortest = wordHeight < groupHeight ? wordHeight : groupHeight;
    final tolerance = (groupHeight * 0.3 > 2 ? groupHeight * 0.3 : 2.0);
    final sameBaseline = (word.bottom - groupBottom).abs() <= tolerance;
    if (overlap >= 0.35 * shortest || sameBaseline) {
      current.add(word);
      if (word.top < groupTop) groupTop = word.top;
      if (word.bottom > groupBottom) groupBottom = word.bottom;
    } else {
      lines.add(VisualLine(current));
      current = <Word>[word];
      groupTop = word.top;
      groupBottom = word.bottom;
    }
  }
  if (current.isNotEmpty) lines.add(VisualLine(current));
  for (final line in lines) {
    line.words.sort((a, b) => a.left.compareTo(b.left));
  }
  return lines;
}

/// Join words as they were printed: typeset text has no gap inside a word, so a
/// tiny gap means the runs belong together (`CA` `-` `125` → `CA-125`), while a
/// real space gap means a space.
String joinWords(List<Word> words) {
  final buffer = StringBuffer();
  var previousJoinTight = false;
  for (var index = 0; index < words.length; index++) {
    if (index > 0) {
      final gap = words[index].left - words[index - 1].right;
      final tight = gap <= 1.2;
      final previousIsPunctuation = RegExp(r'^[^A-Za-z0-9]+$').hasMatch(words[index - 1].text);
      // A hyphen inside a token (`CA-125`) is tight on at least one side; a dash
      // used as a separator (`HDL CHOLESTEROL - DIRECT`) is spaced on both.
      if (!(tight || (previousIsPunctuation && previousJoinTight))) buffer.write(' ');
      previousJoinTight = tight;
    }
    buffer.write(words[index].text);
  }
  return buffer.toString();
}

/// Column boundaries taken from the printed header. Edges carry a small
/// tolerance because headers and their cells are rarely pixel aligned.
class _Columns {
  const _Columns({
    required this.nameRight,
    required this.valueStart,
    required this.unitStart,
    this.refStart,
    this.detected = true,
  });

  final double nameRight;
  final double valueStart;
  final double unitStart;
  final double? refStart;

  /// Whether a real header produced these boundaries. A synthetic fallback keeps
  /// headerless layouts parseable but must never be trusted for references.
  final bool detected;

  static const double edge = 8;

  static const fallback = _Columns(
    nameRight: 300,
    valueStart: 292,
    unitStart: 420,
    detected: false,
  );

  double get valueLeft => valueStart - edge;
  double get unitLeft => unitStart - edge;
  double? get refLeft => refStart == null ? null : refStart! - edge;

  /// Right edge of the value cell; the units (or reference) column owns what
  /// follows it, and must never be read as the reported value.
  double get valueRight => refLeft ?? unitLeft;
}

final RegExp _boundPattern = RegExp(
  r'([<>]=?)\s*(\d+(?:[.,]\d+)?)|less than\s*(\d+(?:[.,]\d+)?)|below\s*(\d+(?:[.,]\d+)?)',
  caseSensitive: false,
);
final RegExp _wordBoundPattern = RegExp(
  r'(\d+(?:[.,]\d+)?)\s*(?:mg/dl|mg|mmol/l|g/dl|gm/dl|%|u/l)?\s*or\s+(higher|more|greater)',
  caseSensitive: false,
);
final RegExp _rangePattern = RegExp(r'(\d+(?:[.,]\d+)?)\s*[-\u2013]\s*(\d+(?:[.,]\d+)?)');
final RegExp _ratioRangePattern =
    RegExp(r'(\d+(?:[.,]\d+)?)\s*:\s*(\d+(?:[.,]\d+)?)\s*[-\u2013]\s*(\d+(?:[.,]\d+)?)\s*:\s*(\d+(?:[.,]\d+)?)');
final RegExp _toRangePattern = RegExp(r'(\d+(?:[.,]\d+)?)\s*to\s*(\d+(?:[.,]\d+)?)');
final RegExp _citation =
    RegExp(r'\b(19|20)\d{2}\b.*[;:]|\bet al\b|J\.\s*Clin|N Engl J Med', caseSensitive: false);
final RegExp _specification =
    RegExp(r'precision|intra assay|inter assay|%cv|sensitivity|specificity|kit validation', caseSensitive: false);
final RegExp _stratum = RegExp(
  r'\b(male|female|adult|child|children|men|women|trimester|newborn|infant|paediatric|pediatric|elderly)\b',
  caseSensitive: false,
);
final RegExp _category = RegExp(
  r'\b(normal|prediabet\w*|diabet\w*|deficien\w*|insufficien\w*|sufficien\w*|toxicit\w*|'
  r'control|unsatisfactory|poor|mild|moderate|severe|borderline|desirable|optimal|high|low)\b',
  caseSensitive: false,
);
final RegExp _numeric = RegExp(r'^[<>]?=?[ ]*\d+(?:[.,]\d+)?$');
final RegExp _qualitative = RegExp(
    r'^(positive|negative|absent|present|nil|trace|normal|reactive|non[- ]?reactive|'
    r'clear|straw|pale|yellow|cloudy|turbid|detected|not detected|not seen|not found|'
    r'indeterminate|equivocal|inconclusive|borderline)$',
    caseSensitive: false);

final RegExp _headerNoise = RegExp(
  r'ref\.?\s*by|referred by|sample collected|barcode|printed (on|by)|page\s*:?\s*\d|'
  r'registration|uhid|invoice|address|contact|www\.|@',
  caseSensitive: false,
);

/// Headings that end a reference block. Anything printed after one of these
/// belongs to the report's prose about the test, not to its reference interval.
final RegExp _blockTerminator = RegExp(
  r'^(clinical significance|clinical remark|specifications?|kit validation|method|'
  r'references?\b|disclaimer|note\b|alert|please correlate|pregnancy reference|'
  r'guidance for|the biological reference|results should always be interpreted|'
  r'different laboratories|to diagnose and monitor|interpretation)',
  caseSensitive: false,
);

final RegExp _referenceHeading = RegExp(
  r'^(bio\.?\s*(ref|reference)|reference\s+(range|interval|value)|ref\.?\s*(range|interval)|'
  r'normal\s+(range|value))',
  caseSensitive: false,
);

/// Header cells that name a printed reference column. The reports seen so far
/// label it `Bio. Ref. Interval.`, `Reference Range`, `NORMAL RANGE`, `Ref. Range`
/// and `Biological Reference Interval`.
final RegExp _referenceColumnHeader = RegExp(
  r'^bio\.?$|bio\.?\s*ref|^ref\b|reference|normal\s+(range|value)|range\b|interval\b',
  caseSensitive: false,
);

final RegExp _blockCaption =
    RegExp(r'guideline|guidance|as per|per ADA|reference range', caseSensitive: false);

class TableParser {
  const TableParser();

  List<ParsedLabRow> parse(List<Glyph> glyphs) => parsePages([glyphs]);

  List<ParsedLabRow> parsePages(List<List<Glyph>> pages) {
    final rows = <ParsedLabRow>[];
    _Columns? columns;
    String? panel;
    for (var index = 0; index < pages.length; index++) {
      final result = _parseLines(buildLines(buildWords(pages[index])), columns, panel, index + 1);
      rows.addAll(result.rows);
      columns = result.columns ?? columns;
      panel = result.panel ?? panel;
    }
    return rows;
  }

  _PageResult _parseLines(
      List<VisualLine> lines, _Columns? columns, String? panel, int pageNumber) {
    // Layouts without a printed header still need a sane column split.
    var cols = columns ?? _Columns.fallback;
    final rows = <ParsedLabRow>[];
    ParsedLabRow? pending;
    double? pendingTop;
    final block = <_BlockLine>[];
    String? carryName;
    // Whether this block is a two-column table. Decided from its first line: a
    // block that starts in the name column is left aligned, and anything printed
    // to the right of it is a second table (guidance, staging), not this test's
    // reference interval.
    bool? blockLeftAligned;

    String blockText(VisualLine line) {
      final left = line.words.where((word) => word.left < cols.nameRight).toList();
      final leftText = joinWords(left).trim();
      final fullText = line.text.trim();
      blockLeftAligned ??= left.isNotEmpty && left.length < line.words.length;
      if (blockLeftAligned == true) return leftText;
      return fullText;
    }

    // Close the open reference block and emit the pending row with whatever
    // reference the block established.
    void flush() {
      final row = pending;
      final collected = [...block];
      pending = null;
      pendingTop = null;
      block.clear();
      blockLeftAligned = null;
      if (row == null) return;
      rows.add(_withBlockReference(row, collected));
    }

    for (var i = 0; i < lines.length; i++) {
      final line = lines[i];
      final text = line.text.trim();
      if (text.isEmpty) continue;
      final lower = text.toLowerCase();

      if (RegExp(r'^(test name|investigation|parameter)\b', caseSensitive: false).hasMatch(lower)) {
        if (RegExp(r'value|observation|result').hasMatch(lower)) cols = _columnsFrom(line);
        carryName = null;
        flush();
        continue;
      }
      if (_headerNoise.hasMatch(lower)) {
        carryName = null;
        flush();
        continue;
      }
      // A line that carries a value in the value column is a result, never a
      // section heading, however it is capitalised (e.g. `RH TYPING POSITIVE`
      // where the value is qualitative rather than a number).
      if (_looksLikePanelHeading(text) &&
          _valueToken(line, cols) == null &&
          !_nextLineCarriesResult(i, lines, cols)) {
        carryName = null;
        flush();
        panel = _titleCase(text);
        continue;
      }
      // A reference heading must be read before the terminator list: reports label
      // the block `Reference Range :`, and a bare `Reference :` is a citation.
      if (_referenceHeading.hasMatch(text)) {
        // Opens (or re-labels) the block that follows the pending row.
        continue;
      }
      if (_blockTerminator.hasMatch(text) || _specification.hasMatch(lower) || _citation.hasMatch(text)) {
        carryName = null;
        flush();
        continue;
      }

      final value = _valueToken(line, cols);
      if (value != null) {
        final ownName = _nameText(line, cols);
        // The row's own name wins over a carried one: a carried line is usually a
        // panel title printed above the table (`Complete Urinogram`), not part of
        // the test name. It is only joined when the own name is a parenthetical
        // continuation of a wrapped name (`… CAPACITY` + `(TIBC)`).
        final joined = carryName != null && _isNameContinuation(ownName);
        final carried = ownName.isEmpty && carryName != null;
        final name = ownName.isEmpty
            ? (carryName ?? '')
            : (joined ? '$carryName $ownName' : ownName);
        // On a page with no printed header there is nothing to prove that the
        // number belongs to a test name printed above it: address blocks and
        // summary tables sit in the same region. Require the row's own name.
        if (carried && !cols.detected) {
          carryName = null;
          continue;
        }
        carryName = null;
        final row = _rowFrom(line, cols, panel,
            name: name, page: pageNumber, carriedName: carried, joinedName: joined);
        flush();
        if (row != null) {
          pending = row;
          pendingTop = line.top;
        }
        continue;
      }

      final range = _parseRange(text);
      if (range != null || _looksLikeCategoryLine(text)) {
        if (pending != null && _blockAccepts(block, line, pendingTop)) {
          final blockLine = blockText(line);
          if (blockLine.isEmpty) continue;
          block.add(_BlockLine(blockLine, _parseRange(blockLine) ?? range));
        }
        continue;
      }

      final onlyName = _nameOnlyText(line, cols);
      if (onlyName != null) {
        // A test name printed on its own line, with the value on the next line.
        carryName = carryName == null ? onlyName : '$carryName $onlyName';
        continue;
      }

      // A fragment with no letters or digits (a hyphen or bullet split out of the
      // previous line by pdfium) carries no meaning and must not close the block.
      if (RegExp(r'^[^A-Za-z0-9]+$').hasMatch(text)) continue;

      // Prose, a caption or a heading we do not model: it ends the block and it
      // must not be carried into the next row.
      if (_blockCaption.hasMatch(text) && pending != null) continue;
      carryName = null;
      flush();
    }
    flush();
    return _PageResult(rows: rows, columns: cols, panel: panel);
  }

  /// A block only owns lines that sit just below its row and that still look
  /// like reference material. This stops a range far down the page — a
  /// pregnancy table, an education table, the next test's range — from being
  /// attached to an unrelated result.
  bool _blockAccepts(List<_BlockLine> block, VisualLine line, double? rowTop) {
    if (block.length >= 10) return false;
    if (rowTop == null) return false;
    return line.top - rowTop <= 220;
  }

  /// A block line may share its baseline with a second table printed to the
  /// right (guidance tables, stage tables). The primary reference table is the
  /// one that starts in the name column, so keep that part and drop the rest.
  bool _looksLikeCategoryLine(String text) {
    if (text.length > 120) return false;
    if (!RegExp(r'\d').hasMatch(text)) return false;
    if (text.contains('||') || _category.hasMatch(text)) return true;
    final rangeHits = _rangePattern.allMatches(text).length + _boundPattern.allMatches(text).length;
    return rangeHits >= 2;
  }

  _Columns _columnsFrom(VisualLine line) {
    double? valueLeft, unitLeft, refLeft, techLeft;
    for (final word in line.words) {
      final lower = word.text.toLowerCase();
      if (lower.startsWith('value') || lower.startsWith('observation') || lower == 'result') {
        valueLeft = word.left;
      } else if (lower.startsWith('unit')) {
        unitLeft = word.left;
      } else if (lower.startsWith('technolog')) {
        techLeft = word.left;
      } else if (_referenceColumnHeader.hasMatch(lower)) {
        // The first word of the group wins: pdfium splits `Bio. Ref. Interval.`
        // into separate words, and the range cell starts under `Bio.`, not under
        // `Interval.`.
        refLeft ??= word.left;
      }
    }
    final resolvedValue = valueLeft ?? 420;
    return _Columns(
      nameRight: (techLeft ?? resolvedValue) - 20,
      valueStart: resolvedValue,
      unitStart: unitLeft ?? (refLeft ?? resolvedValue + 90),
      refStart: refLeft,
    );
  }

  /// The value cell: only words inside the value column, never the units or the
  /// printed reference column.
  String? _valueToken(VisualLine line, _Columns columns) {
    for (final word in line.words) {
      if (word.left < columns.valueLeft) continue;
      if (word.left >= columns.valueRight) continue;
      if (_numeric.hasMatch(word.text) || _qualitative.hasMatch(word.text)) return word.text;
    }
    return null;
  }

  String _nameText(VisualLine line, _Columns columns) =>
      joinWords(line.words.where((word) => word.left < columns.nameRight).toList()).trim();

  /// Name text for a line that carries no value in the value column, or null
  /// when the line is not plausibly a lone test name.
  String? _nameOnlyText(VisualLine line, _Columns columns) {
    final name = _nameText(line, columns);
    if (!_plausibleTestName(name)) return null;
    // Nothing may occupy the value cell: the value is on the next line.
    for (final word in line.words) {
      if (word.left >= columns.valueLeft && word.left < columns.valueRight) return null;
    }
    return name;
  }

  bool _plausibleTestName(String name) {
    if (name.length < 2 || name.length > 60) return false;
    if (!RegExp(r'[A-Za-z]{2,}').hasMatch(name)) return false;
    if (RegExp(r'[:\]\[%<>=]|\|\||,$').hasMatch(name)) return false;
    if (name.endsWith('.')) return false;
    final words = name.split(RegExp(r'\s+')).where((word) => word.isNotEmpty).length;
    if (words > 7) return false;
    if (_specification.hasMatch(name) || _citation.hasMatch(name)) return false;
    if (_category.hasMatch(name)) return false;
    if (RegExp(r'^(less|greater|normal|below|above|bio\.?\s*ref|reference|ref|note|method)\b',
            caseSensitive: false)
        .hasMatch(name)) {
      return false;
    }
    // A name must not be mostly punctuation or digits.
    final letters = RegExp(r'[A-Za-z]').allMatches(name).length;
    if (letters / name.length < 0.5) return false;
    return true;
  }

  /// A wrapped test name splits as `TOTAL IRON BINDING CAPACITY` + `(TIBC)`; the
  /// second line is a parenthetical fragment rather than a name of its own.
  bool _isNameContinuation(String name) {
    final trimmed = name.trim();
    if (trimmed.startsWith('(')) return true;
    return trimmed.endsWith(')') && !trimmed.contains(' ');
  }

  /// True when the next line is a result line that has no name of its own, or
  /// whose name is a parenthetical continuation. Such a line means the current
  /// all-caps line is a wrapped test name, not a section heading.
  bool _nextLineCarriesResult(int index, List<VisualLine> lines, _Columns columns) {
    for (var j = index + 1; j < lines.length && j <= index + 2; j++) {
      final text = lines[j].text.trim();
      if (text.isEmpty) continue;
      if (_valueToken(lines[j], columns) == null) return false;
      final name = _nameText(lines[j], columns);
      return name.isEmpty || _isNameContinuation(name);
    }
    return false;
  }

  bool _looksLikePanelHeading(String text) {
    if (text.length < 6 || text.length > 60) return false;
    if (RegExp(r'\d').hasMatch(text)) return false;
    return text == text.toUpperCase() && text.split(' ').length >= 2;
  }

  /// Title-case each word, capitalising its first letter even after a bracket or
  /// hyphen so `(TIBC)` becomes `(Tibc)` rather than `(tibc)`.
  String _titleCase(String value) => value.toLowerCase().split(' ').map((word) {
        final letter = RegExp(r'[a-z]').firstMatch(word);
        if (letter == null) return word;
        final index = letter.start;
        return '${word.substring(0, index)}${word[index].toUpperCase()}${word.substring(index + 1)}';
      }).join(' ');

  _Range? _parseRange(String raw) {
    final text = raw
        .replaceAllMapped(RegExp(r'([<>])\s*='), (m) => '${m.group(1)}=')
        .replaceAllMapped(RegExp(r'([<>])\s+(?=\d)'), (m) => m.group(1)!);

    final ratio = _ratioRangePattern.firstMatch(text);
    if (ratio != null) {
      double? num(String? whole, String? part) {
        final a = double.tryParse((whole ?? '').replaceAll(',', '.'));
        final b = double.tryParse((part ?? '').replaceAll(',', '.'));
        if (a == null || b == null || b == 0) return null;
        return a / b;
      }

      final low = num(ratio.group(1), ratio.group(2));
      final high = num(ratio.group(3), ratio.group(4));
      if (low != null && high != null) {
        return _Range(ratio.group(0)!.trim(), low: low, high: high);
      }
    }

    final bound = _boundPattern.firstMatch(text);
    if (bound != null) {
      final operator = bound.group(1) ?? '<';
      final number = bound.group(2) ?? bound.group(3) ?? bound.group(4);
      final value = double.tryParse((number ?? '').replaceAll(',', '.'));
      if (value == null) return null;
      final normalised = operator.replaceAll('=', '');
      return _Range(
        bound.group(0)!.trim(),
        low: normalised.startsWith('>') ? value : null,
        high: normalised.startsWith('<') ? value : null,
        operator: normalised.startsWith('<') ? '<' : '>',
      );
    }

    final wordBound = _wordBoundPattern.firstMatch(text);
    if (wordBound != null) {
      final value = double.tryParse((wordBound.group(1) ?? '').replaceAll(',', '.'));
      if (value == null) return null;
      return _Range(wordBound.group(0)!.trim(), low: value, operator: '>');
    }

    final match = _rangePattern.firstMatch(text) ?? _toRangePattern.firstMatch(text);
    if (match == null) return null;
    final low = double.tryParse(match.group(1)!.replaceAll(',', '.'));
    final high = double.tryParse(match.group(2)!.replaceAll(',', '.'));
    if (low == null || high == null) return null;
    return _Range('${match.group(1)}-${match.group(2)}', low: low, high: high);
  }

  ParsedLabRow? _rowFrom(
    VisualLine line,
    _Columns columns,
    String? panel, {
    required String name,
    required int page,
    bool carriedName = false,
    bool joinedName = false,
  }) {
    if (name.length < 2 || !RegExp(r'[A-Za-z]{2,}').hasMatch(name)) return null;
    // A sentence is not a test name: prose paragraphs sit under the table and
    // carry numbers that would otherwise look like values.
    final words = name.split(RegExp(r'\s+')).where((word) => word.isNotEmpty).length;
    if (words > 7 || name.length > 60 || name.contains(',') || name.contains(':') ||
        line.text.trim().endsWith('.')) {
      return null;
    }
    if (RegExp(r'^(less|greater|normal|bio\.?\s*ref|reference|ref)\b', caseSensitive: false)
        .hasMatch(name)) {
      return null;
    }
    if (_specification.hasMatch(name) || _citation.hasMatch(name)) return null;
    // `<200`, `100 - 129`, `DESIRABLE` — a printed reference table, not a test.
    if (RegExp(r'[<>]|\d+\s*[-\u2013]\s*\d+').hasMatch(name)) return null;
    if (_category.hasMatch(name) && !RegExp(r'[A-Za-z]{4,}').hasMatch(name.replaceAll(_category, ''))) {
      return null;
    }

    // A qualitative result can be more than one word ("Not Detected"), so the
    // joined value cell is checked before the per-word scan.
    final valueWords = line.words
        .where((word) => word.left >= columns.valueLeft && word.left < columns.valueRight)
        .toList();
    final cellText = joinWords(valueWords).trim();
    if (cellText.isNotEmpty && _qualitative.hasMatch(cellText)) {
      final reference = _columnReference(line, columns);
      final unitText = _unitText(line, columns);
      return ParsedLabRow(
        name: _titleCase(name.replaceAll(RegExp(r'[-:]+$'), '').trim()),
        panel: panel,
        valueText: cellText.toLowerCase(),
        valueKind: 'qualitative',
        unitText: unitText,
        referenceText: reference?.text,
        low: reference?.low,
        high: reference?.high,
        operator: reference?.operator,
        valueVerified: true,
        unitVerified: unitText != null,
        referenceVerified: reference != null,
        stratified: reference?.stratified ?? false,
        evidence: ExtractionEvidence(
          page: page,
          nameConfidence: carriedName ? 0.85 : (joinedName ? 0.8 : 1),
          valueConfidence: 1,
          unitConfidence: unitText == null ? 0 : 1,
          classificationConfidence: columns.detected ? 1 : 0.5,
          notes: [
            if (!columns.detected) 'No printed column header was found; column positions were inferred.',
            if (carriedName) 'The test name was printed on the line above its value.',
            if (unitText == null) 'No unit was printed for this result.',
          ],
        ).copyWith(
          referenceConfidence: reference == null ? 0 : (reference.stratified ? 0.4 : 0.95),
        ),
      );
    }

    String? valueText;
    var censored = false;
    String? pendingSign;
    for (final word in line.words) {
      if (word.left < columns.valueLeft || word.left >= columns.valueRight) continue;
      if (RegExp(r'^[<>]=?$').hasMatch(word.text)) {
        pendingSign = word.text.replaceAll('=', '');
        continue;
      }
      final match = RegExp(r'^([<>]?=?)\s*(\d+(?:[.,]\d+)?)$').firstMatch(word.text);
      if (match != null) {
        final sign = (match.group(1)!.replaceAll('=', '').isNotEmpty
                ? match.group(1)!.replaceAll('=', '')
                : (pendingSign ?? ''))
            .trim();
        final number = match.group(2)!.replaceAll(',', '.');
        censored = sign.isNotEmpty && double.tryParse(number) != null;
        valueText = censored ? '$sign$number' : number;
        break;
      }
      pendingSign = null;
      if (_qualitative.hasMatch(word.text)) {
        valueText = word.text.toLowerCase();
        break;
      }
    }
    if (valueText == null) return null;

    final unitText = _unitText(line, columns);
    if (unitText != null && _category.hasMatch(unitText) && !RegExp(r'[%/^]').hasMatch(unitText)) {
      return null;
    }
    final reference = _columnReference(line, columns);

    final numeric = double.tryParse(valueText);
    final qualitative = _qualitative.hasMatch(valueText);
    if (numeric == null && !qualitative && !censored) return null;

    final notes = <String>[
      if (!columns.detected) 'No printed column header was found; column positions were inferred.',
      if (carriedName) 'The test name was printed on the line above its value.',
      if (joinedName) 'The test name is wrapped over two printed lines.',
      if (censored) 'The printed value is a bound (${valueText.trim()}), not a measured number.',
      if (unitText == null) 'No unit was printed for this result.',
    ];

    final evidence = ExtractionEvidence(
      page: page,
      nameConfidence: carriedName ? 0.85 : (joinedName ? 0.8 : 1),
      valueConfidence: censored ? 0.5 : 1,
      unitConfidence: unitText == null ? 0 : 1,
      classificationConfidence: columns.detected ? 1 : 0.5,
      notes: notes,
    );

    return ParsedLabRow(
      name: _titleCase(name.replaceAll(RegExp(r'[-:]+$'), '').trim()),
      panel: panel,
      valueText: valueText,
      valueKind: qualitative ? 'qualitative' : 'numeric',
      unitText: unitText,
      referenceText: reference?.text,
      low: reference?.low,
      high: reference?.high,
      operator: reference?.operator,
      valueVerified: !censored,
      unitVerified: unitText != null,
      referenceVerified: reference != null,
      stratified: reference?.stratified ?? false,
      evidence: evidence.copyWith(referenceConfidence: reference?.stratified == true ? 0.4 : (reference == null ? 0 : 0.95)),
    );
  }

  String? _unitText(VisualLine line, _Columns columns) {
    final parts = <Word>[];
    for (final word in line.words) {
      if (word.left < columns.unitLeft) continue;
      final refLeft = columns.refLeft;
      if (refLeft != null && word.left >= refLeft) break;
      if (parts.isEmpty && !RegExp(r'[A-Za-z%µ]').hasMatch(word.text)) continue;
      parts.add(word);
    }
    final text = joinWords(parts).trim();
    // A printed dash means the report has no unit for this test.
    if (text.isEmpty || RegExp(r'^[-\u2013\u2014]+$').hasMatch(text)) return null;
    return text;
  }

  /// A reference printed in its own column of the same line.
  _Reference? _columnReference(VisualLine line, _Columns columns) {
    final refLeft = columns.refLeft;
    if (refLeft == null) return null;
    final text =
        joinWords(line.words.where((word) => word.left >= refLeft).toList()).trim();
    if (text.isEmpty || RegExp(r'^[-\u2013\u2014\s]+$').hasMatch(text)) return null;
    final range = _parseRange(text);
    final hits = _rangePattern.allMatches(text).length + _boundPattern.allMatches(text).length;
    final stratified = _stratum.hasMatch(text) || hits > 1;
    if (stratified) return _Reference(_condense(text), stratified: true);
    if (range == null) return _Reference(_condense(text), stratified: true);
    return _Reference(range.text, low: range.low, high: range.high, operator: range.operator);
  }

  ParsedLabRow _withBlockReference(ParsedLabRow row, List<_BlockLine> block) {
    if (row.referenceText != null) return row; // printed in the row's own column
    if (block.isEmpty) {
      final evidence = row.evidence;
      if (evidence == null) return row;
      return row.withEvidence(evidence.copyWith(notes: [
        ...evidence.notes,
        'No reference range was printed for this result.',
      ]));
    }
    final ranges = [for (final line in block) if (line.range != null) line.range!];
    final single = block.length == 1 &&
        ranges.length == 1 &&
        !_stratum.hasMatch(block.single.text) &&
        !block.single.text.contains('||');
    if (single) {
      return row.withReference(
        text: ranges.single.text,
        low: ranges.single.low,
        high: ranges.single.high,
        operator: ranges.single.operator,
        referenceConfidence: 0.95,
      );
    }
    final evidence = row.evidence;
    return row
        .withReference(
          text: _condense(block.map((line) => line.text).join(' | ')),
          stratified: true,
          referenceConfidence: 0.4,
        )
        .withEvidence(evidence == null
            ? const ExtractionEvidence(page: 0, referenceConfidence: 0.4)
            : evidence.copyWith(
                referenceConfidence: 0.4,
                notes: [
                  ...evidence.notes,
                  'The printed reference is a category or stratified table, so no comparison is shown.',
                ],
              ));
  }

  String _condense(String text, {int max = 120}) {
    final clean = text
        .replaceAllMapped(RegExp(r'([<>])\s*='), (m) => '${m.group(1)}=')
        .replaceAll('||', '|')
        .replaceAll(RegExp(r'\s+'), ' ')
        .trim();
    if (clean.length <= max) return clean;
    // An ASCII ellipsis: the PDF export's built-in font has no U+2026.
    return '${clean.substring(0, max - 3).trimRight()}...';
  }
}

class _PageResult {
  const _PageResult({required this.rows, this.columns, this.panel});
  final List<ParsedLabRow> rows;
  final _Columns? columns;
  final String? panel;
}

class _Range {
  const _Range(this.text, {this.low, this.high, this.operator});
  final String text;
  final double? low;
  final double? high;
  final String? operator;
}

class _Reference {
  const _Reference(this.text, {this.low, this.high, this.operator, this.stratified = false});
  final String text;
  final double? low;
  final double? high;
  final String? operator;
  final bool stratified;
}

class _BlockLine {
  const _BlockLine(this.text, this.range);
  final String text;
  final _Range? range;
}
