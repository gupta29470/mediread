/// Replaceable on-device runtime interface.
///
/// Business logic depends only on this file. Swapping LiteRT-LM for another
/// runtime means implementing this interface; nothing in the explanation
/// pipeline changes.
abstract interface class LlmRuntime {
  String get runtimeName;

  Future<void> load(String modelPath, {String backend = 'auto'});

  Future<LlmGeneration> generate({
    required String systemPrompt,
    required String userPrompt,
    int maxTokens = 512,
    Duration timeout = const Duration(seconds: 90),
  });

  Future<void> unload();

  Future<bool> isLoaded();
}

class LlmGeneration {
  const LlmGeneration({
    required this.text,
    required this.totalMs,
    this.ttftMs,
    this.outputTokens,
    this.tokensPerSecond,
    this.backend = 'unknown',
  });

  final String text;
  final double totalMs;
  final double? ttftMs;
  final int? outputTokens;
  final double? tokensPerSecond;
  final String backend;
}

class LlmFailure implements Exception {
  const LlmFailure(this.code, this.message);

  final String code;
  final String message;

  @override
  String toString() => 'LlmFailure($code): $message';
}
