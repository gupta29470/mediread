import 'dart:typed_data';

import 'package:flutter/foundation.dart' show kDebugMode;

import '../ingest/lab_pipeline.dart';
import 'ocr/geometry.dart';
import 'ocr/image_source.dart';
import 'ocr/ocr_engine.dart';
import 'ocr/page_classification.dart';
import 'ocr/page_outcome.dart';
import 'ocr/page_source.dart';
import 'pdf_table_source.dart';
import 'table_parser.dart';

/// How many OCR words a page must contribute before its rows are marked as
/// OCR-derived. A digital page that was OCR'd by mistake contributes almost
/// nothing after de-duplication, so it is not downgraded to review.
const int kOcrRowThreshold = 5;

/// The single document pipeline: embedded text where it is usable, OCR where it
/// is not, one geometry representation, one table parser, one set of gates.
///
/// Every page is classified from its own text layer. Digital pages keep the
/// existing pdfium path untouched; scanned pages are rendered, recognised and
/// converted into the same [Glyph] stream; hybrid pages keep their embedded text
/// and only gain OCR words that do not overlap it. A failure on one page is
/// recorded and the remaining pages still produce results.
Future<ReportExtraction> extractDocumentRows(
  Uint8List bytes, {
  OcrEngine? ocrEngine,
  void Function(ImportProgress progress)? onProgress,
  double ocrDpi = 200,
  Future<PageSourceDocument> Function(Uint8List bytes)? openDocument,
}) async {
  PageSourceDocument? document;
  try {
    document = await (openDocument ?? openPdfDocument)(bytes);
  } catch (error) {
    return ReportExtraction(
      rows: const [],
      text: '',
      pages: 0,
      warnings: ['This PDF could not be opened: $error'],
    );
  }

  final pages = <List<Glyph>>[];
  final outcomes = <PageOutcome>[];
  final warnings = <String>[];
  final textBuffer = StringBuffer();
  final tokenDump = StringBuffer();
  var provider = '';

  try {
    final total = document.pages.length;
    if (total == 0) {
      warnings.add('This PDF has no pages.');
    }
    for (var index = 0; index < total; index++) {
      final page = document.pages[index];
      final pageNumber = page.number;
      final label = 'page $pageNumber of $total';
      onProgress?.call(ImportProgress(
        stage: ImportStage.inspecting,
        page: index + 1,
        total: total,
        message: 'Inspecting $label',
      ));

      List<Glyph> embedded = const [];
      try {
        embedded = await page.loadGlyphs();
      } catch (error) {
        warnings.add('Page $pageNumber: the text layer could not be read ($error).');
      }
      if (embedded.isNotEmpty) textBuffer.writeln(embedded.map((g) => g.text).join());

      final stats = pageStats(embedded, page.width, page.height);
      var kind = classifyPage(stats);
      var ocrWords = 0;
      var addedWords = 0;
      var droppedWords = 0;
      var ocrMs = 0;
      var renderMs = 0;
      String? warning;

      final needsOcr = kind != PageKind.digitalText;
      if (!needsOcr) {
        // Digital page: the pdfium path is used exactly as before.
      } else if (ocrEngine == null) {
        warning = 'Page $pageNumber needs OCR (${kind.label}), but OCR is not '
            'available on this device; only its embedded text was used.';
      } else if (page.isRotated && embedded.isNotEmpty) {
        warning = 'Page $pageNumber is rotated; OCR was skipped so the text layer '
            'and OCR coordinates are not mixed.';
      } else {
        try {
          onProgress?.call(ImportProgress(
            stage: ImportStage.rendering,
            page: index + 1,
            total: total,
            message: 'Rendering $label',
          ));
          await ocrEngine.initialize();
          provider = ocrEngine.providerName;
          final renderWatch = Stopwatch()..start();
          final rendered = await page.render(ocrDpi);
          renderMs = renderWatch.elapsedMilliseconds;

          onProgress?.call(ImportProgress(
            stage: ImportStage.recognising,
            page: index + 1,
            total: total,
            message: 'Recognising text on $label',
          ));
          final ocrPage = await ocrEngine.recognize(
            rendered.pixels,
            pixelWidth: rendered.pixelWidth,
            pixelHeight: rendered.pixelHeight,
          );
          ocrMs = ocrPage.elapsedMs;
          ocrWords = ocrPage.words.length;
          if (kDebugMode) {
            final maxX = ocrPage.words.fold<double>(0, (m, w) => w.right > m ? w.right : m);
            final maxY = ocrPage.words.fold<double>(0, (m, w) => w.bottom > m ? w.bottom : m);
            tokenDump.writeln('render|$pageNumber|px=${rendered.pixelWidth}x${rendered.pixelHeight}'
                '|bytes=${rendered.pixels.length}|ppp=${rendered.pointsPerPixelX.toStringAsFixed(4)}'
                '|words=${ocrPage.words.length}|maxX=${maxX.toStringAsFixed(0)}'
                '|maxY=${maxY.toStringAsFixed(0)}');
            for (final word in ocrPage.words) {
              tokenDump.writeln('$pageNumber|${word.text}|'
                  '${word.left.toStringAsFixed(1)}|${word.top.toStringAsFixed(1)}|'
                  '${word.right.toStringAsFixed(1)}|${word.bottom.toStringAsFixed(1)}');
            }
          }

          onProgress?.call(ImportProgress(
            stage: ImportStage.merging,
            page: index + 1,
            total: total,
            message: 'Merging text on $label',
          ));
          final ocrGlyphs = ocrWordsToGlyphs(ocrPage.words, rendered);
          final merged = mergeOcrGlyphs(embedded, ocrGlyphs);
          embedded = merged.glyphs;
          addedWords = merged.addedWords;
          droppedWords = merged.droppedWords;
          textBuffer.writeln(ocrPage.rawText);
        } on OcrUnavailable catch (error) {
          warning = 'OCR is unavailable: ${error.message}';
        } catch (error) {
          warning = 'Page $pageNumber could not be recognised ($error).';
        }
      }

      final mergedWords = countWords(embedded);
      kind = resolvePageKind(kind, mergedWords: mergedWords);
      if (kind == PageKind.unusable) {
        warning ??= 'Page $pageNumber has no readable text.';
      }
      if (warning != null) warnings.add(warning);

      pages.add(embedded);
      outcomes.add(PageOutcome(
        number: pageNumber,
        kind: kind,
        embeddedChars: stats.characters,
        ocrWords: ocrWords,
        addedWords: addedWords,
        droppedWords: droppedWords,
        renderMs: renderMs,
        ocrMs: ocrMs,
        warning: warning,
      ));
    }

    onProgress?.call(ImportProgress(
      stage: ImportStage.parsing,
      page: total,
      total: total,
      message: 'Reviewing extracted results',
    ));

    final ocrPageNumbers = {
      for (final outcome in outcomes)
        if (outcome.addedWords >= kOcrRowThreshold) outcome.number,
    };
    final parsed = const TableParser().parsePages(pages);
    final rows = <ParsedLabRow>[
      for (final row in parsed)
        ocrPageNumbers.contains(row.evidence?.page) ? row.withOcr() : row,
    ];

    onProgress?.call(ImportProgress(
      stage: ImportStage.done,
      page: total,
      total: total,
      message: '${rows.length} results',
    ));

    return ReportExtraction(
      rows: rows,
      text: textBuffer.toString(),
      pages: total,
      pageOutcomes: outcomes,
      warnings: warnings,
      usedOcr: ocrPageNumbers.isNotEmpty,
      ocrProvider: provider,
      debugOcrTokens: tokenDump.toString(),
      debugLines: kDebugMode ? _debugLines(pages) : '',
    );
  } finally {
    await document.close();
  }
}

/// Processes a single image (a gallery photo or screenshot) through the same
/// pipeline as a scanned PDF page: no text layer, OCR, common geometry, gates.
Future<ReportExtraction> extractImageRows(
  Uint8List bytes, {
  OcrEngine? ocrEngine,
  void Function(ImportProgress progress)? onProgress,
}) =>
    extractDocumentRows(
      bytes,
      ocrEngine: ocrEngine,
      onProgress: onProgress,
      openDocument: (_) => ImagePageSource.open(bytes),
    );

String _debugLines(List<List<Glyph>> pages) {
  final buffer = StringBuffer();
  for (var index = 0; index < pages.length; index++) {
    buffer.writeln('===== page ${index + 1}');
    for (final line in buildLines(buildWords(pages[index]))) {
      final words = line.words
          .map((word) => '${word.text}[${word.left.toStringAsFixed(0)}-'
              '${word.right.toStringAsFixed(0)}]')
          .join('  ');
      buffer.writeln('y=${line.top.toStringAsFixed(1)} | $words');
    }
  }
  return buffer.toString();
}
