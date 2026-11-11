import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/foundation.dart' show kDebugMode;
import 'package:flutter/material.dart';
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';

import '../ai/orchestrator.dart';
import '../export/report_pdf.dart';
import '../ingest/document_source.dart';
import '../ingest/lab_pipeline.dart';
import '../ingest/ocr/mlkit_ocr_engine.dart';
import '../ingest/ocr/ocr_engine.dart';
import '../ingest/ocr/page_outcome.dart';
import '../ingest/pdf_table_source.dart';
import '../presentation/result_presentation.dart';
import 'report_source.dart';
import 'result_card.dart';
import 'theme.dart';

/// Reads a report's bytes into rows. Injectable so the results screen can be
/// exercised in widget tests without pdfium or ML Kit (neither loads on the host).
typedef ReportLoader = Future<ReportExtraction> Function(
  Uint8List bytes, {
  void Function(ImportProgress progress)? onProgress,
});

/// The platform OCR provider, or null where there is none.
///
/// ML Kit's bundled Latin model is the selected provider; see docs/ocr_pipeline.md
/// for the measured comparison that led to it.
OcrEngine? createPlatformOcrEngine() {
  if (Platform.isAndroid || Platform.isIOS) return MlKitOcrEngine();
  return null;
}

/// The results screen: one scrolling page of expandable result cards.
///
/// It opens with a report that was already picked, so there is no "choose a
/// report" step here. The app bar carries "choose another PDF" for a second
/// import, and the header row carries the file, the counts and the export.
class ImportPage extends StatefulWidget {
  const ImportPage({
    super.key,
    required this.orchestrator,
    required this.modelReady,
    required this.onSetupModel,
    required this.initial,
    this.loader,
    this.ocrEngineFactory,
  });

  final ExplanationOrchestrator orchestrator;
  final bool modelReady;
  final VoidCallback onSetupModel;
  final PickedReport initial;
  final ReportLoader? loader;

  /// Provider used by the default loader. Tests pass a fake through [loader].
  final OcrEngine? Function()? ocrEngineFactory;

  @override
  State<ImportPage> createState() => _ImportPageState();
}

