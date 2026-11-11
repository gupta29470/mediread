import 'dart:typed_data';

/// One recognised word, in the pixel coordinates of the image handed to the
/// engine. The document layer is responsible for converting to PDF points.
class OcrWord {
  const OcrWord({
    required this.text,
    required this.left,
    required this.top,
    required this.right,
    required this.bottom,
    this.confidence,
  });

  final String text;
  final double left;
  final double top;
  final double right;
  final double bottom;

  /// Engine confidence in 0..1 when the engine reports one. ML Kit's text
  /// recognition does not expose per-word confidence, so this stays null and the
  /// extraction gates treat every OCR word as unverified regardless.
  final double? confidence;
}

class OcrPage {
  const OcrPage({
    required this.words,
    required this.provider,
    required this.elapsedMs,
    this.rawText = '',
  });

  final List<OcrWord> words;
  final String provider;
  final int elapsedMs;
  final String rawText;
}

/// Raised when the platform engine cannot run (missing model, unsupported
/// platform, initialisation failure). The pipeline degrades to digital-only and
/// reports the reason; it never invents text.
class OcrUnavailable implements Exception {
  const OcrUnavailable(this.message);

  final String message;

  @override
  String toString() => 'OcrUnavailable: $message';
}

/// A replaceable OCR provider. Implementations live behind this interface so the
/// document pipeline and the tests never depend on a specific SDK.
abstract class OcrEngine {
  /// Human-readable provider name, stored with every recognised word's page.
  String get providerName;

  /// Whether [initialize] has completed successfully.
  bool get isReady;

  /// Prepares the engine. Throws [OcrUnavailable] when it cannot run.
  Future<void> initialize();

  /// Recognises one rendered page image (BGRA8888 pixels, [pixelWidth] x
  /// [pixelHeight]). Coordinates in the result are pixels of that image.
  Future<OcrPage> recognize(
    Uint8List bgraPixels, {
    required int pixelWidth,
    required int pixelHeight,
  });

  Future<void> dispose();
}
