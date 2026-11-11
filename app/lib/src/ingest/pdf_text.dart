import 'dart:convert';
import 'dart:io' show ZLibDecoder;
import 'dart:typed_data';

import 'package:pdfrx/pdfrx.dart';

/// Minimal, dependency-free text extraction for digitally generated PDFs.
///
/// It walks `stream … endstream` blocks, inflates FlateDecode content, and pulls
/// the strings out of `BT … ET` text objects. It does **not** interpret font
/// CID maps, so subset/Identity-H fonts can produce garbled output; such pages
/// are reported as low quality rather than silently trusted.
class PdfTextResult {
  const PdfTextResult({required this.text, required this.streams, required this.decoded});

  final String text;
  final int streams;
  final int decoded;

  bool get usable => text.trim().length > 40;

  /// Rough quality signal: printable ASCII ratio.
  double get quality {
    if (text.isEmpty) return 0;
    final printable = text.runes.where((r) => r == 10 || (r >= 32 && r < 127)).length;
    return printable / text.length;
  }
}

PdfTextResult extractPdfText(Uint8List bytes) {
  final raw = latin1.decode(bytes, allowInvalid: true);
  var searchFrom = 0;
  var streams = 0;
  var decoded = 0;
  final buffer = StringBuffer();

  while (true) {
    final start = raw.indexOf('stream', searchFrom);
    if (start == -1) break;
    final end = raw.indexOf('endstream', start);
    if (end == -1) break;
    streams++;
    var dataStart = start + 'stream'.length;
    if (raw.startsWith('\r\n', dataStart)) {
      dataStart += 2;
    } else if (raw.startsWith('\n', dataStart) || raw.startsWith('\r', dataStart)) {
      dataStart += 1;
    }
    final header = raw.substring((start - 300).clamp(0, start), start);
    final segment = raw.substring(dataStart, end);
    Uint8List payload;
    try {
      payload = header.contains('/FlateDecode')
          ? Uint8List.fromList(ZLibDecoder().convert(latin1.encode(segment)))
          : Uint8List.fromList(latin1.encode(segment));
      decoded++;
    } catch (_) {
      searchFrom = end + 9;
      continue;
    }
    buffer.writeln(_textFromContent(latin1.decode(payload, allowInvalid: true)));
    searchFrom = end + 9;
  }

  return PdfTextResult(
    text: buffer.toString(),
    streams: streams,
    decoded: decoded,
  );
}

final RegExp _textObject = RegExp(r'BT(.*?)ET', dotAll: true);
final RegExp _lineBreak = RegExp(r'(?:Td|TD|T\*)');
final RegExp _literal = RegExp(r'\((?:[^()\\]|\\.)*\)', dotAll: true);

String _textFromContent(String content) {
  final out = StringBuffer();
  for (final block in _textObject.allMatches(content)) {
    final body = block.group(1) ?? '';
    for (final line in body.split(_lineBreak)) {
      final parts = <String>[];
      for (final match in _literal.allMatches(line)) {
        parts.add(_unescape(match.group(0)!.substring(1, match.group(0)!.length - 1)));
      }
      final text = parts.join(' ').trim();
      if (text.isNotEmpty) out.writeln(text);
    }
  }
  return out.toString();
}

String _unescape(String value) {
  final out = StringBuffer();
  for (var i = 0; i < value.length; i++) {
    final char = value[i];
    if (char != '\\' || i + 1 >= value.length) {
      out.write(char);
      continue;
    }
    i++;
    final next = value[i];
    switch (next) {
      case 'n':
        out.write('\n');
      case 'r':
        out.write('\r');
      case 't':
        out.write('\t');
      case '(':
      case ')':
      case '\\':
        out.write(next);
      default:
        if (RegExp(r'[0-7]').hasMatch(next)) {
          var octal = next;
          while (octal.length < 3 && i + 1 < value.length && RegExp(r'[0-7]').hasMatch(value[i + 1])) {
            i++;
            octal += value[i];
          }
          out.writeCharCode(int.parse(octal, radix: 8));
        } else {
          out.write(next);
        }
    }
  }
  return out.toString();
}

/// Extraction through pdfium (via pdfrx), which honours the font `ToUnicode`
/// maps that the byte-level parser above cannot. This is the path real reports
/// need: subset fonts store glyph ids, not ASCII.
Future<PdfTextResult> extractPdfTextAsync(Uint8List bytes) async {
  PdfDocument? document;
  try {
    document = await PdfDocument.openData(bytes);
    final buffer = StringBuffer();
    var decoded = 0;
    for (final page in document.pages) {
      final text = await page.loadText();
      final full = text?.fullText.trim() ?? '';
      if (full.isNotEmpty) {
        buffer.writeln(full);
        decoded++;
      }
    }
    return PdfTextResult(
      text: buffer.toString(),
      streams: document.pages.length,
      decoded: decoded,
    );
  } catch (_) {
    // Fall back to the byte parser for simple, non-embedded PDFs.
    return extractPdfText(bytes);
  } finally {
    document?.dispose();
  }
}
