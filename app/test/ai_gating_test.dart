import 'package:flutter_test/flutter_test.dart';
import 'package:mediread_app/src/ai/orchestrator.dart';
import 'package:mediread_app/src/explanation/explanation_document.dart';
import 'fakes.dart';

void main() {
  late FakeRuntime runtime;
  late ExplanationOrchestrator orchestrator;

  setUp(() {
    runtime = FakeRuntime(text: '{"rewritten_explanation": "Rewritten."}');
    orchestrator = ExplanationOrchestrator(
      runtimeProvider: () => runtime,
      modelReady: () => true,
    );
  });

  test('ambiguous/unsupported knowledge never reaches the model', () async {
    final result = explanation(knowledge: 'unsupported');
    expect(result.hasKnowledge, isFalse);
    expect(result.aiRewriteAllowed, isFalse);

    final outcome = await orchestrator.rewrite(result);
    expect(outcome.usedModel, isFalse);
    expect(outcome.source, AiSource.deterministic);
    expect(runtime.calls, 0);
  });

  test('unknown knowledgeStatus (draft/unknown) is treated as no knowledge', () async {
    // The engine maps unsupported/ambiguous/unknown to 'unsupported'; any other
    // value must still gate the model unless it is an explained status.
    final result = explanation(knowledge: 'unsupported');
    expect(result.aiFollowUpAllowed, isFalse);
    expect(runtime.calls, 0);
  });

  test('blocked identify gate never reaches the model', () async {
    final result = explanation(identify: false);
    expect(result.aiRewriteAllowed, isFalse);
    final outcome = await orchestrator.rewrite(result);
    expect(outcome.usedModel, isFalse);
    expect(runtime.calls, 0);
  });

  test('blocked interpret gate never reaches the model', () async {
    final result = explanation(interpret: false);
    expect(result.aiRewriteAllowed, isFalse);
    await orchestrator.rewrite(result);
    expect(runtime.calls, 0);
  });

  test('approved knowledge with open gates is allowed to reach the model', () async {
    final result = explanation(knowledge: 'approved');
    expect(result.aiRewriteAllowed, isTrue);
    expect(result.aiFollowUpAllowed, isTrue);
  });

  test('follow-up with blocked gates returns deterministic limitation text', () async {
    final result = explanation(range: false);
    expect(result.aiFollowUpAllowed, isFalse);
    final outcome = await orchestrator.answer(result, 'Is this serious?');
    expect(outcome.usedModel, isFalse);
    expect(runtime.calls, 0);
  });

  // The knowledge gate is an exact equality on 'approved'. Every other value —
  // including ones the engine might emit later — must be treated as blocked.
  for (final status in const [
    'ambiguous',
    'unknown',
    'draft',
    'reviewed',
    'blocked',
    'unsupported',
    'pending',
    '',
    'APPROVED',
  ]) {
    test('knowledgeStatus "$status" never reaches the model', () async {
      final result = explanation(knowledge: status);
      expect(result.hasKnowledge, isFalse, reason: 'only approved counts as knowledge');

      final rewrite = await orchestrator.rewrite(result);
      final answer = await orchestrator.answer(result, 'Is this serious?');

      expect(rewrite.usedModel, isFalse);
      expect(answer.usedModel, isFalse);
      expect(answer.source, AiSource.deterministic);
      expect(runtime.calls, 0, reason: 'blocked results must not invoke the runtime');
      expect(rewrite.text, result.deterministicText);
    });
  }

  test('blocked identification and interpretation never reach the model', () async {
    for (final result in [
      explanation(identify: false),
      explanation(interpret: false),
      explanation(identify: false, interpret: false),
    ]) {
      expect(result.aiRewriteAllowed, isFalse);
      expect(result.aiFollowUpAllowed, isFalse);
      await orchestrator.rewrite(result);
      await orchestrator.answer(result, 'What does this mean?');
    }
    expect(runtime.calls, 0);
  });

  test('every one of the sixteen gate combinations is decided without the model', () async {
    var allowed = 0;
    for (final identify in [false, true]) {
      for (final interpret in [false, true]) {
        for (final unit in [false, true]) {
          for (final range in [false, true]) {
            final result = explanation(
              identify: identify,
              interpret: interpret,
              unit: unit,
              range: range,
            );
            final expected = identify && interpret;
            expect(result.aiRewriteAllowed, expected);
            if (expected) allowed++;
            if (!expected) {
              await orchestrator.rewrite(result);
              await orchestrator.answer(result, 'Explain');
            }
          }
        }
      }
    }
    expect(allowed, 4);
    expect(runtime.calls, 0, reason: 'no blocked combination may call the runtime');
  });

  test('approved and fully gated results do reach the model exactly once each', () async {
    final both = FakeRuntime(
      text: '{"rewritten_explanation": "Your report shows HEMOGLOBIN 9 g/dL. '
          'The reference range printed on your report is 12.0-15.0 g/dL. '
          'This information is educational and is not a diagnosis.", '
          '"answer": "An answer.", "answerable_from_context": true, '
          '"used_source_ids": ["mp_lab_cbc"], '
          '"limitations_acknowledged": true, '
          '"limitation": "This is educational and is not a diagnosis."}',
    );
    final bothOrchestrator = ExplanationOrchestrator(
      runtimeProvider: () => both,
      modelReady: () => true,
    );
    final result = explanation();
    expect(result.hasKnowledge, isTrue);
    expect(result.aiRewriteAllowed, isTrue);
    expect(result.aiFollowUpAllowed, isTrue);

    final rewrite = await bothOrchestrator.rewrite(result);
    final answer = await bothOrchestrator.answer(result, 'What is haemoglobin?');

    expect(rewrite.usedModel, isTrue);
    expect(answer.usedModel, isTrue);
    expect(both.calls, 2);
  });

  Map<String, dynamic> document(Map<String, dynamic> extra) => {
        'result_id': 'r',
        'test_name': 'HEMOGLOBIN',
        'status': 'explained',
        'gates': {
          'identify_test': true,
          'interpret_value': true,
          'unit_comparison': true,
          'range_comparison': true,
        },
        'permitted': <String, dynamic>{},
        'sections': <dynamic>[],
        ...extra,
      };

  test('coverage alone never opens the model gate', () {
    final result = ResultExplanation.fromJson(document({
      'knowledge_status': 'complete',
      'knowledge_coverage': 'complete',
    }));
    expect(result.knowledgeStatus, 'complete');
    expect(result.hasKnowledge, isFalse);
    expect(result.aiRewriteAllowed, isFalse);
  });

  test('only an exact approved review status opens the model gate', () {
    for (final review in [
      'approved',
      'draft',
      'reviewed',
      'blocked',
      'unsupported',
      'APPROVED',
      '',
    ]) {
      final result = ResultExplanation.fromJson(document({
        'knowledge_status': 'complete',
        'knowledge_coverage': 'complete',
        'knowledge_review_status': review,
      }));
      expect(result.hasKnowledge, review == 'approved', reason: 'review=$review');
    }

    final approved = ResultExplanation.fromJson(document({
      'knowledge_status': 'complete',
      'knowledge_coverage': 'complete',
      'knowledge_review_status': 'approved',
    }));
    expect(approved.hasKnowledge, isTrue);
    expect(approved.aiRewriteAllowed, isTrue);
    expect(approved.aiFollowUpAllowed, isTrue);
  });

  test('approved knowledge with partial coverage is still reviewable', () {
    final result = ResultExplanation.fromJson(document({
      'knowledge_status': 'partial',
      'knowledge_coverage': 'partial',
      'knowledge_review_status': 'approved',
    }));
    expect(result.knowledgeCoverage, 'partial');
    expect(result.hasKnowledge, isTrue);
  });
}
