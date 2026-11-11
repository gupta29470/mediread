import 'package:flutter/foundation.dart' show kDebugMode;
import 'package:flutter/material.dart';

import '../ai/model_library.dart';
import '../ai/model_service.dart';
import '../ai/orchestrator.dart';
import '../explanation/explanation_document.dart';
import 'demo_data.dart';
import 'import_actions.dart';
import 'import_page.dart';
import 'model_setup_page.dart';
import 'report_source.dart';
import 'result_card.dart';
import 'theme.dart';

/// The single worked example shown before a report can be imported.
const String kSampleCaseId = 'R03_below_range';

class HomePage extends StatefulWidget {
  const HomePage({
    super.key,
    required this.library,
    this.pickReport,
    this.loadDebug,
    this.loadSample,
    this.loadScanned,
    this.loadHybrid,
    this.pickImage,
    this.pickCamera,
  });

  final ModelLibrary library;

  /// Injectable sources so the picker itself can be faked in widget tests.
  final ReportSource? pickReport;
  final ReportSource? loadDebug;
  final ReportSource? loadSample;
  final ReportSource? loadScanned;
  final ReportSource? loadHybrid;
  final ReportSource? pickImage;
  final ReportSource? pickCamera;

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  late final Future<_HomeData> _data;
  late final ExplanationOrchestrator _orchestrator;
  late final Listenable _modelListenable;

  @override
  void initState() {
    super.initState();
    _modelListenable = Listenable.merge([
      widget.library.activeModelId,
      widget.library.busy,
      widget.library.activation,
      for (final service in widget.library.services) service.status,
    ]);
    _orchestrator = ExplanationOrchestrator(
      runtimeProvider: () => widget.library.runtime,
      modelReady: () => widget.library.isReady,
    );
    widget.library.initialize();
    _data = _load();
  }

  ModelRuntimeStatus _statusOf() {
    if (widget.library.activation.value.inProgress) {
      return ModelRuntimeStatus.loading;
    }
    final active = widget.library.active;
    if (active != null) return active.status.value;
    if (widget.library.services.any(
      (service) => service.status.value == ModelRuntimeStatus.loading,
    )) {
      return ModelRuntimeStatus.loading;
    }
    if (widget.library.services.any(
      (service) => service.status.value == ModelRuntimeStatus.detecting,
    )) {
      return ModelRuntimeStatus.detecting;
    }
    if (widget.library.services.any((service) => service.isInstalled)) {
      return ModelRuntimeStatus.installed;
    }
    return ModelRuntimeStatus.notInstalled;
  }

  Future<_HomeData> _load() async {
    final explanations = await DemoData.loadExplanations();
    final cases = await DemoData.loadCases();
    final sample = cases.firstWhere((c) => c.caseId == kSampleCaseId);
    return _HomeData(explanations[sample.caseId], sample);
  }

