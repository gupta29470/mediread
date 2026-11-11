import 'package:flutter/foundation.dart' show kDebugMode;
import 'package:flutter/material.dart';

import '../ai/orchestrator.dart';
import '../explanation/explanation_document.dart';
import '../ingest/lab_pipeline.dart';
import '../presentation/result_presentation.dart';
import 'theme.dart';

/// One result, collapsed to the facts and expanded in place.
///
/// Everything shown here comes from the deterministic engine: the measured
/// value, unit, printed range and comparison status are rendered exactly as the
/// gates permitted them. Expanding reveals the explanation, limitations,
/// sources and extraction provenance — it never navigates away and never lets
/// the model change a measured value.
class ResultCard extends StatefulWidget {
  const ResultCard({
    super.key,
    required this.result,
    this.evidence,
    this.orchestrator,
    this.modelReady = false,
    this.onSetupModel,
  });

  final ResultExplanation result;
  final ExtractionEvidence? evidence;
  final ExplanationOrchestrator? orchestrator;
  final bool modelReady;
  final VoidCallback? onSetupModel;

  @override
  State<ResultCard> createState() => _ResultCardState();
}

class _ResultCardState extends State<ResultCard> {
  bool _expanded = false;
  bool _busy = false;
  AiOutcome? _rewrite;

  void _toggle() => setState(() => _expanded = !_expanded);

  Future<void> _runRewrite() async {
    final orchestrator = widget.orchestrator;
    if (orchestrator == null) return;
    setState(() => _busy = true);
    final outcome = await orchestrator.rewrite(widget.result);
    if (kDebugMode) {
      // Diagnostic only: explains why the deterministic fallback was used.
      debugPrint('MediRead AI rewrite: source=${outcome.source.name} '
          'reason=${outcome.fallbackReason} latency=${outcome.latencyMs}');
    }
    if (mounted) {
      setState(() {
        _rewrite = outcome;
        _busy = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final result = widget.result;
    final view = ResultPresentation.fromExplanation(result, evidence: widget.evidence);
    final key = result.testName;

    return Container(
      key: ValueKey('result-card-$key'),
      margin: const EdgeInsets.only(bottom: 12),
      decoration: Clinical.card(radius: 18),
      clipBehavior: Clip.antiAlias,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          InkWell(
            onTap: _toggle,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(18, 16, 12, 12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Expanded(
                        child: Text(
                          result.testName,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                              fontSize: 17, fontWeight: FontWeight.w700, letterSpacing: -0.2),
                        ),
                      ),
                      const SizedBox(width: 8),
                      _ExtractionChip(presentation: view),
                    ],
                  ),
                  const SizedBox(height: 8),
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.baseline,
                    textBaseline: TextBaseline.alphabetic,
                    children: [
                      Flexible(
                        child: Text(
                          view.value ?? '—',
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                              fontSize: 30, fontWeight: FontWeight.w700, letterSpacing: -0.8),
                        ),
                      ),
                      if (view.unit != null) ...[
                        const SizedBox(width: 6),
                        Text(view.unit!,
                            style: const TextStyle(color: Clinical.muted, fontSize: 13.5)),
                      ],
                    ],
                  ),
                  if (view.printedRange != null) ...[
                    const SizedBox(height: 4),
                    Text('Printed range: ${view.printedRange}',
                        style: const TextStyle(color: Clinical.muted, fontSize: 12, height: 1.35)),
                  ],
                  const SizedBox(height: 10),
                  StatusPill(
                    label: view.outerLabel,
                    bg: _statusBg(view.outerStatus),
                    fg: _statusFg(view.outerStatus),
                  ),
                  const SizedBox(height: 8),
                  Text(view.statusSentence,
                      style: const TextStyle(
                          color: Clinical.inkSecondary, fontSize: 13.5, height: 1.45)),
                  const SizedBox(height: 6),
                  Row(
                    children: [
                      if (view.knowledge == KnowledgeStatus.unsupported)
                        const Padding(
                          padding: EdgeInsets.only(right: 8),
                          child: StatusPill(
                            label: 'No knowledge entry',
                            bg: Clinical.well,
                            fg: Clinical.muted,
                            dot: false,
                          ),
                        ),
                      if (widget.evidence != null)
                        Text('Page ${widget.evidence!.page}',
                            style: const TextStyle(color: Clinical.muted, fontSize: 11.5)),
                      const Spacer(),
                      Text(_expanded ? 'Hide details' : 'Details',
                          style: const TextStyle(
                              color: Clinical.primary, fontSize: 12.5, fontWeight: FontWeight.w600)),
                      Icon(_expanded ? Icons.expand_less : Icons.expand_more,
                          size: 20, color: Clinical.primary),
                    ],
                  ),
                ],
              ),
            ),
          ),
          if (_expanded)
            Padding(
              key: ValueKey('result-card-details-$key'),
              padding: const EdgeInsets.fromLTRB(18, 0, 18, 18),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Divider(height: 20),
                  ..._sections(result, view),
                  _Provenance(view: view, evidence: widget.evidence),
                  if (widget.orchestrator != null && result.aiRewriteAllowed) ...[
                    const SizedBox(height: 14),
                    _RewriteTile(
                      busy: _busy,
                      outcome: _rewrite,
                      modelReady: widget.modelReady,
                      onSetup: widget.onSetupModel,
                      onRun: _runRewrite,
                    ),
                  ],
                ],
              ),
            ),
        ],
      ),
    );
  }

  List<Widget> _sections(ResultExplanation result, ResultPresentation view) {
    final widgets = <Widget>[];
    void addText(String title, ExplanationSection? section) {
      if (section == null) return;
      if (section.permitted && section.hasText) {
        widgets.add(_DetailBlock(title: title, body: section.text!));
      } else if (section.permitted) {
        return;
      } else {
        widgets.add(_WithheldBlock(title: title, reason: section.reason));
      }
    }

    addText('What this test measures', result.section('what_this_test_measures'));
    addText('What the comparison means', result.section('comparison_with_reference'));
    addText('What this may generally indicate', result.section('what_this_may_generally_indicate'));
    addText('Important limitations', result.section('important_limitations'));

    final sources = result.section('sources');
    if (sources != null && sources.permitted && sources.hasText) {
      widgets.add(_DetailBlock(title: 'Sources', body: sources.text!));
    } else if (sources != null && !sources.permitted && view.knowledge == KnowledgeStatus.unsupported) {
      widgets.add(_WithheldBlock(title: 'Sources', reason: sources.reason));
    }
    return widgets;
  }
}