class _ImportPageState extends State<ImportPage> {
  bool _busy = true;
  String? _error;
  String? _fileName;
  double? _quality;
  List<ParsedLabRow> _rows = const [];
  ImportProgress? _progress;
  List<String> _warnings = const [];
  bool _usedOcr = false;
  String? _ocrProvider;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _process(widget.initial));
  }

  Future<void> _process(PickedReport report) async {
    setState(() {
      _busy = true;
      _error = null;
      _fileName = report.name;
    });
    final isImage = report.isImage;
    final loader = widget.loader ??
        (Uint8List bytes, {void Function(ImportProgress progress)? onProgress}) {
          final engine = widget.ocrEngineFactory?.call() ?? createPlatformOcrEngine();
          // A gallery image has no PDF text layer: it goes through the same
          // pipeline as a scanned page, so rows stay OCR-derived and review-only.
          return report.isImage
              ? extractImageRows(bytes, ocrEngine: engine, onProgress: onProgress)
              : extractDocumentRows(bytes, ocrEngine: engine, onProgress: onProgress);
        };
    try {
      final extraction = await loader(
        report.bytes,
        onProgress: (progress) {
          if (mounted) setState(() => _progress = progress);
        },
      );
      if (kDebugMode && extraction.debugLines.isNotEmpty) {
        await _writeDebugDump(extraction);
      }
      if (!mounted) return;
      setState(() {
        _busy = false;
        _progress = null;
        _quality = extraction.quality;
        _rows = extraction.rows;
        _warnings = extraction.warnings;
        _usedOcr = extraction.usedOcr;
        _ocrProvider = extraction.ocrProvider.isEmpty ? null : extraction.ocrProvider;
        if (_rows.isEmpty) {
          _error = isImage
              ? 'This image could not be read. Try a sharper, well-lit photo of the '
                  'whole page, or import a PDF instead.'
              : extraction.text.isEmpty
                  ? 'This PDF has no readable text, even with on-device OCR. It may be '
                      'blank, corrupt, or a scan too low in resolution to recognise.'
                  : 'No laboratory rows were found in this PDF. The layout may not be '
                      'supported yet.';
        }
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error = 'Could not read this report: $error';
      });
    }
  }

  /// Lets a device layout be inspected without a debugger:
  /// adb shell "run-as app.mediread.mediread_app cat app_flutter/import/lines_dump.txt"
  Future<void> _writeDebugDump(ReportExtraction extraction) async {
    try {
      final dir = await getApplicationDocumentsDirectory();
      final rows = extraction.rows
          .map((row) => '${row.name} | ${row.valueText} | ${row.unitText ?? '-'} | '
              '${row.referenceText ?? '-'} | strat=${row.stratified} | page=${row.evidence?.page ?? '?'}')
          .join('\n');
      final pages = extraction.pageOutcomes
          .map((page) => '${page.number}|${page.kind.name}|${page.embeddedChars}|'
              '${page.ocrWords}|${page.addedWords}|${page.droppedWords}|'
              '${page.renderMs}|${page.ocrMs}|${page.warning ?? ''}')
          .join('\n');
      await File('${dir.path}/import/lines_dump.txt').writeAsString(
        '${extraction.debugLines}\n'
        '===== pages\n$pages\n'
        '===== rows (${extraction.rows.length})\n$rows\n'
        '===== ocr_tokens\n${extraction.debugOcrTokens}',
      );
    } catch (_) {
      // Diagnostics only; never block an import on it.
    }
  }

  /// Offers all three ways in again, so an unreadable photo is not a dead end.
  Future<void> _chooseAnother() async {
    final source = await showModalBottomSheet<ReportSource>(
      context: context,
      backgroundColor: Clinical.surface,
      builder: (sheetContext) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Padding(
              padding: EdgeInsets.fromLTRB(20, 18, 20, 8),
              child: Align(
                alignment: Alignment.centerLeft,
                child: Text('Choose another report',
                    style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
              ),
            ),
            ListTile(
              leading: const Icon(Icons.picture_as_pdf_outlined),
              title: const Text('Import a PDF'),
              onTap: () => Navigator.pop(sheetContext, pickPdfReport),
            ),
            ListTile(
              leading: const Icon(Icons.photo_library_outlined),
              title: const Text('Choose a photo from the gallery'),
              onTap: () => Navigator.pop(sheetContext, pickGalleryImage),
            ),
            ListTile(
              leading: const Icon(Icons.photo_camera_outlined),
              title: const Text('Take a photo'),
              onTap: () => Navigator.pop(sheetContext, pickCameraPhoto),
            ),
            const SizedBox(height: 8),
          ],
        ),
      ),
    );
    if (source == null || !mounted) return;
    try {
      final report = await source();
      if (report == null || !mounted) return;
      await _process(report);
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = 'Import failed: $error');
    }
  }

  Future<void> _export() async {
    if (_rows.isEmpty) return;
    setState(() => _busy = true);
    try {
      final bytes = await buildReportPdf(
        sourceName: _fileName ?? 'report.pdf',
        rows: _rows,
      );
      final dir = await getTemporaryDirectory();
      final file = File('${dir.path}/mediread_report.pdf');
      await file.writeAsBytes(bytes);
      await SharePlus.instance.share(ShareParams(
        files: [XFile(file.path)],
        subject: 'MediRead report',
        text: 'Generated by MediRead from ${_fileName ?? 'your report'}.',
      ));
    } catch (error) {
      setState(() => _error = 'Could not export the report: $error');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  List<MapEntry<String?, List<ParsedLabRow>>> _grouped() {
    final groups = <MapEntry<String?, List<ParsedLabRow>>>[];
    for (final row in _rows) {
      if (groups.isNotEmpty && groups.last.key == row.panel) {
        groups.last.value.add(row);
      } else {
        groups.add(MapEntry(row.panel, <ParsedLabRow>[row]));
      }
    }
    return groups;
  }

  @override
  Widget build(BuildContext context) {
    final views = _rows
        .map((row) => ResultPresentation.fromExplanation(
              buildExplanation(row),
              evidence: row.evidence,
            ))
        .toList(growable: false);
    final verified =
        views.where((view) => view.extraction == ExtractionStatus.verified).length;
    final review = views.length - verified;
    final groups = _grouped();

    return Scaffold(
      appBar: AppBar(
        title: Text(
          widget.initial.isImage ? 'Photo report' : (_fileName ?? 'Your report'),
          overflow: TextOverflow.ellipsis,
        ),
        actions: [
          IconButton(
            tooltip: 'Choose another report',
            onPressed: _busy ? null : _chooseAnother,
            icon: const Icon(Icons.file_open_outlined),
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 28),
        children: [
          if (_busy)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 24),
              child: Column(
                children: [
                  const LinearProgressIndicator(minHeight: 3),
                  const SizedBox(height: 12),
                  Text(
                    _progress?.message ?? 'Reading the report on this device…',
                    textAlign: TextAlign.center,
                    style: const TextStyle(color: Clinical.muted, fontSize: 12.5),
                  ),
                  if (_progress != null && _progress!.total > 1) ...[
                    const SizedBox(height: 4),
                    Text('Page ${_progress!.page} of ${_progress!.total}',
                        style: const TextStyle(color: Clinical.muted, fontSize: 11.5)),
                  ],
                ],
              ),
            ),
          if (_error != null)
            Container(
              padding: const EdgeInsets.all(14),
              decoration: Clinical.card(color: Clinical.alertBg),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(_error!,
                      style: const TextStyle(color: Clinical.alertFg, height: 1.4)),
                  const SizedBox(height: 10),
                  OutlinedButton.icon(
                    onPressed: _busy ? null : _chooseAnother,
                    icon: const Icon(Icons.upload_file, size: 17),
                    label: const Text('Choose another file'),
                  ),
                ],
              ),
            ),
          if (!_busy && _warnings.isNotEmpty)
            Container(
              margin: const EdgeInsets.only(bottom: 12),
              padding: const EdgeInsets.all(14),
              decoration: Clinical.card(color: Clinical.well),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      const Icon(Icons.info_outline, size: 16, color: Clinical.muted),
                      const SizedBox(width: 6),
                      Text('Some pages could not be read',
                          style: TextStyle(
                              color: Clinical.inkSecondary,
                              fontSize: 12.5,
                              fontWeight: FontWeight.w600)),
                    ],
                  ),
                  const SizedBox(height: 6),
                  for (final warning in _warnings)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 4),
                      child: Text(warning,
                          style: const TextStyle(
                              color: Clinical.muted, fontSize: 11.5, height: 1.4)),
                    ),
                ],
              ),
            ),
          if (!_busy && _rows.isNotEmpty) ...[
            _Summary(
              isImage: widget.initial.isImage,
              total: _rows.length,
              verified: verified,
              review: review,
              quality: _quality,
              usedOcr: _usedOcr,
              ocrProvider: _ocrProvider,
              onExport: _export,
            ),
            const SizedBox(height: 16),
            for (final group in groups) ...[
              Padding(
                padding: const EdgeInsets.only(bottom: 8, top: 4),
                child: Row(
                  children: [
                    Expanded(
                      child: Text(group.key ?? 'Results',
                          style: const TextStyle(
                              fontSize: 16, fontWeight: FontWeight.w600)),
                    ),
                    Text('${group.value.length} results',
                        style: const TextStyle(color: Clinical.muted, fontSize: 12)),
                  ],
                ),
              ),
              for (final row in group.value)
                ResultCard(
                  result: buildExplanation(row, resultId: row.name),
                  evidence: row.evidence,
                  orchestrator: widget.orchestrator,
                  modelReady: widget.modelReady,
                  onSetupModel: widget.onSetupModel,
                ),
            ],
          ],
          if (!_busy && _rows.isEmpty && _error == null)
            const Text(
              'No results to show yet.',
              style: TextStyle(color: Clinical.muted, fontSize: 13),
            ),
        ],
      ),
    );
  }
}

