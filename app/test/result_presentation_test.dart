import 'package:flutter_test/flutter_test.dart';
import 'package:mediread_app/src/explanation/explanation_document.dart';
import 'package:mediread_app/src/presentation/result_presentation.dart';

ResultExplanation _result({
  bool identify = true,
  bool interpret = true,
  bool unit = true,
  bool range = true,
  String? value = '9.0',
  String? unitText = 'g/dL',
  String? reference = '12.0-15.0',
  String state = 'below_range',
  String status = 'explained',
  String knowledge = 'approved',
  String? coverage,
}) {
  return ResultExplanation(
    resultId: 'r', testName: 'HEMOGLOBIN', status: status, knowledgeStatus: knowledge,
    knowledgeCoverage: coverage ??
        (knowledge == 'unsupported' || knowledge == 'partial' ? knowledge : 'complete'),
    gates: {
      'identify_test': identify,
      'interpret_value': interpret,
      'unit_comparison': unit,
      'range_comparison': range,
    },
    permitted: const {},
    facts: ResultFacts(valueText: value, unitText: unitText, referenceText: reference),
    comparison: range ? {'state': state} : null,
    sections: const [],
  );
}

void main() {
  test('all sixteen gate combinations normalise without inventing permission', () {
    for (var mask = 0; mask < 16; mask++) {
      final i = (mask & 8) != 0;
      final v = (mask & 4) != 0;
      final u = (mask & 2) != 0;
      final r = (mask & 1) != 0;
      final p = ResultPresentation.fromExplanation(
          _result(identify: i, interpret: v, unit: u, range: r));
      if (!i) {
        expect(p.interpret, isFalse, reason: 'I=0 V must be blocked');
        expect(p.unitAllowed, isFalse);
        expect(p.rangeAllowed, isFalse);
      }
      if (!v) {
        expect(p.unitAllowed, isFalse, reason: 'V=0 U must be blocked');
        expect(p.rangeAllowed, isFalse);
      }
      if (p.rangeAllowed) expect(p.unitAllowed, isTrue, reason: 'R requires U');
      if (!p.rangeAllowed) expect(p.comparison, ComparisonState.unavailable);
    }
  });

  test('verified requires value, unit and printed range', () {
    expect(ResultPresentation.fromExplanation(_result()).extraction, ExtractionStatus.verified);
    expect(ResultPresentation.fromExplanation(_result(reference: null, range: false)).extraction,
        ExtractionStatus.review);
    expect(ResultPresentation.fromExplanation(_result(unitText: null, unit: false)).extraction,
        ExtractionStatus.review);
  });

  test('review never carries a confirmed comparison', () {
    final p = ResultPresentation.fromExplanation(_result(identify: false));
    expect(p.hasComparison, isFalse);
    expect(p.comparisonLabel, 'No comparison available');
    // Extraction and knowledge coverage are separate: the fields were read even
    // though the catalogue has no entry, so only the comparison is withheld.
    expect(p.extraction, ExtractionStatus.verified);
    expect(p.knowledge, KnowledgeStatus.complete);
  });

  test('extraction status follows the fields, not the knowledge catalogue', () {
    final unknown = ResultPresentation.fromExplanation(_result(knowledge: 'unsupported'));
    expect(unknown.extraction, ExtractionStatus.verified);
    expect(unknown.knowledge, KnowledgeStatus.unsupported);
    final missingRange =
        ResultPresentation.fromExplanation(_result(reference: null, range: false));
    expect(missingRange.extraction, ExtractionStatus.review);
  });

  test('outer card states match the specification', () {
    expect(ResultPresentation.fromExplanation(_result()).outerLabel, 'Below printed range');
    expect(ResultPresentation.fromExplanation(_result(state: 'within_range')).outerLabel,
        'Within printed range');
    expect(ResultPresentation.fromExplanation(_result(state: 'above_range')).outerLabel,
        'Above printed range');
    expect(ResultPresentation.fromExplanation(_result(interpret: false)).outerLabel,
        'Review this result');
    expect(ResultPresentation.fromExplanation(_result(reference: null, range: false)).outerLabel,
        'Range not provided');
    expect(ResultPresentation.fromExplanation(_result(unit: false, reference: '12.0-15.0')).outerLabel,
        'Cannot compare');
    expect(ResultPresentation.fromExplanation(_result(knowledge: 'unsupported')).outerLabel,
        'Result available');
  });

  test('review never shows a confirmed comparison label', () {
    final p = ResultPresentation.fromExplanation(_result(interpret: false));
    expect(p.outerStatus, OuterStatus.reviewRequired);
    expect(p.outerLabel, isNot(contains('printed range')));
  });

  test('card summary stays grounded and avoids normal or danger wording', () {
    final p = ResultPresentation.fromExplanation(_result());
    expect(p.cardSummary, contains('range printed on this report'));
    final lower = p.cardSummary.toLowerCase();
    expect(lower, isNot(contains('normal')));
    expect(lower, isNot(contains('danger')));
    expect(lower, isNot(contains('healthy')));
  });

  test('comparison labels use printed-range wording, not normal or dangerous', () {
    final p = ResultPresentation.fromExplanation(_result());
    expect(p.comparisonLabel, 'Below printed range');
    expect(p.comparisonLabel.toLowerCase(), isNot(contains('normal')));
    expect(p.comparisonLabel.toLowerCase(), isNot(contains('danger')));
  });

  test('knowledge status is independent of extraction status', () {
    final p = ResultPresentation.fromExplanation(_result(knowledge: 'unsupported'));
    expect(p.knowledge, KnowledgeStatus.unsupported);
    expect(p.extraction, ExtractionStatus.verified);
    // Knowledge status is independent of the permission gates in this fixture.
    expect(p.knowledge, KnowledgeStatus.unsupported);
  });
}
