// Dump the visual lines and words the Dart parser builds for one page of a
// layout fixture. Used to debug word/column reconstruction on real reports.
//
//   cd tooling/dart
//   dart run dump_lines.dart ../../.cache/layout/report16.glyphs.json 7
import 'dart:convert';
import 'dart:io';

import '../../app/lib/src/ingest/table_parser.dart';

void main(List<String> args) {
  final fixture = jsonDecode(File(args[0]).readAsStringSync()) as Map<String, dynamic>;
  final pageNumber = int.parse(args[1]);
  final page = (fixture['pages'] as List<dynamic>)[pageNumber - 1] as List<dynamic>;
  final glyphs = <Glyph>[
    for (final entry in page)
      Glyph(
        (entry as List<dynamic>)[0] as String,
        (entry[1] as num).toDouble(),
        (entry[2] as num).toDouble(),
        (entry[3] as num).toDouble(),
        (entry[4] as num).toDouble(),
      ),
  ];
  final lines = buildLines(buildWords(glyphs));
  for (final line in lines) {
    final words = line.words.map((w) => '${w.text}[${w.left.toStringAsFixed(0)}-${w.right.toStringAsFixed(0)}]');
    stdout.writeln('y=${line.top.toStringAsFixed(1)} | ${words.join('  ')}');
  }
}
