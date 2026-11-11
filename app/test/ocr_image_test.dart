import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter_test/flutter_test.dart';
import 'package:mediread_app/src/ingest/document_source.dart';
import 'package:mediread_app/src/ingest/lab_pipeline.dart';
import 'package:mediread_app/src/ingest/ocr/ocr_engine.dart';
import 'package:mediread_app/src/ingest/ocr/page_classification.dart';

/// A plain white PNG of the given size, used as a stand-in gallery photo.
Future<Uint8List> whitePng(int width, int height) async {
  final rgba = Uint8List(width * height * 4)..fillRange(0, width * height * 4, 255);
  final buffer = await ui.ImmutableBuffer.fromUint8List(rgba);
  final descriptor = ui.ImageDescriptor.raw(
    buffer,
    width: width,
    height: height,
    pixelFormat: ui.PixelFormat.rgba8888,
  );
  final codec = await descriptor.instantiateCodec();
  final frame = await codec.getNextFrame();
  final png = await frame.image.toByteData(format: ui.ImageByteFormat.png);
  frame.image.dispose();
  codec.dispose();
  descriptor.dispose();
  buffer.dispose();
  return png!.buffer.asUint8List();
}

class WordEngine implements OcrEngine {
  WordEngine(this.words);

  final List<OcrWord> words;
  int calls = 0;
  int lastPixelLength = 0;
  int lastWidth = 0;
  int lastHeight = 0;
  bool _ready = false;

  @override
  String get providerName => 'fake-ocr';

  @override
  bool get isReady => _ready;

  @override
  Future<void> initialize() async => _ready = true;

  @override
  Future<OcrPage> recognize(
    Uint8List pixels, {
    required int pixelWidth,
    required int pixelHeight,
  }) async {
    calls++;
    lastPixelLength = pixels.length;
    lastWidth = pixelWidth;
    lastHeight = pixelHeight;
    return OcrPage(words: words, provider: providerName, elapsedMs: 1);
  }

  @override
  Future<void> dispose() async => _ready = false;
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('a gallery image goes through OCR and stays review-only', () async {
    final png = await whitePng(600, 800);
    final engine = WordEngine(const [
      OcrWord(text: 'TEST', left: 40, top: 60, right: 62, bottom: 70),
      OcrWord(text: 'NAME', left: 68, top: 60, right: 95, bottom: 70),
      OcrWord(text: 'TECHNOLOGY', left: 220, top: 60, right: 280, bottom: 70),
      OcrWord(text: 'VALUE', left: 330, top: 60, right: 360, bottom: 70),
      OcrWord(text: 'UNITS', left: 400, top: 60, right: 430, bottom: 70),
      OcrWord(text: 'HAEMOGLOBIN', left: 40, top: 90, right: 115, bottom: 100),
      OcrWord(text: '9.0', left: 330, top: 90, right: 350, bottom: 100),
      OcrWord(text: 'g/dL', left: 400, top: 90, right: 425, bottom: 100),
    ]);

    final extraction = await extractImageRows(png, ocrEngine: engine);

    expect(engine.calls, 1);
    // The engine must receive exactly width × height × 4 bytes: a bigger buffer
    // (e.g. the whole ByteData backing store) is rejected by ML Kit at runtime.
    expect(engine.lastPixelLength, engine.lastWidth * engine.lastHeight * 4);
    expect(extraction.usedOcr, isTrue);
    expect(extraction.pageOutcomes.single.kind, PageKind.imageOnly);
    expect(extraction.rows, hasLength(1));

    final row = extraction.rows.single;
    expect(row.name, 'Haemoglobin');
    expect(row.valueText, '9.0');
    expect(row.unitText, 'g/dL');
    expect(row.ocrDerived, isTrue);

    final gates = gatesFor(row, lookupKnownTest(row.name));
    expect(gates['identify_test'], isFalse);
    expect(gates['interpret_value'], isFalse);
    expect(gates['unit_comparison'], isFalse);
    expect(gates['range_comparison'], isFalse);
  });

  test('multi-word qualitative results survive the OCR path', () async {
    final png = await whitePng(600, 800);
    final engine = WordEngine(const [
      OcrWord(text: 'TEST', left: 40, top: 60, right: 62, bottom: 70),
      OcrWord(text: 'NAME', left: 68, top: 60, right: 95, bottom: 70),
      OcrWord(text: 'TECHNOLOGY', left: 220, top: 60, right: 280, bottom: 70),
      OcrWord(text: 'VALUE', left: 330, top: 60, right: 360, bottom: 70),
      OcrWord(text: 'UNITS', left: 400, top: 60, right: 430, bottom: 70),
      OcrWord(text: 'HEMOGLOBIN', left: 40, top: 90, right: 115, bottom: 100),
      OcrWord(text: 'C', left: 120, top: 90, right: 130, bottom: 100),
      OcrWord(text: 'Not', left: 330, top: 90, right: 348, bottom: 100),
      OcrWord(text: 'Detected', left: 352, top: 90, right: 395, bottom: 100),
    ]);
    final extraction = await extractImageRows(png, ocrEngine: engine);
    expect(extraction.rows, hasLength(1));
    expect(extraction.rows.single.valueText, 'not detected');
    expect(extraction.rows.single.valueKind, 'qualitative');
    expect(extraction.rows.single.ocrDerived, isTrue);
  });

  test('a gallery image without OCR is reported, not guessed', () async {
    final png = await whitePng(600, 800);
    final extraction = await extractImageRows(png);

    expect(extraction.rows, isEmpty);
    expect(extraction.warnings.single, contains('OCR is not available'));
    expect(extraction.pageOutcomes.single.kind, PageKind.unusable);
  });
}