class _DetailBlock extends StatelessWidget {
  const _DetailBlock({required this.title, required this.body});

  final String title;
  final String body;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title,
              style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: Clinical.ink)),
          const SizedBox(height: 4),
          Text(body,
              style: const TextStyle(color: Clinical.inkSecondary, height: 1.5, fontSize: 13.5)),
        ],
      ),
    );
  }
}

class _WithheldBlock extends StatelessWidget {
  const _WithheldBlock({required this.title, this.reason});

  final String title;
  final String? reason;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(color: Clinical.well, borderRadius: BorderRadius.circular(10)),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Icon(Icons.lock_outline, size: 15, color: Clinical.muted),
            const SizedBox(width: 8),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(title,
                      style: const TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600)),
                  const SizedBox(height: 2),
                  Text(reason ?? 'Not shown for this result.',
                      style: const TextStyle(color: Clinical.muted, fontSize: 12, height: 1.4)),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _Provenance extends StatelessWidget {
  const _Provenance({required this.view, this.evidence});

  final ResultPresentation view;
  final ExtractionEvidence? evidence;

  @override
  Widget build(BuildContext context) {
    final notes = view.reviewNotes;
    return Padding(
      padding: const EdgeInsets.only(top: 2),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('From your report',
              style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700)),
          const SizedBox(height: 6),
          Wrap(
            spacing: 10,
            runSpacing: 6,
            children: [
              _FieldCheck(label: 'Test', ok: view.identify),
              _FieldCheck(label: 'Value', ok: view.interpret),
              _FieldCheck(label: 'Unit', ok: view.unitAllowed),
              _FieldCheck(label: 'Range', ok: view.rangeAllowed),
              if (evidence != null)
                _FieldCheck(label: 'Page ${evidence!.page}', ok: true, neutral: true),
            ],
          ),
          if (notes.isNotEmpty) ...[
            const SizedBox(height: 12),
            const Text('Extraction review',
                style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600)),
            const SizedBox(height: 4),
            for (final note in notes)
              Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Padding(
                      padding: EdgeInsets.only(top: 2),
                      child: Icon(Icons.info_outline, size: 13, color: Clinical.alertFg),
                    ),
                    const SizedBox(width: 6),
                    Expanded(
                      child: Text(note,
                          style: const TextStyle(
                              color: Clinical.inkSecondary, fontSize: 12, height: 1.4)),
                    ),
                  ],
                ),
              ),
          ],
        ],
      ),
    );
  }
}

