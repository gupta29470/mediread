import 'dart:typed_data';

import 'package:pdf/pdf.dart';
import 'package:pdf/widgets.dart' as pw;

import '../ingest/lab_pipeline.dart';
import '../presentation/result_presentation.dart';

/// Builds the patient-facing report PDF from the same presentation model the
/// cards use, so an export cannot drift from what the user saw.
Future<Uint8List> buildReportPdf({
  required String sourceName,
  required List<ParsedLabRow> rows,
  String? reportDate,
}) async {
  final document = pw.Document();
  final groups = <(String?, List<ParsedLabRow>)>[];
  for (final row in rows) {
    if (groups.isNotEmpty && groups.last.$1 == row.panel) {
      groups.last.$2.add(row);
    } else {
      groups.add((row.panel, <ParsedLabRow>[row]));
    }
  }

  document.addPage(
    pw.MultiPage(
      pageFormat: PdfPageFormat.a4,
      margin: const pw.EdgeInsets.all(36),
      build: (context) => [
        pw.Text('MediRead report',
            style: const pw.TextStyle(fontSize: 22, fontWeight: pw.FontWeight.bold)),
        pw.SizedBox(height: 4),
        pw.Text('Source: $sourceName',
            style: const pw.TextStyle(fontSize: 9, color: PdfColors.grey700)),
        if (reportDate != null)
          pw.Text('Report date: $reportDate',
              style: const pw.TextStyle(fontSize: 9, color: PdfColors.grey700)),
        pw.Text('Educational information only. Not a diagnosis and not medical advice.',
            style: const pw.TextStyle(fontSize: 9, color: PdfColors.grey700)),
        pw.SizedBox(height: 14),
        for (final group in groups) ...[
          if (group.$1 != null) ...[
            pw.Text(group.$1!,
                style: const pw.TextStyle(fontSize: 13, fontWeight: pw.FontWeight.bold)),
            pw.SizedBox(height: 4),
          ],
          for (final row in group.$2) _keepTogether(_row(row)),
        ],
      ],
    ),
  );
  return document.save();
}

/// Keep one result card on a single page. Every widget in the pdf package can be
/// split by `MultiPage`; a card split in two leaves an empty bordered box at the
/// bottom of one page and its content on the next. A one-cell table is laid out
/// row by row, so the card moves whole to the next page instead.
pw.Widget _keepTogether(pw.Widget card) =>
    pw.Table(children: [pw.TableRow(children: [card])]);

pw.Widget _row(ParsedLabRow row) {
  final view = ResultPresentation.fromExplanation(buildExplanation(row));
  return pw.Container(
    margin: const pw.EdgeInsets.only(bottom: 14),
    padding: const pw.EdgeInsets.all(10),
    decoration: pw.BoxDecoration(
      border: pw.Border.all(color: PdfColors.grey300),
      borderRadius: pw.BorderRadius.circular(6),
    ),
    child: pw.Column(
      crossAxisAlignment: pw.CrossAxisAlignment.start,
      children: [
        pw.Text(view.testName,
            style: const pw.TextStyle(fontSize: 12, fontWeight: pw.FontWeight.bold)),
        pw.SizedBox(height: 2),
        pw.Text('${view.value ?? ''} ${view.unit ?? ''}'.trim(),
            style: const pw.TextStyle(fontSize: 16, fontWeight: pw.FontWeight.bold)),
        if (view.printedRange != null) ...[
          pw.SizedBox(height: 2),
          // A cut-off table is exported verbatim and can be long. It gets its own
          // full-width line so it wraps inside the card; sharing the value's row
          // drew it past the page edge and clipped it.
          pw.Text('Printed range: ${view.printedRange}',
              style: const pw.TextStyle(fontSize: 9, color: PdfColors.grey700)),
        ],
        pw.SizedBox(height: 4),
        pw.Text(view.outerLabel,
            style: const pw.TextStyle(fontSize: 10, fontWeight: pw.FontWeight.bold)),
        pw.SizedBox(height: 4),
        pw.Text(view.cardSummary, style: const pw.TextStyle(fontSize: 9.5)),
      ],
    ),
  );
}
