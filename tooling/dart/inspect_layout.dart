// Host-side inspector for the geometry parser.
//
// pdfium (and therefore pdfrx `page.loadText()`) cannot load inside
// `flutter test` on the host, so the real report layout is exported once by
// `tooling/export_layout_fixture.py` and replayed here. This tool prints what
// `TableParser` actually extracts, which is the only honest way to review a
// binding change without a device.
//
//   cd app
//   /path/to/flutter/bin/cache/dart-sdk/bin/dart run tool/inspect_layout.dart \
//       ../.cache/layout/report16.glyphs.json [--verbose]
import 'dart:convert';
import 'dart:io';

import '../../app/lib/src/ingest/lab_pipeline.dart';
import '../../app/lib/src/ingest/table_parser.dart';

List<List<Glyph>> glyphPages(Map<String, dynamic> fixture) {
  final pages = fixture['pages'] as List<dynamic>;
  return [
    for (final page in pages)
      [
        for (final entry in (page as List<dynamic>))
          Glyph(
            (entry as List<dynamic>)[0] as String,
            ((entry[1] as num)).toDouble(),
            ((entry[2] as num)).toDouble(),
            ((entry[3] as num)).toDouble(),
            ((entry[4] as num)).toDouble(),
          ),
      ],
  ];
}

void main(List<String> args) {
  if (args.isEmpty) {
    stderr.writeln('usage: inspect_layout.dart <fixture.json> [--verbose]');
    exit(2);
  }
  final verbose = args.contains('--verbose');
  final file = File(args.first);
  if (!file.existsSync()) {
    stderr.writeln('missing fixture: ${file.path}');
    exit(2);
  }
  final fixture = jsonDecode(file.readAsStringSync()) as Map<String, dynamic>;
  final pages = glyphPages(fixture);
  final rows = const TableParser().parsePages(pages);

  var withReference = 0;
  var comparable = 0;
  String? panel;
  for (final row in rows) {
    if (row.panel != panel) {
      panel = row.panel;
      stdout.writeln('\n## ${row.panel ?? "(no panel)"}');
    }
    final gates = gatesFor(row, lookupKnownTest(row.name));
    final hasReference = row.referenceText != null;
    if (hasReference) withReference++;
    if (gates['range_comparison'] == true) comparable++;
    stdout.writeln(
      '  ${hasReference ? "REF" : "   "} '
      '${row.name.padRight(34).substring(0, 34)} '
      '${row.valueText.padRight(8)} ${(row.unitText ?? "-").padRight(9)} '
      'ref=${(row.referenceText ?? "-").padRight(22)} '
      'low=${row.low?.toString() ?? "-"} high=${row.high?.toString() ?? "-"} '
      'op=${row.operator ?? "-"} strat=${row.stratified} '
      'known=${gates["identify_test"]} cmp=${gates["range_comparison"]}',
    );
    if (verbose) {
      stdout.writeln('        valueKind=${row.valueKind} '
          'valueVerified=${row.valueVerified} '
          'unitVerified=${row.unitVerified} '
          'referenceVerified=${row.referenceVerified}');
    }
  }
  stdout.writeln('\n${rows.length} rows, $withReference with a reference, '
      '$comparable comparable');
}
