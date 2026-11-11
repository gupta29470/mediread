import 'dart:io';
import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/services.dart' show rootBundle;
import 'package:image_picker/image_picker.dart';
import 'package:path_provider/path_provider.dart';

enum ReportFormat { pdf, image }

/// A report the user chose, already read into memory. A gallery image is a
/// one-page report with no text layer; it is handled by the OCR pipeline.
class PickedReport {
  const PickedReport({
    required this.bytes,
    required this.name,
    this.format = ReportFormat.pdf,
  });

  final Uint8List bytes;
  final String name;
  final ReportFormat format;

  bool get isImage => format == ReportFormat.image;
}

/// Opens a source and returns the report, or null when the user cancels.
typedef ReportSource = Future<PickedReport?> Function();

/// The system file picker, restricted to PDFs.
Future<PickedReport?> pickPdfReport() async {
  final picked = await FilePicker.pickFiles(
    type: FileType.custom,
    allowedExtensions: const ['pdf'],
  );
  if (picked.isEmpty) return null;
  final file = picked.first;
  final path = file.path;
  if (path == null) return null;
  return PickedReport(bytes: await File(path).readAsBytes(), name: file.name);
}

/// The system gallery picker. The chosen image goes straight into the OCR
/// pipeline; there is no separate "image report" screen.
Future<PickedReport?> pickGalleryImage() => _pickImage(ImageSource.gallery);

/// The system camera. The captured photo goes through the same OCR pipeline as
/// a gallery image.
Future<PickedReport?> pickCameraPhoto() => _pickImage(ImageSource.camera);

Future<PickedReport?> _pickImage(ImageSource source) async {
  final picked = await ImagePicker().pickImage(source: source);
  if (picked == null) return null;
  return PickedReport(
    bytes: await picked.readAsBytes(),
    name: picked.name,
    format: ReportFormat.image,
  );
}

/// Debug-only: the report pushed to `app_flutter/import/report.pdf`.
Future<PickedReport?> loadDebugReport() async {
  final dir = await getApplicationDocumentsDirectory();
  final file = File('${dir.path}/import/report.pdf');
  if (!await file.exists()) return null;
  return PickedReport(bytes: await file.readAsBytes(), name: 'debug_report.pdf');
}

/// Debug-only: the sample PDF bundled with the app.
Future<PickedReport?> loadSampleReport() async {
  final data = await rootBundle.load('assets/samples/lab_report.pdf');
  return PickedReport(bytes: data.buffer.asUint8List(), name: 'lab_report.pdf');
}

/// Evaluation-only: a synthetic scanned report (three pages, image-only).
Future<PickedReport?> loadScannedReport() async {
  final data = await rootBundle.load('assets/eval/scanned_report.pdf');
  return PickedReport(bytes: data.buffer.asUint8List(), name: 'scanned_report.pdf');
}

/// Evaluation-only: a synthetic hybrid report (embedded header + scanned table).
Future<PickedReport?> loadHybridReport() async {
  final data = await rootBundle.load('assets/eval/hybrid_report.pdf');
  return PickedReport(bytes: data.buffer.asUint8List(), name: 'hybrid_report.pdf');
}
