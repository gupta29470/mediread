import 'package:flutter_test/flutter_test.dart';
import 'package:mediread_app/src/ai/prompts.dart';
import 'package:mediread_app/src/explanation/explanation_document.dart';

import 'fakes.dart';

void main() {
  test('rewrite prompt cites a real approved source id, not a placeholder', () {
    final prompt = rewritePrompt(explanation());
    expect(prompt, contains('"mp_lab_cbc"'));
    expect(prompt, isNot(contains('approved ids only')));
  });

  test('rewrite prompt names the reported value and printed range to preserve', () {
    final prompt = rewritePrompt(explanation());
    expect(prompt, contains('HEMOGLOBIN 9 g/dL'));
    expect(prompt, contains('Repeat the printed reference range "12.0-15.0"'));
  });

  test('prompt does not invent a source id or value when there is none', () {
    final bare = ResultExplanation.fromJson({
      'result_id': 'r',
      'test_name': 'UNKNOWN',
      'status': 'withheld',
      'knowledge_review_status': 'unsupported',
      'gates': const <String, dynamic>{},
      'permitted': const <String, dynamic>{},
      'facts': const <String, dynamic>{},
      'sections': const <dynamic>[],
    });
    final prompt = rewritePrompt(bare);
    expect(prompt, contains('"used_source_ids": []'));
    expect(prompt, isNot(contains('State the reported result')));
  });

  test('follow-up prompt uses the approved id list too', () {
    final prompt = followUpPrompt(explanation(), 'What is haemoglobin?');
    expect(prompt, contains('"used_source_ids": ["mp_lab_cbc"]'));
    expect(prompt, isNot(contains('approved ids only')));
  });
}
