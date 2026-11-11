import 'package:flutter/services.dart' show rootBundle;
import 'package:flutter_test/flutter_test.dart';
import 'package:mediread_app/src/ingest/lab_pipeline.dart';
import 'package:mediread_app/src/ingest/pdf_text.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('the bundled sample PDF flows through extract → parse → gated explanation', () async {
    final data = await rootBundle.load('assets/samples/lab_report.pdf');
    final extracted = extractPdfText(data.buffer.asUint8List());
    expect(extracted.usable, isTrue);

    final rows = const LabParser().parse(extracted.text);
    expect(rows, isNotEmpty);
    expect(rows.any((row) => row.name.contains('HEMOGLOBIN')), isTrue);

    final verified = rows.where((row) => row.unitVerified && row.referenceVerified).toList();
    expect(verified, isNotEmpty);
    final explanation = buildExplanation(verified.first);
    expect(explanation.gates['identify_test'], isTrue);
    expect(explanation.gates['range_comparison'], isTrue);
    expect(explanation.section('important_limitations')!.permitted, isTrue);
  });

  test('a row without a unit stays unverified end to end', () async {
    final data = await rootBundle.load('assets/samples/lab_report.pdf');
    final rows = const LabParser().parse(extractPdfText(data.buffer.asUint8List()).text);
    final glucose = rows.firstWhere((row) => row.name.contains('FASTING BLOOD SUGAR'));
    final explanation = buildExplanation(glucose);
    expect(explanation.gates['range_comparison'], isFalse);
    expect(explanation.section('your_reported_result')!.permitted, isTrue);
  });
}