class _FieldCheck extends StatelessWidget {
  const _FieldCheck({required this.label, required this.ok, this.neutral = false});

  final String label;
  final bool ok;
  final bool neutral;

  @override
  Widget build(BuildContext context) {
    final color = neutral ? Clinical.muted : (ok ? Clinical.normalFg : Clinical.muted);
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(neutral ? Icons.description_outlined : (ok ? Icons.check_circle : Icons.remove_circle_outline),
            size: 13, color: color),
        const SizedBox(width: 4),
        Text(label, style: const TextStyle(fontSize: 11.5, color: Clinical.inkSecondary)),
      ],
    );
  }
}

class _ExtractionChip extends StatelessWidget {
  const _ExtractionChip({required this.presentation});

  final ResultPresentation presentation;

  @override
  Widget build(BuildContext context) {
    final verified = presentation.extraction == ExtractionStatus.verified;
    return StatusPill(
      label: verified ? 'Verified' : 'Review',
      bg: verified ? Clinical.normalBg : Clinical.alertBg,
      fg: verified ? Clinical.normalFg : Clinical.alertFg,
      dot: false,
    );
  }
}

class _RewriteTile extends StatelessWidget {
  const _RewriteTile({
    required this.busy,
    required this.outcome,
    required this.modelReady,
    required this.onSetup,
    required this.onRun,
  });

  final bool busy;
  final AiOutcome? outcome;
  final bool modelReady;
  final VoidCallback? onSetup;
  final VoidCallback onRun;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(color: Clinical.tealWash, borderRadius: BorderRadius.circular(12)),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.auto_awesome, size: 16, color: Clinical.primary),
              const SizedBox(width: 6),
              const Expanded(
                child: Text('Simplify wording',
                    style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600)),
              ),
              TextButton(
                onPressed: busy ? null : (modelReady ? onRun : onSetup),
                child: Text(modelReady ? 'Rewrite' : 'Set up'),
              ),
            ],
          ),
          const Text(
            'Rewrites approved explanation text only. Values, units, ranges and comparisons '
            'are never changed.',
            style: TextStyle(color: Clinical.muted, fontSize: 11.5, height: 1.4),
          ),
          if (busy) const Padding(
            padding: EdgeInsets.only(top: 8),
            child: LinearProgressIndicator(minHeight: 2),
          ),
          if (outcome != null) ...[
            const SizedBox(height: 8),
            Text(
              outcome!.usedModel
                  ? 'Generated on device · ${outcome!.backend ?? 'runtime'}'
                  : 'Deterministic fallback',
              style: const TextStyle(fontSize: 11, color: Clinical.primary),
            ),
            const SizedBox(height: 4),
            Text(outcome!.text,
                style: const TextStyle(color: Clinical.inkSecondary, height: 1.45, fontSize: 13)),
          ],
        ],
      ),
    );
  }
}

Color _statusBg(OuterStatus status) => switch (status) {
      OuterStatus.withinRange => Clinical.normalBg,
      OuterStatus.belowRange ||
      OuterStatus.aboveRange ||
      OuterStatus.meetsBound ||
      OuterStatus.outsideBound ||
      OuterStatus.reviewRequired =>
        Clinical.alertBg,
      OuterStatus.rangeNotProvided || OuterStatus.cannotCompare || OuterStatus.resultAvailable => Clinical.well,
    };

Color _statusFg(OuterStatus status) => switch (status) {
      OuterStatus.withinRange => Clinical.normalFg,
      OuterStatus.belowRange ||
      OuterStatus.aboveRange ||
      OuterStatus.meetsBound ||
      OuterStatus.outsideBound ||
      OuterStatus.reviewRequired =>
        Clinical.alertFg,
      OuterStatus.rangeNotProvided || OuterStatus.cannotCompare || OuterStatus.resultAvailable => Clinical.muted,
    };
