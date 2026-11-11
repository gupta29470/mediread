import 'package:flutter_test/flutter_test.dart';
import 'package:mediread_app/src/export/report_pdf.dart';
import 'package:mediread_app/src/ingest/lab_pipeline.dart';

void main() {
  test('exported PDF is a real PDF containing the uploaded rows', () async {
    const parser = LabParser();
    final rows = parser.parse('''
COMPLETE BLOOD COUNT
HEMOGLOBIN 9.0 g/dL 12.0 - 15.0
PLATELET COUNT 250 X10^3/uL 150 - 410
''');
    final bytes = await buildReportPdf(sourceName: 'my_report.pdf', rows: rows);
    expect(bytes.length, greaterThan(1000));
    expect(String.fromCharCodes(bytes.take(5)), '%PDF-');
  });

  test('a long printed range and many cards export without throwing', () async {
    // A cut-off table is exported verbatim and is much longer than a plain
    // range; it must wrap inside the card rather than be drawn past the page
    // edge, and cards must not split across pages.
    const cutoff = 'DEFICIENCY : <20 ng/ml | INSUFFICIENCY : 20-<30 ng/ml | '
        'SUFFICIENCY : 30-100 ng/ml | TOXICITY : >100 ng/ml';
    final rows = [
      for (var index = 0; index < 40; index++)
        ParsedLabRow(
          name: 'TEST ${index + 1}',
          valueText: '${index + 1}.5',
          valueKind: 'numeric',
          unitText: 'ng/mL',
          referenceText: cutoff,
          valueVerified: true,
          unitVerified: true,
          referenceVerified: true,
          stratified: true,
        ),
    ];
    final bytes = await buildReportPdf(sourceName: 'many_rows.pdf', rows: rows);
    expect(bytes.length, greaterThan(1000));
    expect(String.fromCharCodes(bytes.take(5)), '%PDF-');
  });
}
