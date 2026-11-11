/// Pinned model artifact metadata.
///
/// Every field is a fact about a downloaded file, not a guess: the URL, digest
/// and size were read from the publisher (Hugging Face LFS metadata for the
/// compact build, a verified Google Drive file for the FP32 build).
///
/// The compact artifact is the original one and is kept byte-for-byte as it
/// was before the second model was added.
class ModelArtifact {
  const ModelArtifact({
    required this.id,
    required this.displayName,
    required this.version,
    required this.revision,
    required this.fileName,
    required this.url,
    required this.sha256,
    required this.sizeBytes,
    required this.license,
    required this.minAppVersion,
    this.tagline = '',
    this.modelName = '',
    this.alternateSha256 = const [],
    this.description = '',
    this.technicalDetails = '',
  });

  final String id;

  /// Product name shown to people, e.g. "Medi Lite".
  final String displayName;

  /// Short card subtitle, e.g. "Compact AI".
  final String tagline;

  /// The underlying model, shown in small print under the product name.
  final String modelName;
  final String version;
  final String revision;
  final String fileName;
  final String url;
  final String sha256;

  /// Additional validated digests for the same artifact. A model host can
  /// re-serialise an identical export (different bytes, same behaviour), and
  /// both files must still install. Every entry here has passed the same
  /// contract benchmark as [sha256].
  final List<String> alternateSha256;
  final int sizeBytes;
  final String license;
  final int minAppVersion;
  final String description;
  final String technicalDetails;

  /// Title shown on the model card: "Medi Lite — Compact AI".
  String get cardTitle =>
      tagline.isEmpty ? displayName : '$displayName — $tagline';

  /// Small print under the title: "Powered by Qwen3 0.6B".
  String get modelCredit => modelName.isEmpty ? '' : 'Powered by $modelName';

  double get sizeGb => sizeBytes / (1000 * 1000 * 1000);

  /// Free space required before a download starts: the file plus a 512 MB reserve.
  int get requiredFreeBytes => sizeBytes + 512 * 1024 * 1024;

  bool get hasPinnedChecksum => RegExp(r'^[0-9a-f]{64}$').hasMatch(sha256);

  /// Every digest this artifact may legitimately have on disk.
  List<String> get acceptedSha256 => [
    sha256,
    ...alternateSha256.where((digest) => digest != sha256),
  ];

  bool acceptsDigest(String digest) => acceptedSha256.contains(digest);

  bool isCompatibleWith(int appVersion) => appVersion >= minAppVersion;

  String get sizeLabel => sizeBytes >= 1000000000
      ? '${(sizeBytes / 1e9).toStringAsFixed(2)} GB'
      : '${(sizeBytes / 1e6).toStringAsFixed(1)} MB';

  /// Human label used on the cards; "≈" because the download is a fixed size
  /// but storage accounting reports base-10 units.
  String get approxSizeLabel => '≈ $sizeLabel';

  /// Qwen3 0.6B, LiteRT-LM build, revision-pinned.
  ///
  /// This is the original artifact and the default for existing installations.
  static const qwen3_0_6b = qwen3Compact;

  /// The original, compact model. Kept byte-for-byte as before.
  static const qwen3Compact = ModelArtifact(
    id: 'qwen3-0-6b-litertlm',
    displayName: 'Medi Lite',
    tagline: 'Compact AI',
    modelName: 'Qwen3 0.6B',
    version: '1.0.0',
    revision: 'bd47201734a34f1eba8ed7d28289225b60152e9e',
    fileName: 'Qwen3-0.6B.litertlm',
    url:
        'https://huggingface.co/litert-community/Qwen3-0.6B/'
        'resolve/bd47201734a34f1eba8ed7d28289225b60152e9e/Qwen3-0.6B.litertlm',
    sha256: 'c5f39b4191926786c3e6668b62af4d6eb15248dfc7a5348252a9b406f33f2108',
    sizeBytes: 613722264,
    license: 'Apache-2.0',
    minAppVersion: 1,
    description:
        'A lightweight AI model that helps explain your medical reports in '
        'simple language. Requires less storage and a smaller download.',
    technicalDetails: 'LiteRT-LM, 16-bit weights, runtime 0.19.1',
  );

  /// Validated FP32 build (2.39 GB), served from Google Drive.
  ///
  /// SHA-256 and size are those of the validated FP32 artifact. They must never
  /// be replaced with the rejected INT8 build's values.
  static const qwen3Fp32 = ModelArtifact(
    id: 'qwen3-0-6b-fp32',
    displayName: 'Medi Super',
    tagline: 'Detailed AI',
    modelName: 'Qwen3 0.6B FP32',
    version: '1.0.0',
    revision: 'drive-1pskhr290Diou-iVvi2XXphohMkW4AJ_L',
    fileName: 'model-001.litertlm',
    url:
        'https://drive.usercontent.google.com/download'
        '?id=1pskhr290Diou-iVvi2XXphohMkW4AJ_L&export=download&confirm=t',
    sha256: '73cfa641a4018c30b0a48fcd43cb630debc6dfa6bc4ecc2243b8861c53f506fb',
    // The public Drive link currently serves a re-serialised FP32 export of the
    // same model (identical size, different bytes). It passed the same 22-case
    // contract with 22/22 exact token matches, so both files are accepted.
    alternateSha256: [
      '195265f0a414773b5acf4a3910616c137bb7cdc75ee2071dccc10a5cd223a03c',
    ],
    sizeBytes: 2389683152,
    license: 'Apache-2.0',
    minAppVersion: 1,
    description:
        'A larger, higher-precision version of our on-device AI model, '
        'designed to provide more detailed and natural explanations of medical '
        'reports. Requires approximately 2.39 GB of storage and a larger initial '
        'download.',
    technicalDetails:
        'LiteRT-LM, float32 weights, runtime 0.19.1, '
        '22/22 contract cases',
  );

  static const allArtifacts = <ModelArtifact>[qwen3Compact, qwen3Fp32];

  static ModelArtifact? byId(String? id) {
    if (id == null) return null;
    for (final artifact in allArtifacts) {
      if (artifact.id == id) return artifact;
    }
    return null;
  }
}

/// The artifact a fresh installation selects, and the one an existing
/// installation keeps using until the user chooses otherwise.
const ModelArtifact defaultModelArtifact = ModelArtifact.qwen3_0_6b;
