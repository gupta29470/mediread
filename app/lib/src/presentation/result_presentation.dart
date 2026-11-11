import '../explanation/explanation_document.dart';
import '../ingest/lab_pipeline.dart';

enum ExtractionStatus { verified, review }

enum ExplanationStatus { explained, partiallyExplained, withheld }

enum KnowledgeStatus { complete, partial, unsupported }

enum OuterStatus {
  withinRange,
  belowRange,
  aboveRange,
  meetsBound,
  outsideBound,
  reviewRequired,
  rangeNotProvided,
  cannotCompare,
  resultAvailable,
}

enum ComparisonState {
  withinRange,
  belowRange,
  aboveRange,
  satisfiesBound,
  violatesBound,
  qualitativeMatch,
  qualitativeDifference,
  unavailable,
}

/// Presentation-only projection of a result. Permissions are normalised here and
/// never inferred from status; impossible combinations fail closed (the UI shows
/// the printed fact and a limitation, never a comparison).
class ResultPresentation {
  const ResultPresentation({
    required this.testName,
    required this.value,
    required this.unit,
    required this.printedRange,
    required this.extraction,
    required this.explanation,
    required this.knowledge,
    required this.comparison,
    required this.identify,
    required this.interpret,
    required this.unitAllowed,
    required this.rangeAllowed,
    required this.limitations,
    this.measures,
    this.panel,
    this.valueConfirmed = true,
    this.unitConfirmed = true,
    this.evidence,
  });

  final String testName;
  final String? value;
  final String? unit;
  final String? printedRange;
  final ExtractionStatus extraction;
  final ExplanationStatus explanation;
  final KnowledgeStatus knowledge;
  final ComparisonState comparison;
  final bool identify;
  final bool interpret;
  final bool unitAllowed;
  final bool rangeAllowed;
  final List<String> limitations;
  final String? measures;
  final String? panel;
  final bool valueConfirmed;
  final bool unitConfirmed;

  /// Where the row came from in the source report, when the row was extracted
  /// in this process. Demo/serialised explanations do not carry it.
  final ExtractionEvidence? evidence;

  /// The comparison/status sentence on its own. `cardSummary` prefixes the first
  /// sentence of the test description, which the card shows in its expanded
  /// section instead.
  String get statusSentence => switch (outerStatus) {
        OuterStatus.withinRange => 'Your reported value is within the range printed on this report.',
        OuterStatus.belowRange => 'Your reported value is below the range printed on this report.',
        OuterStatus.aboveRange => 'Your reported value is above the range printed on this report.',
        OuterStatus.meetsBound => 'Your reported value meets the bound printed on this report.',
        OuterStatus.outsideBound => 'Your reported value is outside the bound printed on this report.',
        OuterStatus.reviewRequired => 'Some extracted details need confirmation before comparing.',
        OuterStatus.rangeNotProvided => 'No reference range was printed for this result.',
        OuterStatus.cannotCompare => 'No comparison is shown for this result.',
        OuterStatus.resultAvailable => 'MediRead has no explanation for this test yet.',
      };

  /// Review notes for the expanded card. Extraction warnings are never hidden,
  /// and a withheld comparison always says why.
  List<String> get reviewNotes {
    final notes = <String>[...?evidence?.notes];
    if (!rangeAllowed && printedRange != null) notes.add(cannotCompareReason);
    if (!unitAllowed && printedRange != null) {
      notes.add('A reliable unit was not available, so no comparison is shown.');
    }
    return notes.toSet().toList(growable: false);
  }

  bool get hasComparison => rangeAllowed && comparison != ComparisonState.unavailable;

  OuterStatus get outerStatus {
    // A missing range is its own state: it is not an extraction failure and must
    // never be inferred.
    if (printedRange == null) return OuterStatus.rangeNotProvided;
    if (!valueConfirmed) return OuterStatus.reviewRequired;
    if (!unitConfirmed) return OuterStatus.cannotCompare;
    if (knowledge == KnowledgeStatus.unsupported) return OuterStatus.resultAvailable;
    if (!rangeAllowed) return OuterStatus.cannotCompare;
    return switch (comparison) {
      ComparisonState.withinRange => OuterStatus.withinRange,
      ComparisonState.belowRange => OuterStatus.belowRange,
      ComparisonState.aboveRange => OuterStatus.aboveRange,
      ComparisonState.satisfiesBound => OuterStatus.meetsBound,
      ComparisonState.violatesBound => OuterStatus.outsideBound,
      _ => OuterStatus.cannotCompare,
    };
  }

  String get outerLabel => switch (outerStatus) {
        OuterStatus.withinRange => 'Within printed range',
        OuterStatus.belowRange => 'Below printed range',
        OuterStatus.aboveRange => 'Above printed range',
        OuterStatus.meetsBound => 'Meets printed bound',
        OuterStatus.outsideBound => 'Outside printed bound',
        OuterStatus.reviewRequired => 'Review this result',
        OuterStatus.rangeNotProvided => 'Range not provided',
        OuterStatus.cannotCompare => 'Cannot compare',
        OuterStatus.resultAvailable => 'Result available',
      };

  String get cannotCompareReason {
    if (printedRange == null) return 'This report does not include a reference range for this result.';
    if (!unitAllowed) return 'A reliable unit was not available, so no comparison is shown.';
    if (!interpret) return 'The reported value needs confirmation, so no comparison is shown.';
    return 'The printed range depends on information that is not available here. No comparison is shown.';
  }

