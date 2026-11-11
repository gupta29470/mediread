import 'dart:convert';
import 'dart:io' show ZLibEncoder;
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:mediread_app/src/ingest/pdf_text.dart';

Uint8List _pdf(String content, {bool flate = false}) {
  final body = flate
      ? latin1.decode(ZLibEncoder().convert(latin1.encode(content)))
      : content;
  final filter = flate ? '/Filter /FlateDecode ' : '';
  final text = '%PDF-1.4\n1 0 obj\n<< /Length ${body.length} $filter>>\nstream\n$body\nendstream\nendobj\n%%EOF';
  return Uint8List.fromList(latin1.encode(text));
}

void main() {
  test('extracts text from an uncompressed content stream', () {
    final result = extractPdfText(_pdf('BT /F1 12 Tf 72 720 Td (HEMOGLOBIN 9.0 g/dL 12.0 - 15.0) Tj ET'));
    expect(result.streams, 1);
    expect(result.text, contains('HEMOGLOBIN 9.0 g/dL 12.0 - 15.0'));
  });

  test('extracts text from a FlateDecode stream', () {
    final result = extractPdfText(_pdf('BT 72 720 Td (GLUCOSE 92.9 mg/dL) Tj ET', flate: true));
    expect(result.decoded, 1);
    expect(result.text, contains('GLUCOSE 92.9 mg/dL'));
  });

  test('keeps multiple text lines separate', () {
    final result = extractPdfText(_pdf('BT 72 720 Td (HEMOGLOBIN 9.0 g/dL) Tj T* (12.0 - 15.0) Tj ET'));
    expect(result.text, contains('HEMOGLOBIN 9.0 g/dL'));
    expect(result.text, contains('12.0 - 15.0'));
  });

  test('reports unusable text for a non-text stream', () {
    final result = extractPdfText(_pdf('BT ET'));
    expect(result.usable, isFalse);
  });
}
