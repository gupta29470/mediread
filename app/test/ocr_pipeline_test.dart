import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:mediread_app/src/ingest/document_source.dart';
import 'package:mediread_app/src/ingest/lab_pipeline.dart';
import 'package:mediread_app/src/ingest/ocr/ocr_engine.dart';
import 'package:mediread_app/src/ingest/ocr/page_classification.dart';
import 'package:mediread_app/src/ingest/ocr/page_outcome.dart';
import 'package:mediread_app/src/ingest/ocr/page_source.dart';
import 'package:mediread_app/src/ingest/pdf_table_source.dart';
import 'package:mediread_app/src/ingest/table_parser.dart';

List<Glyph> chars(String text, double x, double y, {double size = 10}) {
  final result = <Glyph>[];
  var cursor = x;
  for (final char in text.split('')) {
    final width = char == ' ' ? size * 0.3 : size * 0.55;
    result.add(Glyph(char, cursor, y, cursor + width, y + size));
    cursor += width;
  }
  return result;
}

/// A page of a synthetic report: a header plus rows of `name technology value
/// unit` placed in the four columns the parser expects.
List<Glyph> tablePage({int rows = 20}) {
  final glyphs = <Glyph>[
    ...chars('TEST NAME', 40, 60),
    ...chars('TECHNOLOGY', 220, 60),
    ...chars('VALUE', 330, 60),
    ...chars('UNITS', 400, 60),
  ];
  for (var row = 0; row < rows; row++) {
    final y = 90.0 + row * 18;
    glyphs.addAll(chars('TEST ${row + 1}', 40, y));
    glyphs.addAll(chars('PHOTOMETRY', 220, y));
    glyphs.addAll(chars('${row + 10}.5', 330, y));
    glyphs.addAll(chars('mg/dL', 400, y));
  }
  return glyphs;
}

class FakePage implements PageSourcePage {
  FakePage({
    required this.number,
    this.glyphs = const [],
    this.failLoad = false,
    this.failRender = false,
    this.isRotated = false,
  });

  @override
  final int number;
  final List<Glyph> glyphs;
  final bool failLoad;
  final bool failRender;

  @override
  final bool isRotated;

  @override
  double get width => 595;

  @override
  double get height => 842;

  @override
  Future<List<Glyph>> loadGlyphs() async {
    if (failLoad) throw StateError('text layer unreadable');
    return glyphs;
  }

  @override
  Future<RenderedPage> render(double dpi) async {
    if (failRender) throw StateError('render failed');
    return RenderedPage(
      pixels: Uint8List(0),
      pixelWidth: 595,
      pixelHeight: 842,
      pointsPerPixelX: 1,
      pointsPerPixelY: 1,
    );
  }
}

class FakeDocument implements PageSourceDocument {
  FakeDocument(this.pages);

  @override
  final List<PageSourcePage> pages;

  @override
  Future<void> close() async {}
}

class FakeEngine implements OcrEngine {
  FakeEngine(this.words, {this.failure});

  final List<OcrWord> words;
  final Object? failure;
  int calls = 0;
  bool _ready = false;

  @override
  String get providerName => 'fake-ocr';

  @override
  bool get isReady => _ready;

  @override
  Future<void> initialize() async => _ready = true;

  @override
  Future<OcrPage> recognize(
    Uint8List bgraPixels, {
    required int pixelWidth,
    required int pixelHeight,
  }) async {
    calls++;
    if (failure != null) throw failure!;
    return OcrPage(words: words, provider: providerName, elapsedMs: 4);
  }

  @override
  Future<void> dispose() async => _ready = false;
}

Future<ReportExtraction> run(FakeDocument document, {OcrEngine? engine, List<ImportProgress>? progress}) =>
    extractDocumentRows(
      Uint8List(1),
      ocrEngine: engine,
      openDocument: (bytes) async => document,
      onProgress: progress?.add,
    );

