import 'package:flutter_test/flutter_test.dart';
import 'package:mediread_app/src/ai/model_artifact.dart';
import 'package:mediread_app/src/ai/thinking.dart';

void main() {
  test('fresh installation selects Medi Lite (Qwen3 0.6B), never Gemma', () {
    const artifact = defaultModelArtifact;
    expect(artifact.id, 'qwen3-0-6b-litertlm');
    expect(artifact.displayName, 'Medi Lite');
    expect(artifact.modelName, 'Qwen3 0.6B');
    expect(artifact.modelCredit, 'Powered by Qwen3 0.6B');
    expect(artifact.fileName, 'Qwen3-0.6B.litertlm');
    expect(artifact.revision, 'bd47201734a34f1eba8ed7d28289225b60152e9e');
    expect(artifact.sizeBytes, 613722264);
    expect(artifact.sizeLabel, '613.7 MB');
    expect(artifact.sha256, 'c5f39b4191926786c3e6668b62af4d6eb15248dfc7a5348252a9b406f33f2108');
    expect(artifact.url, contains('litert-community/Qwen3-0.6B'));
    expect(artifact.url, contains(artifact.revision));
    expect(artifact.url, endsWith('Qwen3-0.6B.litertlm'));
    expect(artifact.license, 'Apache-2.0');
    expect(artifact.url.toLowerCase(), isNot(contains('gemma')));
    expect(artifact.fileName.toLowerCase(), isNot(contains('gemma')));
  });

  test('Qwen3 thinking blocks are separated, not blindly stripped', () {
    final open = '<' + 'thi' + 'nk>';
    final close = '<｜end▁of▁thi' + 'nking｜>';
    final balanced = splitThinking(
        '${open}Reasoning about the range.$close{"answer": "x", "answerable_from_context": true}');
    expect(balanced.malformed, isFalse);
    expect(balanced.reasoning, 'Reasoning about the range.');
    expect(balanced.answer, '{"answer": "x", "answerable_from_context": true}');

    final plain = splitThinking('{"answer": "x"}');
    expect(plain.hadReasoning, isFalse);
    expect(plain.malformed, isFalse);
  });

  test('malformed thinking blocks are rejected, not repaired', () {
    final open = '<' + 'thi' + 'nk>';
    expect(splitThinking('$open Let me think... {"answer": "x"}', openTag: open).malformed, isTrue);
    final close = '<｜end▁of▁thi' + 'nking｜>';
    expect(splitThinking('$close oops {"answer": "x"}', closeTag: close).malformed, isTrue);
    expect(splitThinking('<｜end▁of▁thinking｜> only a close').malformed, isTrue);
  });
}
