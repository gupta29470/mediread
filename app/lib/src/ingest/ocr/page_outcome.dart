import 'page_classification.dart';

/// What happened to one page during document processing.
class PageOutcome {
  const PageOutcome({
    required this.number,
    required this.kind,
    required this.embeddedChars,
    required this.ocrWords,
    required this.addedWords,
    required this.droppedWords,
    required this.renderMs,
    required this.ocrMs,
    this.warning,
  });

  final int number;
  final PageKind kind;
  final int embeddedChars;
  final int ocrWords;
  final int addedWords;
  final int droppedWords;
  final int renderMs;
  final int ocrMs;
  final String? warning;

  bool get usedOcr => ocrWords > 0;

  Map<String, Object?> toJson() => {
        'page': number,
        'kind': kind.name,
        'embedded_chars': embeddedChars,
        'ocr_words': ocrWords,
        'added_words': addedWords,
        'dropped_words': droppedWords,
        'render_ms': renderMs,
        'ocr_ms': ocrMs,
        if (warning != null) 'warning': warning,
      };
}

enum ImportStage { inspecting, rendering, recognising, merging, parsing, done }

/// Progress of one import, reported to the UI so it can name the work in
/// progress instead of showing an anonymous spinner.
class ImportProgress {
  const ImportProgress({
    required this.stage,
    required this.page,
    required this.total,
    required this.message,
  });

  final ImportStage stage;
  final int page;
  final int total;
  final String message;
}
