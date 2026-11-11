import 'dart:convert';

import 'package:flutter/material.dart';

import '../ai/llm_runtime.dart';
import '../ai/model_service.dart';
import '../eval/eval_harness.dart';
import 'demo_data.dart';

class EvalPage extends StatefulWidget {
  const EvalPage({super.key, required this.service});

  final OnDeviceModelService service;

  @override
  State<EvalPage> createState() => _EvalPageState();
}

class _EvalPageState extends State<EvalPage> {
  EvalReport? _report;
  bool _running = false;
  String _mode = '';

  Future<void> _run() async {
    setState(() { _running = true; _report = null; });
    final useDevice = widget.service.isReady;
    _mode = useDevice ? 'device-litertlm' : 'canned-e4b';
    late final MobileEvalRunner runner;
    if (useDevice) {
      runner = MobileEvalRunner(
        generate: (evalCase) => widget.service.runtime.generate(
          systemPrompt: MobileEvalRunner.systemPrompt,
          userPrompt: runner.promptFor(evalCase),
          timeout: const Duration(seconds: 120),
        ),
      );
    } else {
      final canned = await DemoData.loadCannedOutputs();
      runner = MobileEvalRunner(
        generate: (evalCase) async => LlmGeneration(
          text: canned[evalCase.caseId] ?? '',
          totalMs: 0,
        ),
      );
    }
    final report = await runner.run(mode: _mode);
    if (mounted) setState(() { _report = report; _running = false; });
  }

  @override
  Widget build(BuildContext context) {
    final report = _report;
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(title: const Text('21-case evaluation')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(
            widget.service.isReady
                ? 'Running against the installed LiteRT-LM model.'
                : 'No model is loaded: this run replays the recorded E4B outputs to validate '
                    'the harness itself. Load the model for real on-device results.',
            style: theme.textTheme.bodySmall,
          ),
          const SizedBox(height: 12),
          FilledButton(
            onPressed: _running ? null : _run,
            child: Text(_running ? 'Running…' : 'Run all 21 cases'),
          ),
          if (_running) const Padding(
            padding: EdgeInsets.only(top: 12),
            child: LinearProgressIndicator(),
          ),
          if (report != null) ...[
            const SizedBox(height: 16),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('Mode: ${report.mode}', style: theme.textTheme.titleMedium),
                    Text('Passed: ${report.passed}/${report.total}'),
                    Text('Schema valid: ${report.schemaValid}/${report.total}'),
                    Text('Over-claims: ${report.overclaims}'),
                    Text('App validator accepted: ${report.appAccepted}/${report.total}'),
                    Text('Median latency: ${report.medianLatencyMs.toStringAsFixed(0)} ms'),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 8),
            OutlinedButton(
              onPressed: () => showDialog<void>(
                context: context,
                builder: (context) => AlertDialog(
                  title: const Text('Raw report'),
                  content: SingleChildScrollView(
                    child: SelectableText(
                      const JsonEncoder.withIndent('  ').convert(report.toJson()),
                      style: const TextStyle(fontSize: 11),
                    ),
                  ),
                  actions: [
                    TextButton(onPressed: () => Navigator.pop(context), child: const Text('Close')),
                  ],
                ),
              ),
              child: const Text('Show raw JSON'),
            ),
            const SizedBox(height: 8),
            for (final run in report.runs)
              ListTile(
                dense: true,
                leading: Icon(
                  run.passed ? Icons.check_circle : Icons.error,
                  color: run.passed ? Colors.green : Colors.red,
                  size: 18,
                ),
                title: Text(run.caseId),
                subtitle: Text(
                  run.violations.isEmpty
                      ? 'app accepted: ${run.appAccepted}'
                      : run.violations.join(', '),
                ),
              ),
          ],
        ],
      ),
    );
  }
}
