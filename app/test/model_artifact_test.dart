import 'package:flutter_test/flutter_test.dart';
import 'package:mediread_app/src/ai/model_artifact.dart';

void main() {
  test('two distinct artifacts are offered', () {
    expect(ModelArtifact.allArtifacts, hasLength(2));
    final ids = ModelArtifact.allArtifacts.map((a) => a.id).toSet();
    expect(ids, hasLength(2));
    expect(
      ModelArtifact.byId(ModelArtifact.qwen3Compact.id),
      same(ModelArtifact.qwen3Compact),
    );
    expect(
      ModelArtifact.byId(ModelArtifact.qwen3Fp32.id),
      same(ModelArtifact.qwen3Fp32),
    );
    expect(ModelArtifact.byId('nope'), isNull);
    expect(ModelArtifact.byId(null), isNull);
  });

  test('FP32 artifact pins the validated Drive metadata exactly', () {
    const fp32 = ModelArtifact.qwen3Fp32;
    expect(fp32.id, 'qwen3-0-6b-fp32');
    expect(fp32.displayName, 'Medi Super');
    expect(fp32.modelName, 'Qwen3 0.6B FP32');
    expect(fp32.modelCredit, 'Powered by Qwen3 0.6B FP32');
    expect(fp32.tagline, 'Detailed AI');
    expect(fp32.cardTitle, 'Medi Super — Detailed AI');
    expect(fp32.fileName, 'model-001.litertlm');
    expect(fp32.sizeBytes, 2389683152);
    expect(fp32.sizeLabel, '2.39 GB');
    expect(fp32.approxSizeLabel, '≈ 2.39 GB');
    expect(
      fp32.sha256,
      '73cfa641a4018c30b0a48fcd43cb630debc6dfa6bc4ecc2243b8861c53f506fb',
    );
    expect(
      fp32.url,
      'https://drive.usercontent.google.com/download'
      '?id=1pskhr290Diou-iVvi2XXphohMkW4AJ_L&export=download&confirm=t',
    );
    expect(fp32.url, isNot(contains('/folders/')));
    expect(fp32.hasPinnedChecksum, isTrue);
    expect(
      fp32.alternateSha256,
      contains(
        '195265f0a414773b5acf4a3910616c137bb7cdc75ee2071dccc10a5cd223a03c',
      ),
    );
    expect(fp32.acceptedSha256, hasLength(2));
    expect(fp32.acceptsDigest(fp32.sha256), isTrue);
    expect(fp32.acceptsDigest(fp32.alternateSha256.single), isTrue);
    expect(fp32.acceptsDigest('b' * 64), isFalse);
    expect(fp32.license, 'Apache-2.0');
    expect(fp32.version, '1.0.0');
    expect(fp32.revision, 'drive-1pskhr290Diou-iVvi2XXphohMkW4AJ_L');
    expect(fp32.description.toLowerCase(), isNot(contains('clinically')));
    expect(fp32.description.toLowerCase(), contains('2.39 gb'));
  });

  test('compact artifact keeps the original checksum and is the default', () {
    const compact = ModelArtifact.qwen3Compact;
    expect(compact.id, 'qwen3-0-6b-litertlm');
    expect(compact.displayName, 'Medi Lite');
    expect(compact.modelName, 'Qwen3 0.6B');
    expect(compact.modelCredit, 'Powered by Qwen3 0.6B');
    expect(compact.tagline, 'Compact AI');
    expect(compact.cardTitle, 'Medi Lite — Compact AI');
    expect(compact.fileName, 'Qwen3-0.6B.litertlm');
    expect(compact.sizeBytes, 613722264);
    expect(
      compact.sha256,
      'c5f39b4191926786c3e6668b62af4d6eb15248dfc7a5348252a9b406f33f2108',
    );
    expect(
      identical(ModelArtifact.qwen3_0_6b, ModelArtifact.qwen3Compact),
      isTrue,
    );
    expect(identical(defaultModelArtifact, ModelArtifact.qwen3Compact), isTrue);
    expect(
      ModelArtifact.qwen3Fp32.sha256,
      isNot(ModelArtifact.qwen3Compact.sha256),
    );
  });

  test('rejected INT8 artifact is not referenced anywhere', () {
    for (final artifact in ModelArtifact.allArtifacts) {
      expect(artifact.sha256.toLowerCase(), isNot(startsWith('082f0dfc')));
      expect(artifact.id.toLowerCase(), isNot(contains('int8')));
      expect(artifact.id.toLowerCase(), isNot(contains('int4')));
      expect(artifact.fileName, isNot(contains('wo8')));
    }
  });

  test('storage requirement includes headroom over the file size', () {
    for (final artifact in ModelArtifact.allArtifacts) {
      expect(artifact.requiredFreeBytes, greaterThan(artifact.sizeBytes));
      expect(
        artifact.requiredFreeBytes - artifact.sizeBytes,
        512 * 1024 * 1024,
      );
    }
  });

  test('each artifact has its own file name and identity', () {
    final names = ModelArtifact.allArtifacts.map((a) => a.fileName).toSet();
    expect(names, hasLength(2));
    final urls = ModelArtifact.allArtifacts.map((a) => a.url).toSet();
    expect(urls, hasLength(2));
  });
}