  void _open(Widget page) {
    Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => page));
  }

  void _requireModel() {
    _open(ModelSetupPage(library: widget.library));
  }

  /// Pick the report first, then open the results screen with it. There is no
  /// intermediate "choose a report" screen: the three actions act immediately.
  Future<void> _importReport(
    ReportSource source, {
    String sourceLabel = 'that report',
  }) async {
    try {
      final report = await source();
      if (report == null || !mounted) return;
      _open(
        ImportPage(
          orchestrator: _orchestrator,
          modelReady: widget.library.isReady,
          onSetupModel: _requireModel,
          initial: report,
        ),
      );
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Could not open $sourceLabel: $error')),
      );
    }
  }

  void _showHelp() {
    showDialog<void>(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: Clinical.surface,
        title: const Text('About this build'),
        content: const Text(
          'The sample result is a worked example shipped with the app, not your report.\n\n'
          'Report import runs on this device, including scanned and partly scanned '
          'PDFs (on-device OCR). The on-device AI model is optional: it must be '
          'installed first, it only rewrites permitted explanation text, and it never '
          'receives withheld values.',
          style: TextStyle(height: 1.45),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Close'),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        bottom: false,
        child: FutureBuilder<_HomeData>(
          future: _data,
          builder: (context, snapshot) {
            if (!snapshot.hasData) {
              return const Center(child: CircularProgressIndicator());
            }
            return _homeView(snapshot.data!);
          },
        ),
      ),
      bottomNavigationBar: NavigationBar(
        backgroundColor: Clinical.surface,
        indicatorColor: Clinical.tealWash,
        selectedIndex: 0,
        onDestinationSelected: (index) {
          if (index == 1) _open(ModelSetupPage(library: widget.library));
        },
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.home_outlined),
            selectedIcon: Icon(Icons.home),
            label: 'Home',
          ),
          NavigationDestination(
            icon: Icon(Icons.settings_outlined),
            selectedIcon: Icon(Icons.settings),
            label: 'Settings',
          ),
        ],
      ),
    );
  }

  Widget _homeView(_HomeData data) {
    return AnimatedBuilder(
      animation: _modelListenable,
      builder: (context, _) {
        final status = _statusOf();
        final activating = widget.library.activation.value;
        final modelName = activating.inProgress
            ? widget.library.byId(activating.modelId)?.artifact.displayName
            : widget.library.active?.artifact.displayName;
        final ready = status == ModelRuntimeStatus.ready;
        return ListView(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 28),
          children: [
            _Header(
              status: status,
              modelName: modelName,
              onHelp: _showHelp,
              onDebugDevice: kDebugMode
                  ? () => _importReport(widget.loadDebug ?? loadDebugReport)
                  : null,
              onDebugSample: kDebugMode
                  ? () => _importReport(widget.loadSample ?? loadSampleReport)
                  : null,
              onDebugScanned: kDebugMode
                  ? () => _importReport(widget.loadScanned ?? loadScannedReport)
                  : null,
              onDebugHybrid: kDebugMode
                  ? () => _importReport(widget.loadHybrid ?? loadHybridReport)
                  : null,
            ),
            const SizedBox(height: 20),
            const Text(
              'WELCOME',
              style: TextStyle(
                color: Clinical.muted,
                fontSize: 11,
                fontWeight: FontWeight.w600,
                letterSpacing: 1.1,
              ),
            ),
            const SizedBox(height: 2),
            const Text(
              'Understand your lab results',
              style: TextStyle(
                fontSize: 28,
                fontWeight: FontWeight.w700,
                letterSpacing: -0.6,
              ),
            ),
            const SizedBox(height: 14),
            _AiBanner(
              status: status,
              modelName: modelName,
              onTap: _requireModel,
            ),
            const SizedBox(height: 16),
            _HeroCard(
              ready: ready,
              onPdf: () => _importReport(widget.pickReport ?? pickPdfReport),
              onCamera: () => _importReport(
                widget.pickCamera ?? pickCameraPhoto,
                sourceLabel: 'the camera',
              ),
              onGallery: () =>
                  _importReport(widget.pickImage ?? pickGalleryImage),
            ),
            const SizedBox(height: 22),
            const SectionLabel('Sample result'),
            const SizedBox(height: 4),
            const Text(
              'One worked example — not your report.',
              style: TextStyle(color: Clinical.muted, fontSize: 12),
            ),
            const SizedBox(height: 12),
            if (data.sample != null && data.example != null)
              ResultCard(
                result: data.example!,
                orchestrator: _orchestrator,
                modelReady: ready,
                onSetupModel: _requireModel,
              ),
            const SizedBox(height: 14),
            const _HowItWorks(),
          ],
        );
      },
    );
  }
}

class _HomeData {
  _HomeData(this.example, this.sample);

  final ResultExplanation? example;
  final DemoCase? sample;
}

class _Header extends StatelessWidget {
  const _Header({
    required this.status,
    required this.modelName,
    required this.onHelp,
    this.onDebugDevice,
    this.onDebugSample,
    this.onDebugScanned,
    this.onDebugHybrid,
  });

  final ModelRuntimeStatus status;
  final String? modelName;
  final VoidCallback onHelp;
  final VoidCallback? onDebugDevice;
  final VoidCallback? onDebugSample;
  final VoidCallback? onDebugScanned;
  final VoidCallback? onDebugHybrid;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Container(
          width: 38,
          height: 38,
          decoration: BoxDecoration(
            color: Clinical.primary,
            borderRadius: BorderRadius.circular(10),
          ),
          child: const Icon(
            Icons.health_and_safety,
            color: Colors.white,
            size: 22,
          ),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'MediRead',
                style: TextStyle(
                  fontSize: 20,
                  fontWeight: FontWeight.w700,
                  letterSpacing: -0.3,
                ),
              ),
              Row(
                children: [
                  Container(
                    width: 6,
                    height: 6,
                    decoration: BoxDecoration(
                      color: status == ModelRuntimeStatus.ready
                          ? Clinical.normalFg
                          : Clinical.muted,
                      shape: BoxShape.circle,
                    ),
                  ),
                  const SizedBox(width: 5),
                  Flexible(
                    child: Text(
                      switch (status) {
                        ModelRuntimeStatus.detecting =>
                          'Checking for on-device model…',
                        ModelRuntimeStatus.loading =>
                          'Loading ${modelName ?? 'model'}…',
                        ModelRuntimeStatus.ready =>
                          '${modelName ?? 'AI model'} · active',
                        ModelRuntimeStatus.failed =>
                          '${modelName ?? 'AI model'} · load failed',
                        ModelRuntimeStatus.installed =>
                          '${modelName ?? 'AI model'} · installed',
                        ModelRuntimeStatus.notInstalled =>
                          'AI model not installed',
                      },
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        color: Clinical.muted,
                        fontSize: 11.5,
                      ),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
        if (onDebugDevice != null || onDebugSample != null)
          PopupMenuButton<int>(
            tooltip: 'Debug report sources',
            icon: const Icon(Icons.bug_report_outlined),
            onSelected: (value) => switch (value) {
              0 => onDebugDevice?.call(),
              1 => onDebugSample?.call(),
              2 => onDebugScanned?.call(),
              _ => onDebugHybrid?.call(),
            },
            itemBuilder: (context) => const [
              PopupMenuItem(
                value: 0,
                child: Text('Load device report (debug)'),
              ),
              PopupMenuItem(value: 1, child: Text('Load bundled sample PDF')),
              PopupMenuItem(value: 2, child: Text('Load scanned sample (OCR)')),
              PopupMenuItem(value: 3, child: Text('Load hybrid sample (OCR)')),
            ],
          ),
        IconButton(onPressed: onHelp, icon: const Icon(Icons.help_outline)),
      ],
    );
  }
}