class _Summary extends StatelessWidget {
  const _Summary({
    required this.isImage,
    required this.total,
    required this.verified,
    required this.review,
    required this.quality,
    required this.usedOcr,
    required this.ocrProvider,
    required this.onExport,
  });

  final bool isImage;
  final int total;
  final int verified;
  final int review;
  final double? quality;
  final bool usedOcr;
  final String? ocrProvider;
  final VoidCallback onExport;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('$total results · $verified verified · $review to review',
            style: const TextStyle(color: Clinical.muted, fontSize: 12)),
        const SizedBox(height: 10),
        OutlinedButton.icon(
          onPressed: onExport,
          icon: const Icon(Icons.download_outlined, size: 18),
          label: const Text('Download report PDF'),
        ),
        if (usedOcr)
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Text(
              isImage
                  ? 'This photo was read with OCR'
                      '${ocrProvider == null ? '' : ' ($ocrProvider)'} — those values need review.'
                  : 'Scanned pages were read with OCR'
                      '${ocrProvider == null ? '' : ' ($ocrProvider)'} — those values need review.',
              style: const TextStyle(color: Clinical.muted, fontSize: 12, height: 1.4),
            ),
          ),
        if (quality != null)
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Text('Extraction quality ${(quality! * 100).toStringAsFixed(0)}%',
                style: const TextStyle(color: Clinical.muted, fontSize: 12)),
          ),
      ],
    );
  }
}
