import 'package:flutter_test/flutter_test.dart';
import 'package:mediread_app/src/ai/llm_runtime.dart';
import 'package:mediread_app/src/ai/orchestrator.dart';
import 'package:mediread_app/src/explanation/explanation_document.dart';

import 'fakes.dart';

const validRewrite = '{"rewritten_explanation": "Your haemoglobin is 9 g/dL, below the '
    '12.0-15.0 g/dL interval printed on your report. This is education and not a diagnosis.", '
    '"used_source_ids": ["mp_lab_cbc"], "limitations_acknowledged": true}';

const validAnswer = '{"answer": "It is below the 12.0-15.0 g/dL range printed on your report.", '
    '"answerable_from_context": true, "used_source_ids": ["mp_lab_cbc"], "limitation": ""}';

ExplanationOrchestrator build(FakeRuntime runtime, {bool ready = true}) =>
    ExplanationOrchestrator(runtimeProvider: () => runtime, modelReady: () => ready);

void main() {
  test('uses the model when the rewrite is valid', () async {
    final runtime = FakeRuntime(text: validRewrite);
    final outcome = await build(runtime).rewrite(explanation());
    expect(outcome.source, AiSource.model);
    expect(outcome.text, contains('9 g/dL'));
  });

  test('falls back when the gates forbid AI rewriting', () async {
    final runtime = FakeRuntime(text: validRewrite);
    final outcome = await build(runtime).rewrite(explanation(identify: false));
    expect(outcome.source, AiSource.deterministic);
    expect(runtime.calls, 0);
    expect(outcome.fallbackReason, contains('gates'));
  });

  test('falls back when the model is not ready', () async {
    final runtime = FakeRuntime(text: validRewrite);
    final outcome = await build(runtime, ready: false).rewrite(explanation());
    expect(outcome.source, AiSource.deterministic);
    expect(runtime.calls, 0);
  });

  test('falls back on inference failure', () async {
    final runtime = FakeRuntime(failure: const LlmFailure('timeout', 'slow'));
    final outcome = await build(runtime).rewrite(explanation());
    expect(outcome.source, AiSource.deterministic);
    expect(outcome.fallbackReason, contains('timeout'));
  });

  test('falls back on malformed JSON', () async {
    final runtime = FakeRuntime(text: 'not json at all');
    final outcome = await build(runtime).rewrite(explanation());
    expect(outcome.source, AiSource.deterministic);
    expect(outcome.fallbackReason, contains('malformed'));
  });

  test('falls back when the model invents a number', () async {
    final runtime = FakeRuntime(
      text: '{"rewritten_explanation": "Your value is 99.9 g/dL, below 12.0-15.0. '
          'This is education and not a diagnosis.", "used_source_ids": [], '
          '"limitations_acknowledged": true}',
    );
    final outcome = await build(runtime).rewrite(explanation());
    expect(outcome.source, AiSource.deterministic);
    expect(outcome.validation?.hasCode('invented_number'), isTrue);
  });

  test('falls back when the model omits the value', () async {
    final runtime = FakeRuntime(
      text: '{"rewritten_explanation": "Your haemoglobin is below the 12.0-15.0 g/dL '
          'interval. This is education and not a diagnosis.", "used_source_ids": [], '
          '"limitations_acknowledged": true}',
    );
    final outcome = await build(runtime).rewrite(explanation());
    expect(outcome.source, AiSource.deterministic);
    expect(outcome.validation?.hasCode('value_omitted'), isTrue);
  });

  test('answer is not attempted when a gate is blocked', () async {
    final runtime = FakeRuntime(text: validAnswer);
    final outcome = await build(runtime).answer(explanation(range: false), 'Is this normal?');
    expect(runtime.calls, 0);
    expect(outcome.answerableDeterministically, isFalse);
    expect(outcome.text, contains('educational'));
  });

  test('answer uses the model when all gates are open', () async {
    final runtime = FakeRuntime(text: validAnswer);
    final outcome = await build(runtime).answer(explanation(), 'Is this within range?');
    expect(outcome.source, AiSource.model);
    expect(outcome.answerableDeterministically, isTrue);
  });

  test('answer falls back on timeout', () async {
    final runtime = FakeRuntime(failure: const LlmFailure('timeout', 'slow'));
    final outcome = await build(runtime).answer(explanation(), 'Is this within range?');
    expect(outcome.source, AiSource.deterministic);
    expect(outcome.text, contains('educational'));
  });

  test('deterministic text never includes blocked sections', () async {
    final outcome = await build(FakeRuntime()).rewrite(explanation(range: false));
    expect(outcome.text, isNot(contains('below the reference interval')));
  });

  test('a blocked section carrying text is never sent to the model', () async {
    String? seenPrompt;
    final runtime = _CapturingRuntime((prompt) => seenPrompt = prompt, text: validRewrite);
    final withHidden = ResultExplanation(
      resultId: 'r1',
      testName: 'HEMOGLOBIN',
      status: 'explained',
      knowledgeStatus: 'approved',
      gates: const {
        'identify_test': true,
        'interpret_value': true,
        'unit_comparison': true,
        'range_comparison': false,
      },
      permitted: const {},
      facts: const ResultFacts(valueText: '9', unitText: 'g/dL'),
      sections: const [
        ExplanationSection(
          key: 'what_this_test_measures',
          permitted: true,
          text: 'Haemoglobin carries oxygen.',
        ),
        ExplanationSection(
          key: 'what_this_may_generally_indicate',
          permitted: true,
          text: 'Low levels are described as low haemoglobin.',
        ),
        ExplanationSection(
          key: 'important_limitations',
          permitted: true,
          text: 'This is education and not a diagnosis.',
        ),
        ExplanationSection(
          key: 'comparison_with_reference',
          permitted: false,
          text: 'SECRET_HIDDEN_TEXT',
          reason: 'reference is stratified',
        ),
      ],
    );
    await ExplanationOrchestrator(
      runtimeProvider: () => runtime,
      modelReady: () => true,
    ).rewrite(withHidden);
    expect(seenPrompt, isNotNull);
    expect(seenPrompt, isNot(contains('SECRET_HIDDEN_TEXT')));
    expect(seenPrompt, contains('reference is stratified'));
  });
}

class _CapturingRuntime extends FakeRuntime {
  _CapturingRuntime(void Function(String) onPrompt, {super.text}) : _onPrompt = onPrompt;

  final void Function(String) _onPrompt;

  @override
  Future<LlmGeneration> generate({
    required String systemPrompt,
    required String userPrompt,
    int maxTokens = 512,
    Duration timeout = const Duration(seconds: 90),
  }) {
    _onPrompt(userPrompt);
    return super.generate(
      systemPrompt: systemPrompt,
      userPrompt: userPrompt,
      maxTokens: maxTokens,
      timeout: timeout,
    );
  }
}