  /// One deterministic sentence for the outer card. The model may later restate
  /// it, but it never replaces these facts.
  String get cardSummary {
    final base = measures?.trim();
    final first = base == null || base.isEmpty
        ? null
        : base.split(RegExp(r'(?<=[.!?])\s+')).first.trim();
    final comparisonSentence = switch (outerStatus) {
      OuterStatus.withinRange => 'Your reported value is within the range printed on this report.',
      OuterStatus.belowRange => 'Your reported value is below the range printed on this report.',
      OuterStatus.aboveRange => 'Your reported value is above the range printed on this report.',
      OuterStatus.meetsBound => 'Your reported value meets the bound printed on this report.',
      OuterStatus.outsideBound => 'Your reported value is outside the bound printed on this report.',
      OuterStatus.reviewRequired => 'Some extracted details need confirmation before comparing.',
      OuterStatus.rangeNotProvided => 'No reference range was printed for this result.',
      OuterStatus.cannotCompare => 'No comparison is shown for this result.',
      OuterStatus.resultAvailable => 'MediRead has no explanation for this test yet.',
    };
    return [if (first != null) first, comparisonSentence].join(' ');
  }
  bool get canSimplify => explanation != ExplanationStatus.withheld && identify && interpret;

  String get extractionLabel => extraction == ExtractionStatus.verified ? 'Verified' : 'Review';

  String get comparisonLabel => switch (comparison) {
        ComparisonState.withinRange => 'Within printed range',
        ComparisonState.belowRange => 'Below printed range',
        ComparisonState.aboveRange => 'Above printed range',
        ComparisonState.satisfiesBound => 'Meets printed bound',
        ComparisonState.violatesBound => 'Outside printed bound',
        ComparisonState.qualitativeMatch => 'Matches printed description',
        ComparisonState.qualitativeDifference => 'Differs from printed description',
        ComparisonState.unavailable => 'No comparison available',
      };

  String get comparisonSupport => switch (comparison) {
        ComparisonState.withinRange => 'This value is within the range printed on this report.',
        ComparisonState.belowRange => 'This value is below the range printed on this report.',
        ComparisonState.aboveRange => 'This value is above the range printed on this report.',
        ComparisonState.satisfiesBound => 'This value meets the bound printed on this report.',
        ComparisonState.violatesBound => 'This value is outside the bound printed on this report.',
        ComparisonState.qualitativeMatch =>
          'The reported result matches the comparison text printed on this report.',
        ComparisonState.qualitativeDifference =>
          'The reported result differs from the comparison text printed on this report.',
        ComparisonState.unavailable => 'No comparison is shown for this result.',
      };

  String get explanationLabel => switch (explanation) {
        ExplanationStatus.explained => 'Explained',
        ExplanationStatus.partiallyExplained => 'Limited explanation',
        ExplanationStatus.withheld => 'Limited information',
      };

  String get limitationNote {
    if (limitations.isNotEmpty) return limitations.first;
    return switch (explanation) {
      ExplanationStatus.explained => '',
      ExplanationStatus.partiallyExplained =>
        'Some educational information is available; other details are not covered.',
      ExplanationStatus.withheld =>
        'The report text is shown, but MediRead cannot reliably explain this result.',
    };
  }

  static ResultPresentation fromExplanation(ResultExplanation result, {ExtractionEvidence? evidence}) {
    var identify = result.gates['identify_test'] == true;
    var interpret = result.gates['interpret_value'] == true;
    var unit = result.gates['unit_comparison'] == true;
    var range = result.gates['range_comparison'] == true;

    // Fail closed: dependent permissions cannot outlive their prerequisites.
    if (!identify) {
      interpret = false;
      unit = false;
      range = false;
    }
    if (!interpret) {
      unit = false;
      range = false;
    }
    if (range && !unit) range = false;

    final state = result.comparison?['state']?.toString();
    final comparison = !range
        ? ComparisonState.unavailable
        : switch (state) {
            'within_range' => ComparisonState.withinRange,
            'below_range' => ComparisonState.belowRange,
            'above_range' => ComparisonState.aboveRange,
            'satisfies_one_sided_reference' => ComparisonState.satisfiesBound,
            'violates_one_sided_reference' => ComparisonState.violatesBound,
            'matches_qualitative_reference' => ComparisonState.qualitativeMatch,
            'differs_from_qualitative_reference' => ComparisonState.qualitativeDifference,
            _ => ComparisonState.unavailable,
          };

    // Extraction status is about the fields that were read, not about whether the
    // knowledge catalogue recognises the test: an unknown test with a verified
    // value, unit and reference is still a verified extraction. Explanation
    // permissions stay fail-closed below.
    final fieldsRead = result.gates['interpret_value'] == true &&
        result.gates['unit_comparison'] == true &&
        result.facts.referenceText != null;

    final measuresText = result.section('what_this_test_measures')?.text;
    final limitations = <String>[];
    if (!unit) limitations.add('A reliable unit was not available for comparison.');
    if (!range) limitations.add('No reference comparison is shown for this result.');

    return ResultPresentation(
      testName: result.testName,
      value: result.facts.valueText,
      unit: result.facts.unitText,
      printedRange: result.facts.referenceText,
      extraction: fieldsRead ? ExtractionStatus.verified : ExtractionStatus.review,
      explanation: switch (result.status) {
        'explained' => ExplanationStatus.explained,
        'partially_explained' => ExplanationStatus.partiallyExplained,
        _ => ExplanationStatus.withheld,
      },
      knowledge: switch (result.knowledgeCoverage) {
        'complete' => KnowledgeStatus.complete,
        'partial' => KnowledgeStatus.partial,
        _ => KnowledgeStatus.unsupported,
      },
      comparison: comparison,
      identify: identify,
      interpret: interpret,
      unitAllowed: unit,
      rangeAllowed: range,
      limitations: limitations,
      measures: measuresText,
      panel: result.panel,
      valueConfirmed: result.gates['interpret_value'] == true,
      unitConfirmed: result.gates['unit_comparison'] == true,
      evidence: evidence,
    );
  }
}
