import 'dart:typed_data';

import 'package:google_mlkit_text_recognition/google_mlkit_text_recognition.dart';

import 'ocr_engine.dart';

/// ML Kit text recognition, Latin script, using the model bundled in the APK.
///
/// The bundled dependency (`com.google.mlkit:text-recognition`) ships the model
/// inside the application, so recognition works in airplane mode with no
/// download and no Play Services fetch. The model is ~10 MB of native libraries
/// (see docs/ocr_pipeline.md for the measured APK delta).
class MlKitOcrEngine implements OcrEngine {
  MlKitOcrEngine();

  TextRecognizer? _recognizer;
  bool _ready = false;

  @override
  String get providerName => 'mlkit-text-recognition-latin';

  @override
  bool get isReady => _ready;

  @override
  Future<void> initialize() async {
    if (_ready) return;
    try {
      _recognizer = TextRecognizer(script: TextRecognitionScript.latin);
      _ready = true;
    } catch (error) {
      throw OcrUnavailable('ML Kit text recognition could not start: $error');
    }
  }

  @override
  Future<OcrPage> recognize(
    Uint8List bgraPixels, {
    required int pixelWidth,
    required int pixelHeight,
  }) async {
    final recognizer = _recognizer;
    if (recognizer == null) {
      throw const OcrUnavailable('ML Kit text recognition is not initialised');
    }
    final stopwatch = Stopwatch()..start();
    // Passing the bitmap directly (rather than a PNG file) keeps the coordinate
    // space exactly the one we rendered: a PNG file is decoded by the platform
    // with density scaling, which silently changes the pixel size and therefore
    // every bounding box.
    final input = InputImage.fromBitmap(
      bitmap: bgraPixels,
      width: pixelWidth,
      height: pixelHeight,
    );
    {
      final recognised = await recognizer.processImage(input);
      final words = <OcrWord>[];
      for (final block in recognised.blocks) {
        for (final line in block.lines) {
          for (final element in line.elements) {
            final box = element.boundingBox;
            final text = element.text.trim();
            if (text.isEmpty) continue;
            words.add(OcrWord(
              text: text,
              left: box.left,
              top: box.top,
              right: box.right,
              bottom: box.bottom,
            ));
          }
        }
      }
      stopwatch.stop();
      return OcrPage(
        words: words,
        provider: providerName,
        elapsedMs: stopwatch.elapsedMilliseconds,
        rawText: recognised.text,
      );
    }
  }

  @override
  Future<void> dispose() async {
    await _recognizer?.close();
    _recognizer = null;
    _ready = false;
  }
}
