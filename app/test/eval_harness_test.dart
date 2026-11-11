import 'package:flutter_test/flutter_test.dart';
import 'package:mediread_app/src/ai/llm_runtime.dart';
import 'package:mediread_app/src/ai/model_artifact.dart';
import 'package:mediread_app/src/eval/eval_harness.dart';
import 'package:mediread_app/src/ui/demo_data.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('pinned artifact metadata is complete and immutable', () {
    const artifact = ModelArtifact.qwen3_0_6b;
    expect(artifact.hasPinnedChecksum, isTrue);
    expect(artifact.sha256.length, 64);
    expect(artifact.sizeBytes, 613722264);
    expect(artifact.url, contains(artifact.revision));
    expect(artifact.license, contains('Apache-2.0'));
  });

  test('replaying recorded E4B outputs reproduces the offline verdicts', () async {
    final canned = await DemoData.loadCannedOutputs();
    final runner = MobileEvalRunner(
      generate: (evalCase) async => LlmGeneration(
        text: canned[evalCase.caseId] ?? '',
        totalMs: 1,
      ),
    );
    final report = await runner.run(mode: 'canned-e4b');
    final failed = report.runs.where((run) => !run.passed).map((run) => run.caseId).toSet();
    expect(report.total, 21);
    expect(report.schemaValid, 21);
    expect(report.overclaims, 2);
    expect(report.passed, 19);
    expect(failed, {'F01_anemia_question', 'F09_contradictory_information'});
  });

  test('blocked sections never become permitted content', () async {
    final runner = MobileEvalRunner(generate: (_) async => const LlmGeneration(text: '{}', totalMs: 0));
    final cases = await runner.loadCases();
    expect(cases.length, 21);
    for (final evalCase in cases) {
      final explanation = evalCase.toExplanation();
      for (final key in evalCase.blockedSections.keys) {
        expect(explanation.section(key)?.permitted, isFalse, reason: '${evalCase.caseId}:$key');
      }
    }
  });

  test('gates alone close follow-ups for blocked or unsupported cases', () async {
    final runner = MobileEvalRunner(generate: (_) async => const LlmGeneration(text: '{}', totalMs: 0));
    final cases = await runner.loadCases();
    for (final evalCase in cases) {
      final hasBlockedGate = evalCase.blockedSections.keys.any(
        (key) => key == 'what_this_test_measures' || key == 'comparison_with_reference',
      );
      final unsupported = evalCase.facts['knowledge_status'] == 'unsupported';
      if (hasBlockedGate || unsupported) {
        expect(evalCase.toExplanation().aiFollowUpAllowed, isFalse, reason: evalCase.caseId);
      }
    }
  });
}
