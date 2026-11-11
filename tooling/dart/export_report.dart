// Regenerate the patient-facing export PDF on the host from a layout fixture.
//
// The app writes `mediread_report.pdf` from the same presentation model the cards
// use; this script exercises that path with the real report geometry so an export
// bug can be found without a device.
//
//   cd tooling/dart
//   dart run export_report.dart ../../.cache/layout/report16.glyphs.json /tmp/out.pdf
import 'dart:convert';
import 'dart:io';

import '../../app/lib/src/export/report_pdf.dart';
import '../../app/lib/src/ingest/table_parser.dart';

void main(List<String> args) async {
  if (args.length < 2) {
    stderr.writeln('usage: export_report.dart <fixture.json> <out.pdf> [sourceName]');
    exit(2);
  }
  final fixture = jsonDecode(File(args[0]).readAsStringSync()) as Map<String, dynamic>;
  final pages = [
    for (final page in fixture['pages'] as List<dynamic>)
      [
        for (final entry in page as List<dynamic>)
          Glyph(
            (entry as List<dynamic>)[0] as String,
            (entry[1] as num).toDouble(),
            (entry[2] as num).toDouble(),
            (entry[3] as num).toDouble(),
            (entry[4] as num).toDouble(),
          ),
      ],
  ];
  final rows = const TableParser().parsePages(pages);
  final bytes = await buildReportPdf(
    sourceName: args.length > 2 ? args[2] : (fixture['fileName'] as String? ?? 'report.pdf'),
    rows: rows,
  );
  File(args[1]).writeAsBytesSync(bytes);
  stdout.writeln('${rows.length} rows → ${args[1]} (${bytes.length} bytes)');
}
