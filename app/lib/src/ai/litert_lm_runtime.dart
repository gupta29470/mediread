import 'dart:async';

import 'package:flutter/services.dart';

import 'llm_runtime.dart';

/// LiteRT-LM implementation, backed by the native Android bridge in
/// `LiteRtLmBridge.kt` (official `com.google.ai.edge.litertlm` Kotlin API).
class LiteRtLmRuntime implements LlmRuntime {
  LiteRtLmRuntime({MethodChannel? channel})
      : _channel = channel ?? const MethodChannel('app.mediread/litertlm');

  final MethodChannel _channel;
  bool _loaded = false;

  @override
  String get runtimeName => 'litert-lm-android';

  @override
  Future<void> load(String modelPath, {String backend = 'auto'}) async {
    try {
      final result = await _channel.invokeMapMethod<String, dynamic>('load', {
        'modelPath': modelPath,
        'backend': backend,
      }).timeout(const Duration(minutes: 3));
      _loaded = result?['loaded'] == true;
    } on TimeoutException {
      throw const LlmFailure('load_timeout', 'Model load timed out');
    } on PlatformException catch (error) {
      throw LlmFailure(error.code, error.message ?? 'Model load failed');
    }
    if (!_loaded) {
      throw const LlmFailure('load_failed', 'Runtime did not report a loaded engine');
    }
  }

  @override
  Future<LlmGeneration> generate({
    required String systemPrompt,
    required String userPrompt,
    int maxTokens = 512,
    Duration timeout = const Duration(seconds: 240),
  }) async {
    if (!_loaded) {
      throw const LlmFailure('not_loaded', 'No model is loaded');
    }
    try {
      final result = await _channel.invokeMapMethod<String, dynamic>('generate', {
        'systemPrompt': systemPrompt,
        'userPrompt': userPrompt,
        'maxTokens': maxTokens,
      }).timeout(timeout);
      if (result == null) {
        throw const LlmFailure('empty_result', 'Runtime returned no result');
      }
      return LlmGeneration(
        text: (result['text'] as String?) ?? '',
        totalMs: (result['totalMs'] as num?)?.toDouble() ?? 0,
        ttftMs: (result['ttftMs'] as num?)?.toDouble(),
        outputTokens: (result['outputTokens'] as num?)?.toInt(),
        tokensPerSecond: (result['tokensPerSecond'] as num?)?.toDouble(),
        backend: (result['backend'] as String?) ?? 'unknown',
      );
    } on TimeoutException {
      throw const LlmFailure('timeout', 'Generation timed out');
    } on PlatformException catch (error) {
      throw LlmFailure(error.code, error.message ?? 'Generation failed');
    }
  }

  @override
  Future<void> unload() async {
    try {
      await _channel.invokeMethod<void>('unload');
    } on PlatformException {
      // Unloading is best-effort.
    }
    _loaded = false;
  }

  @override
  Future<bool> isLoaded() async => _loaded;
}