class _AiBanner extends StatelessWidget {
  const _AiBanner({
    required this.status,
    required this.modelName,
    required this.onTap,
  });

  final ModelRuntimeStatus status;
  final String? modelName;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final ready = status == ModelRuntimeStatus.ready;
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(16),
      child: Container(
        padding: const EdgeInsets.all(14),
        decoration: Clinical.card(color: Clinical.tealWash),
        child: Row(
          children: [
            Icon(
              ready ? Icons.lock_outline : Icons.download_outlined,
              size: 18,
              color: Clinical.primary,
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    ready
                        ? '${modelName ?? 'On-device AI'} active · 100% local inference'
                        : 'Set up on-device AI to begin',
                    style: const TextStyle(
                      fontWeight: FontWeight.w600,
                      fontSize: 13.5,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    switch (status) {
                      ModelRuntimeStatus.detecting =>
                        'Looking for a downloaded model on this device.',
                      ModelRuntimeStatus.loading =>
                        'Initialising the on-device engine.',
                      ModelRuntimeStatus.ready => 'Nothing leaves this device.',
                      ModelRuntimeStatus.failed =>
                        'Tap to retry or re-download the model.',
                      ModelRuntimeStatus.installed =>
                        'Tap to load it and unlock explanations.',
                      ModelRuntimeStatus.notInstalled => 'The model must be installed before a report can be processed.',
                    },
                    style: const TextStyle(color: Clinical.muted, fontSize: 12),
                  ),
                ],
              ),
            ),
            const Icon(Icons.chevron_right, color: Clinical.muted),
          ],
        ),
      ),
    );
  }
}

class _HeroCard extends StatelessWidget {
  const _HeroCard({
    required this.ready,
    required this.onPdf,
    required this.onCamera,
    required this.onGallery,
  });

  final bool ready;
  final VoidCallback onPdf;
  final VoidCallback onCamera;
  final VoidCallback onGallery;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: Clinical.card(color: Clinical.surface, radius: 24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const StatusPill(
            label: 'ON-DEVICE AI',
            bg: Clinical.infoBg,
            fg: Clinical.infoFg,
          ),
          const SizedBox(height: 12),
          const Text(
            'Add a report.',
            style: TextStyle(
              fontSize: 24,
              fontWeight: FontWeight.w700,
              letterSpacing: -0.5,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            ready
                ? 'Pick a PDF, or take a photo of a printed report. Values, units and printed '
                      'ranges are read on this device.'
                : 'Install the on-device model first to add and explain a report.',
            style: const TextStyle(color: Clinical.inkSecondary, height: 1.4),
          ),
          const SizedBox(height: 16),
          ImportActions(
            enabled: ready,
            onPdf: onPdf,
            onCamera: onCamera,
            onGallery: onGallery,
          ),
        ],
      ),
    );
  }
}

class _HowItWorks extends StatelessWidget {
  const _HowItWorks();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: Clinical.card(color: Clinical.tealWash),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 34,
                height: 34,
                decoration: BoxDecoration(
                  color: Clinical.primary,
                  borderRadius: BorderRadius.circular(10),
                ),
                child: const Icon(
                  Icons.shield_outlined,
                  color: Colors.white,
                  size: 18,
                ),
              ),
              const SizedBox(width: 10),
              const Text(
                'How MediRead works',
                style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
              ),
            ],
          ),
          const SizedBox(height: 8),
          const Text(
            'Your report is parsed on the device. The deterministic engine verifies values, '
            'units and ranges before anything is shown. The AI model only rewrites approved '
            'text — it never calculates and never sees withheld values.',
            style: TextStyle(
              color: Clinical.inkSecondary,
              height: 1.45,
              fontSize: 13,
            ),
          ),
          const SizedBox(height: 10),
          const Row(
            children: [
              Icon(
                Icons.verified_user_outlined,
                size: 14,
                color: Clinical.primary,
              ),
              SizedBox(width: 5),
              Text(
                'Private by architecture',
                style: TextStyle(fontSize: 11.5, color: Clinical.primary),
              ),
              SizedBox(width: 14),
              Icon(Icons.cloud_off_outlined, size: 14, color: Clinical.primary),
              SizedBox(width: 5),
              Text(
                'Fully offline',
                style: TextStyle(fontSize: 11.5, color: Clinical.primary),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