void main() {
  test('a digital page keeps the existing path and never calls OCR', () async {
    final engine = FakeEngine(const []);
    final extraction = await run(FakeDocument([FakePage(number: 1, glyphs: tablePage())]), engine: engine);

    expect(engine.calls, 0);
    expect(extraction.rows, isNotEmpty);
    expect(extraction.usedOcr, isFalse);
    expect(extraction.pageOutcomes.single.kind, PageKind.digitalText);
    expect(extraction.rows.every((row) => !row.ocrDerived), isTrue);
    // Digital rows keep their normal gates.
    expect(gatesFor(extraction.rows.first, lookupKnownTest('Hemoglobin')), isNotNull);
  });

  test('a scanned page is recognised and its rows stay review-only', () async {
    final engine = FakeEngine(const [
      OcrWord(text: 'TEST', left: 40, top: 60, right: 62, bottom: 70),
      OcrWord(text: 'NAME', left: 68, top: 60, right: 95, bottom: 70),
      OcrWord(text: 'TECHNOLOGY', left: 220, top: 60, right: 280, bottom: 70),
      OcrWord(text: 'VALUE', left: 330, top: 60, right: 360, bottom: 70),
      OcrWord(text: 'UNITS', left: 400, top: 60, right: 430, bottom: 70),
      OcrWord(text: 'CHOLESTEROL', left: 40, top: 90, right: 110, bottom: 100),
      OcrWord(text: '113', left: 330, top: 90, right: 350, bottom: 100),
      OcrWord(text: 'mg/dL', left: 400, top: 90, right: 440, bottom: 100),
    ]);
    final extraction = await run(FakeDocument([FakePage(number: 1)]), engine: engine);

    expect(engine.calls, 1);
    expect(extraction.usedOcr, isTrue);
    expect(extraction.pageOutcomes.single.kind, PageKind.imageOnly);
    expect(extraction.pageOutcomes.single.ocrWords, 8);

    final row = extraction.rows.single;
    expect(row.name, 'Cholesterol');
    expect(row.valueText, '113');
    expect(row.unitText, 'mg/dL');
    expect(row.ocrDerived, isTrue);

    final gates = gatesFor(row, lookupKnownTest(row.name));
    expect(gates['identify_test'], isFalse);
    expect(gates['interpret_value'], isFalse);
    expect(gates['unit_comparison'], isFalse);
    expect(gates['range_comparison'], isFalse);
    expect(row.evidence?.notes.first, contains('Read with OCR'));
  });

  test('a page that fails does not destroy the other pages', () async {
    final extraction = await run(
      FakeDocument([
        FakePage(number: 1, failLoad: true, failRender: true),
        FakePage(number: 2, glyphs: tablePage()),
      ]),
      engine: FakeEngine(const []),
    );

    expect(extraction.rows, isNotEmpty);
    expect(extraction.warnings.any((warning) => warning.contains('Page 1')), isTrue);
    expect(extraction.pageOutcomes.first.kind, PageKind.unusable);
    expect(extraction.pageOutcomes.last.kind, PageKind.digitalText);
  });

  test('OCR failure is reported and the embedded text is kept', () async {
    final extraction = await run(
      FakeDocument([FakePage(number: 1, glyphs: tablePage())]),
      engine: FakeEngine(const [], failure: const OcrUnavailable('no model')),
    );

    // A digital page is not sent to OCR at all.
    expect(extraction.warnings, isEmpty);
    expect(extraction.rows, isNotEmpty);

    final scanned = await run(
      FakeDocument([FakePage(number: 1)]),
      engine: FakeEngine(const [], failure: const OcrUnavailable('no model')),
    );
    expect(scanned.rows, isEmpty);
    expect(scanned.warnings.single, contains('OCR is unavailable'));
    expect(scanned.pageOutcomes.single.kind, PageKind.unusable);
  });

  test('progress names the work per page', () async {
    final progress = <ImportProgress>[];
    await run(
      FakeDocument([FakePage(number: 1), FakePage(number: 2, glyphs: tablePage())]),
      engine: FakeEngine(const []),
      progress: progress,
    );
    expect(progress.map((item) => item.stage), contains(ImportStage.recognising));
    expect(progress.map((item) => item.stage), contains(ImportStage.parsing));
    expect(progress.last.stage, ImportStage.done);
  });
}
