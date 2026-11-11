import 'dart:async';
import 'dart:convert';

import '../explanation/explanation_document.dart';
import 'llm_runtime.dart';
import 'output_validator.dart';
import 'prompts.dart';
import 'thinking.dart';

enum AiSource { deterministic, model }

class AiOutcome {
  const AiOutcome({
    required this.text,
    required this.source,
    this.fallbackReason,
    this.validation,
    this.latencyMs,
    this.backend,
    this.answerableDeterministically = false,
  });

  final String text;
  final AiSource source;
  final String? fallbackReason;
  final ValidationResult? validation;
  final double? latencyMs;
  final String? backend;

  /// Answerability is decided here, from the gates, and never read from the
  /// model's own `answerable_from_context` field.
  final bool answerableDeterministically;

  bool get usedModel => source == AiSource.model;
}

/// Runs the deterministic explanation first, then optionally lets the model
/// rewrite it. Any failure returns the deterministic text unchanged.
class ExplanationOrchestrator {
  ExplanationOrchestrator({
    required this.runtimeProvider,
    required this.modelReady,
    this.validator = const GeneratedOutputValidator(),
    this.rewriteTimeout = const Duration(seconds: 180),
    this.followUpTimeout = const Duration(seconds: 180),
  });

  final LlmRuntime? Function() runtimeProvider;
  final bool Function() modelReady;
  final GeneratedOutputValidator validator;
  final Duration rewriteTimeout;
  final Duration followUpTimeout;

  Future<AiOutcome> rewrite(ResultExplanation result) async {
    if (!result.aiRewriteAllowed) {
      return _fallback(result, 'the deterministic gates do not permit AI rewriting');
    }
    final runtime = runtimeProvider();
    if (runtime == null || !modelReady()) {
      return _fallback(result, 'on-device model is not available');
    }
    try {
      final generation = await runtime.generate(
        systemPrompt: systemPrompt,
        userPrompt: rewritePrompt(result),
        timeout: rewriteTimeout,
      );
      final parsed = _parseObject(generation.text);
      final validation = validator.validateRewrite(parsed, result);
      if (!validation.ok) {
        return _fallback(
          result,
          'generated text rejected: ${validation.issues.map((issue) => issue.code).toSet().join(', ')}',
          validation: validation,
        );
      }
      return AiOutcome(
        text: (parsed['rewritten_explanation'] as String).trim(),
        source: AiSource.model,
        validation: validation,
        latencyMs: generation.totalMs,
        backend: generation.backend,
        answerableDeterministically: true,
      );
    } on LlmFailure catch (error) {
      return _fallback(result, 'inference failed: ${error.code}');
    } on TimeoutException {
      return _fallback(result, 'inference timed out');
    } on FormatException {
      return _fallback(result, 'model returned malformed JSON');
    } catch (error) {
      return _fallback(result, 'unexpected inference error: ${error.runtimeType}');
    }
  }

  Future<AiOutcome> answer(ResultExplanation result, String question) async {
    if (!result.aiFollowUpAllowed) {
      return AiOutcome(
        text: _limitationText(result),
        source: AiSource.deterministic,
        fallbackReason: 'the deterministic gates do not permit an AI answer',
        answerableDeterministically: false,
      );
    }
    final runtime = runtimeProvider();
    if (runtime == null || !modelReady()) {
      return AiOutcome(
        text: _limitationText(result),
        source: AiSource.deterministic,
        fallbackReason: 'on-device model is not available',
        answerableDeterministically: true,
      );
    }
    try {
      final generation = await runtime.generate(
        systemPrompt: systemPrompt,
        userPrompt: followUpPrompt(result, question),
        timeout: followUpTimeout,
      );
      final parsed = _parseObject(generation.text);
      final validation = validator.validateFollowUp(parsed, result);
      if (!validation.ok) {
        return AiOutcome(
          text: _limitationText(result),
          source: AiSource.deterministic,
          fallbackReason:
              'generated answer rejected: ${validation.issues.map((issue) => issue.code).toSet().join(', ')}',
          validation: validation,
          answerableDeterministically: true,
        );
      }
      return AiOutcome(
        text: (parsed['answer'] as String).trim(),
        source: AiSource.model,
        validation: validation,
        latencyMs: generation.totalMs,
        backend: generation.backend,
        answerableDeterministically: true,
      );
    } on LlmFailure catch (error) {
      return AiOutcome(
        text: _limitationText(result),
        source: AiSource.deterministic,
        fallbackReason: 'inference failed: ${error.code}',
        answerableDeterministically: true,
      );
    } on TimeoutException {
      return AiOutcome(
        text: _limitationText(result),
        source: AiSource.deterministic,
        fallbackReason: 'inference timed out',
        answerableDeterministically: true,
      );
    } on FormatException {
      return AiOutcome(
        text: _limitationText(result),
        source: AiSource.deterministic,
        fallbackReason: 'model returned malformed JSON',
        answerableDeterministically: true,
      );
    }
  }

  AiOutcome _fallback(ResultExplanation result, String reason, {ValidationResult? validation}) {
    return AiOutcome(
      text: result.deterministicText,
      source: AiSource.deterministic,
      fallbackReason: reason,
      validation: validation,
      answerableDeterministically: false,
    );
  }

  String _limitationText(ResultExplanation result) {
    final limitation = result.section('important_limitations')?.text;
    if (limitation != null && limitation.trim().isNotEmpty) return limitation.trim();
    return 'MediRead cannot answer this from the approved information in the report. '
        'Please ask the clinician who ordered the test.';
  }

  Map<String, dynamic> _parseObject(String raw) {
    final split = splitThinking(raw.trim());
    if (split.malformed) {
      throw const FormatException('unbalanced thinking block');
    }
    var text = split.answer.trim();
    if (text.startsWith('```')) {
      final newline = text.indexOf('\n');
      if (newline != -1) text = text.substring(newline + 1);
      if (text.endsWith('```')) text = text.substring(0, text.length - 3);
    }
    final start = text.indexOf('{');
    final end = text.lastIndexOf('}');
    if (start == -1 || end <= start) {
      throw const FormatException('no JSON object in response');
    }
    final decoded = jsonDecode(text.substring(start, end + 1));
    if (decoded is! Map<String, dynamic>) {
      throw const FormatException('response is not a JSON object');
    }
    return decoded;
  }
}
