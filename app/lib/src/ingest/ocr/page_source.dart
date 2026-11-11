import 'dart:typed_data';

import 'package:pdfrx/pdfrx.dart';

import '../table_parser.dart' show Glyph;

/// A word from a page, in PDF points with a top-down y axis — the coordinate
/// system the table parser already uses.
class SourceWord {
  const SourceWord({
    required this.text,
    required this.left,
    required this.top,
    required this.right,
    required this.bottom,
  });

  final String text;
  final double left;
  final double top;
  final double right;
  final double bottom;

  double get width => right - left;
  double get height => bottom - top;
}

/// A rendered page image plus the mapping back to PDF points.
class RenderedPage {
  const RenderedPage({
    required this.pixels,
    required this.pixelWidth,
    required this.pixelHeight,
    required this.pointsPerPixelX,
    required this.pointsPerPixelY,
  });

  /// BGRA8888 pixels, exactly [pixelWidth] x [pixelHeight] values.
  final Uint8List pixels;
  final int pixelWidth;
  final int pixelHeight;

  /// Multiply a pixel coordinate by these to get PDF points.
  final double pointsPerPixelX;
  final double pointsPerPixelY;

  double toPointX(double pixelX) => pixelX * pointsPerPixelX;
  double toPointY(double pixelY) => pixelY * pointsPerPixelY;
}

/// One page of a document, abstracted away from pdfium so the pipeline can be
/// exercised in tests with synthetic geometry.
abstract class PageSourcePage {
  int get number;

  /// Page size in PDF points (already rotated to the displayed orientation).
  double get width;
  double get height;

  /// True when the page carries a display rotation. Rotated pages are not merged
  /// with OCR output because the two coordinate frames differ.
  bool get isRotated;

  /// Characters with rectangles, in text order. Empty when there is no text
  /// layer; throws only if the page itself is unreadable.
  Future<List<Glyph>> loadGlyphs();

  /// Renders the whole page at [dpi] as BGRA pixels.
  Future<RenderedPage> render(double dpi);
}

abstract class PageSourceDocument {
  List<PageSourcePage> get pages;

  Future<void> close();
}

/// Opens a PDF through pdfium (pdfrx) as a page source.
Future<PageSourceDocument> openPdfDocument(Uint8List bytes) =>
    _PdfrxDocument.open(bytes);

class _PdfrxDocument implements PageSourceDocument {
  _PdfrxDocument(this._document, this.pages);

  final PdfDocument _document;

  @override
  final List<PageSourcePage> pages;

  static Future<_PdfrxDocument> open(Uint8List bytes) async {
    final document = await PdfDocument.openData(bytes);
    final pages = <PageSourcePage>[
      for (final page in document.pages) _PdfrxPage(page),
    ];
    return _PdfrxDocument(document, pages);
  }

  @override
  Future<void> close() async => _document.dispose();
}

class _PdfrxPage implements PageSourcePage {
  _PdfrxPage(this._page);

  final PdfPage _page;

  @override
  int get number => _page.pageNumber;

  @override
  double get width => _page.width;

  @override
  double get height => _page.height;

  @override
  bool get isRotated => _page.rotation != PdfPageRotation.none;

  @override
  Future<List<Glyph>> loadGlyphs() async {
    final raw = await _page.loadText();
    if (raw == null) return const [];
    final glyphs = <Glyph>[];
    final text = raw.fullText;
    final rects = raw.charRects;
    final count = text.length < rects.length ? text.length : rects.length;
    for (var i = 0; i < count; i++) {
      final rect = rects[i];
      // pdfium's y axis grows upward; the parser works top-down.
      glyphs.add(Glyph(text[i], rect.left, -rect.top, rect.right, -rect.bottom));
    }
    return glyphs;
  }

  @override
  Future<RenderedPage> render(double dpi) async {
    final scale = dpi / 72.0;
    final pixelWidth = (width * scale).round();
    final pixelHeight = (height * scale).round();
    // pdfrx draws the page at `fullWidth` x `fullHeight` pixels (defaults to the
    // page size in points, i.e. 72 DPI) into a `width` x `height` bitmap. Both
    // must be the bitmap size, otherwise the page is drawn at 1:1 in the corner.
    final image = await _page.render(
      width: pixelWidth,
      height: pixelHeight,
      fullWidth: pixelWidth.toDouble(),
      fullHeight: pixelHeight.toDouble(),
    );
    if (image == null) {
      throw StateError('page $number could not be rendered');
    }
    try {
      // pdfrx exposes a view over native memory; take an owned copy before the
      // image is disposed, otherwise the OCR engine reads freed memory.
      final pixels = Uint8List.fromList(image.pixels);
      return RenderedPage(
        pixels: pixels,
        pixelWidth: image.width,
        pixelHeight: image.height,
        // Map from the actual bitmap back to the page rectangle.
        pointsPerPixelX: width / image.width,
        pointsPerPixelY: height / image.height,
      );
    } finally {
      image.dispose();
    }
  }
}
