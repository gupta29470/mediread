import 'package:mediread_app/src/ai/llm_runtime.dart';
import 'package:mediread_app/src/explanation/explanation_document.dart';

class FakeRuntime implements LlmRuntime {
  FakeRuntime({this.text = '', this.failure, this.delay = Duration.zero});

  String text;
  LlmFailure? failure;
  Duration delay;
  int calls = 0;
  bool _loaded = false;

  @override
  String get runtimeName => 'fake';

  @override
  Future<void> load(String modelPath, {String backend = 'auto'}) async {
    _loaded = true;
  }

  @override
  Future<LlmGeneration> generate({
    required String systemPrompt,
    required String userPrompt,
    int maxTokens = 512,
    Duration timeout = const Duration(seconds: 90),
  }) async {
    calls++;
    if (delay > Duration.zero) await Future<void>.delayed(delay);
    if (failure != null) throw failure!;
    return LlmGeneration(text: text, totalMs: 12);
  }

  @override
  Future<void> unload() async => _loaded = false;

  @override
  Future<bool> isLoaded() async => _loaded;
}

ResultExplanation explanation({
  String testName = 'HEMOGLOBIN',
  String? valueText = '9',
  String? unitText = 'g/dL',
  String? referenceText = '12.0-15.0',
  bool identify = true,
  bool interpret = true,
  bool unit = true,
  bool range = true,
  String knowledge = 'approved',
  String coverage = 'complete',
  String limitation = 'This is educational and is not a diagnosis.',
}) {
  return ResultExplanation(
    resultId: 'r1',
    testName: testName,
    status: 'explained',
    knowledgeStatus: knowledge,
    knowledgeCoverage: coverage,
    gates: {
      'identify_test': identify,
      'interpret_value': interpret,
      'unit_comparison': unit,
      'range_comparison': range,
    },
    permitted: const {},
    facts: ResultFacts(
      valueText: valueText,
      unitText: unitText,
      referenceText: referenceText,
    ),
    sections: [
      const ExplanationSection(
        key: 'what_this_test_measures',
        permitted: true,
        text: 'Haemoglobin carries oxygen in red blood cells.',
      ),
      ExplanationSection(
        key: 'your_reported_result',
        permitted: true,
        text: 'Your report lists $valueText $unitText for $testName.',
      ),
      if (range)
        ExplanationSection(
          key: 'comparison_with_reference',
          permitted: true,
          text: 'The value is below the reference interval $referenceText.',
        )
      else
        const ExplanationSection(
          key: 'comparison_with_reference',
          permitted: false,
          reason: 'reference is missing',
        ),
      const ExplanationSection(
        key: 'what_this_may_generally_indicate',
        permitted: true,
        text: 'Low levels may be described as low haemoglobin.',
      ),
      ExplanationSection(
        key: 'important_limitations',
        permitted: true,
        text: limitation,
      ),
      const ExplanationSection(
        key: 'sources',
        permitted: true,
        text: 'Complete Blood Count. Source: MedlinePlus.',
        sources: ['mp_lab_cbc'],
      ),
    ],
  );
}
