/// Read-only model of the deterministic engine's output
/// (`mediread.explanation/1`). The app never recomputes medical meaning; it
/// renders what the engine permitted and uses the gates to decide what the
/// optional model may see.
class ExplanationSection {
  const ExplanationSection({
    required this.key,
    required this.permitted,
    this.text,
    this.reason,
    this.sources = const [],
  });

  final String key;
  final bool permitted;
  final String? text;
  final String? reason;
  final List<String> sources;

  bool get hasText => permitted && (text?.trim().isNotEmpty ?? false);

  factory ExplanationSection.fromJson(Map<String, dynamic> json) {
    return ExplanationSection(
      key: json['key'] as String? ?? '',
      permitted: json['permitted'] as bool? ?? false,
      text: json['text'] as String?,
      reason: json['reason'] as String?,
      sources: (json['sources'] as List<dynamic>? ?? const [])
          .map((source) => source.toString())
          .toList(growable: false),
    );
  }
}

class ResultFacts {
  const ResultFacts({
    this.valueText,
    this.unitText,
    this.referenceText,
    this.valueKind = 'numeric',
    this.comparisonState,
  });

  final String? valueText;
  final String? unitText;
  final String? referenceText;
  final String valueKind;
  final String? comparisonState;

  factory ResultFacts.fromJson(Map<String, dynamic>? json) {
    if (json == null) return const ResultFacts();
    return ResultFacts(
      valueText: json['value_text'] as String?,
      unitText: json['unit_text'] as String?,
      referenceText: json['reference_text'] as String?,
      valueKind: json['value_kind'] as String? ?? 'numeric',
      comparisonState: json['comparison_state'] as String?,
    );
  }
}

class ResultExplanation {
  ResultExplanation({
    required this.resultId,
    required this.testName,
    required this.status,
    required this.knowledgeStatus,
    required this.gates,
    required this.permitted,
    required this.sections,
    this.knowledgeCoverage = 'unknown',
    this.canonicalName,
    this.panel,
    this.comparison,
    this.facts = const ResultFacts(),
  });

  final String resultId;
  final String testName;
  final String status;

  /// Review status of the knowledge entry behind this result: `approved`,
  /// `reviewed`, `draft`, `blocked` or `unsupported`.
  ///
  /// Only an exact `approved` opens the model gate. Coverage (below) is a
  /// separate concept and never substitutes for review.
  final String knowledgeStatus;

  /// How much of the test the knowledge base covers: `complete`, `partial` or
  /// `unsupported`. Display only; it does not grant model access.
  final String knowledgeCoverage;
  final Map<String, bool> gates;
  final Map<String, bool> permitted;
  final List<ExplanationSection> sections;
  final String? canonicalName;
  final String? panel;
  final Map<String, dynamic>? comparison;
  final ResultFacts facts;

  factory ResultExplanation.fromJson(Map<String, dynamic> json) {
    final gates = <String, bool>{};
    (json['gates'] as Map<String, dynamic>? ?? const {}).forEach((key, value) {
      gates[key] = value == true;
    });
    final permitted = <String, bool>{};
    (json['permitted'] as Map<String, dynamic>? ?? const {}).forEach((key, value) {
      permitted[key] = value == true;
    });
    return ResultExplanation(
      resultId: json['result_id'] as String? ?? '',
      testName: json['test_name'] as String? ?? '',
      canonicalName: json['canonical_name'] as String?,
      panel: json['panel'] as String?,
      status: json['status'] as String? ?? 'withheld',
      knowledgeStatus: (json['knowledge_review_status'] as String?) ??
          (json['knowledge_status'] as String?) ??
          'unsupported',
      knowledgeCoverage: (json['knowledge_coverage'] as String?) ??
          (json['knowledge_status'] as String?) ??
          'unsupported',
      gates: gates,
      permitted: permitted,
      comparison: json['comparison'] as Map<String, dynamic>?,
      facts: ResultFacts.fromJson(json['facts'] as Map<String, dynamic>?),
      sections: (json['sections'] as List<dynamic>? ?? const [])
          .map((section) => ExplanationSection.fromJson(section as Map<String, dynamic>))
          .toList(growable: false),
    );
  }

  ExplanationSection? section(String key) {
    for (final section in sections) {
      if (section.key == key) return section;
    }
    return null;
  }

  // -- gate helpers ---------------------------------------------------------
  bool get canIdentify => gates['identify_test'] == true;
  bool get canInterpret => gates['interpret_value'] == true;
  bool get canCompareUnits => gates['unit_comparison'] == true;
  bool get canCompareRange => gates['range_comparison'] == true;
  bool get hasKnowledge => knowledgeStatus == 'approved';

  /// The model may rewrite only what the engine has already identified and
  /// interpreted, and only for a test with an approved knowledge entry.
  bool get aiRewriteAllowed => canIdentify && canInterpret && hasKnowledge;

  /// Follow-ups are only sent to the model when every gate is open. This is the
  /// deterministic answerability decision; the model's own flag is never used.
  bool get aiFollowUpAllowed =>
      canIdentify && canInterpret && canCompareUnits && canCompareRange && hasKnowledge;

  /// Sections whose text may be sent to the model. Blocked text never is.
  List<ExplanationSection> get permittedSections =>
      sections.where((section) => section.hasText).toList(growable: false);

  List<ExplanationSection> get blockedSections =>
      sections.where((section) => !section.permitted).toList(growable: false);

  List<String> get approvedSourceIds {
    final ids = <String>{};
    for (final section in sections) {
      ids.addAll(section.sources);
    }
    return ids.toList(growable: false)..sort();
  }

  /// Deterministic explanation text, used whenever the model is unavailable or
  /// its output is rejected.
  String get deterministicText {
    const order = [
      'what_this_test_measures',
      'your_reported_result',
      'comparison_with_reference',
      'what_this_may_generally_indicate',
      'important_limitations',
    ];
    final buffer = StringBuffer();
    for (final key in order) {
      final current = section(key);
      if (current != null && current.hasText) {
        buffer.writeln(current.text!.trim());
        buffer.writeln();
      }
    }
    return buffer.toString().trim();
  }

  bool get hasLimitation => section('important_limitations')?.hasText ?? false;
}

class ExplanationDocument {
  ExplanationDocument({required this.reportId, required this.results});

  final String reportId;
  final List<ResultExplanation> results;

  factory ExplanationDocument.fromJson(Map<String, dynamic> json) {
    return ExplanationDocument(
      reportId: json['report_id'] as String? ?? '',
      results: (json['results'] as List<dynamic>? ?? const [])
          .map((result) => ResultExplanation.fromJson(result as Map<String, dynamic>))
          .toList(growable: false),
    );
  }
}
