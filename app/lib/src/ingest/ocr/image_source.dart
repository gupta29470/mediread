import 'dart:typed_data';
import 'dart:ui' as ui;

import '../table_parser.dart' show Glyph;
import 'page_source.dart';

/// A page that is a single raster image (a photo or screenshot of a report).
///
/// There is no text layer, so the document pipeline classifies it as
/// `image_only` and sends it to OCR. Coordinates stay in image pixels: the page
/// is treated as 1 px = 1 pt, which is enough for a layout parser that only uses
/// relative positions. Every row from such a page is therefore OCR-derived and
/// gated as review-only, exactly like a scanned PDF page.
class ImagePageSource implements PageSourceDocument {
  ImagePageSource._(this.pages);

  @override
  final List<PageSourcePage> pages;

  /// Decodes [bytes] (PNG/JPEG/WebP) and exposes it as a one-page document.
  static Future<ImagePageSource> open(Uint8List bytes) async {
    final codec = await ui.instantiateImageCodec(bytes);
    final frame = await codec.getNextFrame();
    final image = frame.image;
    try {
      final data = await image.toByteData(format: ui.ImageByteFormat.rawRgba);
      if (data == null) {
        throw StateError('the image could not be decoded');
      }
      // `ByteData.buffer` can be larger than the image; take exactly the view's
      // bytes, otherwise the OCR engine is handed a buffer whose length does not
      // match width × height × 4 and rejects the bitmap.
      final expected = image.width * image.height * 4;
      final rgba = data.buffer.asUint8List(data.offsetInBytes, expected);
      final page = _ImagePage(
        pixels: _rgbaToBgra(rgba),
        width: image.width.toDouble(),
        height: image.height.toDouble(),
      );
      return ImagePageSource._([page]);
    } finally {
      image.dispose();
      codec.dispose();
    }
  }

  @override
  Future<void> close() async {}

  static Uint8List _rgbaToBgra(Uint8List rgba) {
    final bgra = Uint8List(rgba.length);
    for (var i = 0; i + 3 < rgba.length; i += 4) {
      bgra[i] = rgba[i + 2];
      bgra[i + 1] = rgba[i + 1];
      bgra[i + 2] = rgba[i];
      bgra[i + 3] = rgba[i + 3];
    }
    return bgra;
  }
}

class _ImagePage implements PageSourcePage {
  _ImagePage({required this.pixels, required this.width, required this.height});

  final Uint8List pixels;

  @override
  final double width;

  @override
  final double height;

  @override
  int get number => 1;

  @override
  bool get isRotated => false;

  @override
  Future<List<Glyph>> loadGlyphs() async => const [];

  @override
  Future<RenderedPage> render(double dpi) async => RenderedPage(
        pixels: pixels,
        pixelWidth: width.round(),
        pixelHeight: height.round(),
        // Pixels are the page coordinate system for an image.
        pointsPerPixelX: 1,
        pointsPerPixelY: 1,
      );
}
