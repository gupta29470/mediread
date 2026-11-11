import 'dart:async';

import 'package:flutter/material.dart';

import '../ai/model_artifact.dart';
import '../ai/model_download_manager.dart';
import '../ai/model_library.dart';
import '../ai/model_service.dart';
import 'eval_page.dart';
import 'theme.dart';

/// Two-card model chooser.
///
/// Download, installed and initialisation state are per artifact; only the
/// active model id is shared. A downloaded model is not usable until it has
/// been activated, and activation only succeeds after a smoke prompt.
class ModelSetupPage extends StatefulWidget {
  const ModelSetupPage({super.key, required this.library});

  final ModelLibrary library;

  @override
  State<ModelSetupPage> createState() => _ModelSetupPageState();
}

enum _CardStatus {
  notDownloaded,
  downloading,
  paused,
  downloadFailed,
  downloaded,
  initializing,
  active,
  initFailed,
}

class _ModelSetupPageState extends State<ModelSetupPage> {
  final Map<String, ModelState> _states = {};
  int? _freeBytes;
  bool _wifiOnly = true;
  String? _pageError;

  ModelLibrary get _library => widget.library;

  @override
  void initState() {
    super.initState();
    _refresh();
    _refreshFreeSpace();
  }

  Future<void> _refresh() async {
    final states = <String, ModelState>{};
    for (final service in _library.services) {
      states[service.artifact.id] = await service.downloads.state();
    }
    if (!mounted) return;
    setState(() {
      _states
        ..clear()
        ..addAll(states);
    });
  }

  Future<void> _refreshFreeSpace() async {
    if (_library.services.isEmpty) return;
    final free = await _library.services.first.downloads.storage.freeBytes();
    if (mounted) setState(() => _freeBytes = free);
  }

  bool _insufficient(ModelArtifact artifact) =>
      _freeBytes != null && _freeBytes! < artifact.requiredFreeBytes;

  Future<void> _download(OnDeviceModelService service) async {
    final artifact = service.artifact;
    final consent = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('Download ${artifact.cardTitle}?'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'MediRead will download ${artifact.sizeLabel} once. The model runs entirely '
              'on this device; your reports are never uploaded.',
              style: const TextStyle(height: 1.45),
            ),
            if (artifact.sizeBytes >= 1000000000) ...[
              const SizedBox(height: 12),
              Container(
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: Clinical.alertBg,
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Text(
                  'This is a large download: approximately ${artifact.sizeLabel} of storage '
                  'and a stable internet connection are required.',
                  style: const TextStyle(
                    color: Clinical.alertFg,
                    fontSize: 12.5,
                    height: 1.4,
                  ),
                ),
              ),
            ],
            if (_insufficient(artifact)) ...[
              const SizedBox(height: 12),
              Text(
                'There is not enough free storage for this model right now.',
                style: TextStyle(
                  color: Theme.of(context).colorScheme.error,
                  fontSize: 12.5,
                ),
              ),
            ],
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: _insufficient(artifact)
                ? null
                : () => Navigator.pop(context, true),
            child: const Text('Download'),
          ),
        ],
      ),
    );
    if (consent != true || !mounted) return;
    await _runDownload(service);
  }

  /// Resume/retry continues the existing `.part` file, so consent is not asked
  /// again for a download the user already approved.
  Future<void> _resume(OnDeviceModelService service) => _runDownload(service);

  Future<void> _runDownload(OnDeviceModelService service) async {
    setState(() => _pageError = null);
    final outcome = await service.downloadModel(wifiOnly: _wifiOnly);
    if (!mounted) return;
    await _refresh();
    await _refreshFreeSpace();
    if (!mounted) return;
    if (outcome == DownloadOutcome.failed) {
      setState(
        () => _pageError = service.lastDownloadError ?? 'Download failed.',
      );
    }
  }

  Future<void> _activate(OnDeviceModelService service) async {
    setState(() => _pageError = null);
    final ok = await _library.activate(service.artifact.id);
    if (!mounted) return;
    await _refresh();
    if (!mounted) return;
    if (!ok) {
      setState(
        () =>
            _pageError = _library.lastError ?? 'Could not activate this model.',
      );
    } else {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('${service.artifact.displayName} is now active'),
        ),
      );
    }
  }

  Future<void> _delete(OnDeviceModelService service) async {
    final artifact = service.artifact;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('Delete ${artifact.displayName}?'),
        content: Text(
          'The ${artifact.sizeLabel} file will be removed from this device. '
          'You will need to download it again to use it.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Delete'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    final ok = await _library.deleteModel(artifact.id);
    if (!mounted) return;
    await _refresh();
    await _refreshFreeSpace();
    if (!mounted) return;
    if (!ok) {
      setState(
        () => _pageError = _library.lastError ?? 'Could not delete this model.',
      );
    }
  }

  Future<void> _cancelDownload(OnDeviceModelService service) async {
    await service.cancelDownload();
    if (!mounted) return;
    await _refresh();
    await _refreshFreeSpace();
  }

  _CardStatus _statusFor(
    OnDeviceModelService service,
    String? activeId,
    ActivationProgress activation,
  ) {
    final status = service.status.value;
    final artifactId = service.artifact.id;
    final state = _states[artifactId];
    if (activation.modelId == artifactId && activation.inProgress) {
      return _CardStatus.initializing;
    }
    if (status == ModelRuntimeStatus.loading) return _CardStatus.initializing;
    if (activeId == artifactId && status == ModelRuntimeStatus.ready) {
      return _CardStatus.active;
    }
    if (status == ModelRuntimeStatus.failed) return _CardStatus.initFailed;
    if (service.isDownloading) return _CardStatus.downloading;
    if (service.lastDownloadOutcome == DownloadOutcome.failed) {
      return _CardStatus.downloadFailed;
    }
    if (service.lastDownloadOutcome == DownloadOutcome.paused ||
        state?.availability == ModelAvailability.partial) {
      return _CardStatus.paused;
    }
    if (state?.isInstalled ?? false) return _CardStatus.downloaded;
    return _CardStatus.notDownloaded;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('On-device AI')),
      body: ListenableBuilder(
        listenable: Listenable.merge([
          _library.activeModelId,
          _library.activation,
          _library.busy,
          for (final service in _library.services) service.status,
        ]),
        builder: (context, _) {
          final activeId = _library.activeModelId.value;
          final activation = _library.activation.value;
          final busy = _library.busy.value;
          return ListView(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 28),
            children: [
              const Text(
                'Choose the AI model that explains your reports.',
                style: TextStyle(
                  fontSize: 20,
                  fontWeight: FontWeight.w700,
                  letterSpacing: -0.3,
                ),
              ),
              const SizedBox(height: 6),
              const Text(
                'Only one model runs at a time. Download either one, or both, and switch '
                'whenever you like.',
                style: TextStyle(
                  color: Clinical.muted,
                  fontSize: 12.5,
                  height: 1.4,
                ),
              ),
              const SizedBox(height: 14),
              if (_freeBytes != null)
                Row(
                  children: [
                    const Icon(
                      Icons.sd_storage_outlined,
                      size: 14,
                      color: Clinical.muted,
                    ),
                    const SizedBox(width: 5),
                    Text(
                      'Free storage: ${(_freeBytes! / 1e9).toStringAsFixed(2)} GB',
                      style: const TextStyle(
                        color: Clinical.muted,
                        fontSize: 11.5,
                      ),
                    ),
                  ],
                ),
              const SizedBox(height: 8),
              Container(
                decoration: Clinical.card(),
                child: Material(
                  type: MaterialType.transparency,
                  child: SwitchListTile(
                    value: _wifiOnly,
                    onChanged: (value) => setState(() => _wifiOnly = value),
                    title: const Text('Download over Wi-Fi only'),
                    subtitle: const Text(
                      'A large model should not be downloaded over mobile data.',
                      style: TextStyle(color: Clinical.muted, fontSize: 11.5),
                    ),
                  ),
                ),
              ),
              const SizedBox(height: 14),
              for (final service in _library.services) ...[
                _ModelCard(
                  service: service,
                  activeId: activeId,
                  state: _states[service.artifact.id],
                  status: _statusFor(service, activeId, activation),
                  activation: activation.modelId == service.artifact.id
                      ? activation
                      : null,
                  busy: busy,
                  freeBytes: _freeBytes,
                  onDownload: () => _download(service),
                  onResume: () => _resume(service),
                  onActivate: () => _activate(service),
                  onDelete: () => _delete(service),
                  onPause: service.pauseDownload,
                  onCancel: () => _cancelDownload(service),
                ),
                const SizedBox(height: 14),
              ],
              if (_pageError != null)
                Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: Clinical.criticalBg,
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Icon(
                        Icons.error_outline,
                        size: 16,
                        color: Clinical.criticalFg,
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          _pageError!,
                          style: const TextStyle(
                            color: Clinical.criticalFg,
                            fontSize: 12.5,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              if (_library.isReady) ...[
                const SizedBox(height: 8),
                TextButton.icon(
                  onPressed: () => Navigator.of(context).push(
                    MaterialPageRoute<void>(
                      builder: (_) => EvalPage(service: _library.active!),
                    ),
                  ),
                  icon: const Icon(Icons.science_outlined, size: 18),
                  label: const Text('Developer: run the 21-case evaluation'),
                ),
              ],
            ],
          );
        },
      ),
    );
  }
}

class _ModelCard extends StatelessWidget {
  const _ModelCard({
    required this.service,
    required this.activeId,
    required this.state,
    required this.status,
    required this.activation,
    required this.busy,
    required this.freeBytes,
    required this.onDownload,
    required this.onResume,
    required this.onActivate,
    required this.onDelete,
    required this.onPause,
    required this.onCancel,
  });

  final OnDeviceModelService service;
  final String? activeId;
  final ModelState? state;
  final _CardStatus status;
  final ActivationProgress? activation;
  final bool busy;
  final int? freeBytes;
  final VoidCallback onDownload;
  final VoidCallback onResume;
  final VoidCallback onActivate;
  final VoidCallback onDelete;
  final VoidCallback onPause;
  final VoidCallback onCancel;

  ModelArtifact get artifact => service.artifact;

  bool get isActive => activeId == artifact.id;

  @override
  Widget build(BuildContext context) {
    final statusStyle = _style(status);
    final statusLabel = status == _CardStatus.initializing && activation != null
        ? activation!.chipLabel
        : statusStyle.label;
    final insufficient =
        freeBytes != null && freeBytes! < artifact.requiredFreeBytes;
    return Container(
      key: Key('model-card-${artifact.id}'),
      padding: const EdgeInsets.fromLTRB(16, 14, 16, 8),
      decoration: BoxDecoration(
        color: isActive ? Clinical.tealWash : Clinical.surface,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(
          color: isActive ? Clinical.primary : Clinical.border,
          width: isActive ? 1.8 : 1,
        ),
        boxShadow: const [
          BoxShadow(
            color: Color(0x0A0F172A),
            blurRadius: 3,
            offset: Offset(0, 1),
          ),
          BoxShadow(
            color: Color(0x080F172A),
            blurRadius: 16,
            offset: Offset(0, 6),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      artifact.cardTitle,
                      style: const TextStyle(
                        fontSize: 16.5,
                        fontWeight: FontWeight.w700,
                        letterSpacing: -0.2,
                      ),
                    ),
                    if (artifact.modelCredit.isNotEmpty) ...[
                      const SizedBox(height: 2),
                      Text(
                        artifact.modelCredit,
                        key: Key('model-credit-${artifact.id}'),
                        style: const TextStyle(
                          color: Clinical.muted,
                          fontSize: 10.5,
                        ),
                      ),
                    ],
                    const SizedBox(height: 3),
                    Text(
                      '${artifact.approxSizeLabel} · version ${artifact.version}',
                      style: const TextStyle(
                        color: Clinical.muted,
                        fontSize: 11.5,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              StatusPill(
                label: statusLabel,
                bg: statusStyle.bg,
                fg: statusStyle.fg,
              ),
            ],
          ),
          const SizedBox(height: 10),
          Text(
            artifact.description,
            style: const TextStyle(
              color: Clinical.inkSecondary,
              fontSize: 13,
              height: 1.45,
            ),
          ),
          if (isActive) ...[
            const SizedBox(height: 8),
            Row(
              children: const [
                Icon(
                  Icons.verified_outlined,
                  size: 14,
                  color: Clinical.normalFg,
                ),
                SizedBox(width: 5),
                Expanded(
                  child: Text(
                    'Active model · checksum verified at install · test prompt answered',
                    style: TextStyle(color: Clinical.normalFg, fontSize: 11.5),
                  ),
                ),
              ],
            ),
          ],
          const SizedBox(height: 10),
          _body(context, insufficient),
          const SizedBox(height: 4),
          _actions(insufficient),
          Material(
            type: MaterialType.transparency,
            child: Theme(
              data: Theme.of(context)
                  .copyWith(dividerColor: Colors.transparent),
              child: ExpansionTile(
                key: Key('technical-${artifact.id}'),
                tilePadding: EdgeInsets.zero,
                childrenPadding: const EdgeInsets.only(bottom: 8),
                title: const Text(
                  'Technical details',
                  style: TextStyle(
                    fontSize: 12.5,
                    color: Clinical.muted,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                children: [
                  _techRow('Model ID', artifact.id),
                  _techRow('File', artifact.fileName),
                  _techRow('Size', '${artifact.sizeBytes} bytes'),
                  _techRow('SHA-256', artifact.sha256, selectable: true),
                  for (final digest in artifact.alternateSha256)
                    _techRow('Alt SHA-256', digest, selectable: true),
                  _techRow('Base model', artifact.modelName),
                  _techRow('Runtime', artifact.technicalDetails),
                  _techRow('License', artifact.license),
                  _techRow(
                    'Version',
                    '${artifact.version} · ${artifact.revision}',
                  ),
                  _techRow('Source', Uri.parse(artifact.url).host),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _body(BuildContext context, bool insufficient) {
    switch (status) {
      case _CardStatus.downloading:
        return ValueListenableBuilder<DownloadProgress>(
          valueListenable: service.downloadProgress,
          builder: (context, progress, _) {
            final percent = (progress.fraction * 100).toStringAsFixed(1);
            return Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                ClipRRect(
                  borderRadius: BorderRadius.circular(999),
                  child: LinearProgressIndicator(
                    value: progress.fraction,
                    minHeight: 6,
                  ),
                ),
                const SizedBox(height: 8),
                Row(
                  children: [
                    SizedBox(
                      width: 56,
                      child: Text(
                        '$percent%',
                        style: const TextStyle(
                          fontWeight: FontWeight.w600,
                          fontSize: 13,
                        ),
                      ),
                    ),
                    Text(
                      '${(progress.received / 1e9).toStringAsFixed(2)} of '
                      '${(progress.total / 1e9).toStringAsFixed(2)} GB',
                      style: const TextStyle(
                        color: Clinical.muted,
                        fontSize: 12,
                      ),
                    ),
                    const Spacer(),
                    if (progress.restarting)
                      const Text(
                        'restarting…',
                        style: TextStyle(color: Clinical.muted, fontSize: 11),
                      ),
                  ],
                ),
              ],
            );
          },
        );
      case _CardStatus.initializing:
        if (activation != null) {
          return _ActivationPanel(progress: activation!);
        }
        return const Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            LinearProgressIndicator(minHeight: 6),
            SizedBox(height: 8),
            Text(
              'Loading the model into memory and running a test prompt…',
              style: TextStyle(color: Clinical.muted, fontSize: 12),
            ),
          ],
        );
      case _CardStatus.paused:
        return _note(
          'Download paused at ${_partialLabel()}.',
          'Resume to continue where it stopped; the partial file is kept.',
        );
      case _CardStatus.downloadFailed:
        return _note(
          service.lastDownloadError ?? 'The download did not finish.',
          'Retry to resume from the bytes already on disk.',
          error: true,
        );
      case _CardStatus.initFailed:
        return _note(
          service.lastError ?? 'The model could not be initialised.',
          'It is not marked active. Try again, or use the other model.',
          error: true,
        );
      case _CardStatus.downloaded:
        return _note(
          insufficient ? 'Not enough free storage to activate this model.' : 'Downloaded and verified. Activate it to use it for explanations.',
          null,
          error: insufficient,
        );
      case _CardStatus.active:
        return const SizedBox.shrink();
      case _CardStatus.notDownloaded:
        return _note(
          insufficient
              ? 'Not enough free storage: about ${artifact.sizeLabel} is needed.'
              : 'Download once to use this model on this device.',
          'Nothing is uploaded; the model runs offline after download.',
          error: insufficient,
        );
    }
  }

  String _partialLabel() {
    final bytes = state?.bytesOnDisk ?? 0;
    final fraction = artifact.sizeBytes <= 0 ? 0.0 : bytes / artifact.sizeBytes;
    return '${(fraction * 100).clamp(0, 100).toStringAsFixed(0)}% '
        '(${(bytes / 1e9).toStringAsFixed(2)} GB)';
  }

  Widget _note(String text, String? secondary, {bool error = false}) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            text,
            style: TextStyle(
              color: error ? Clinical.criticalFg : Clinical.inkSecondary,
              fontSize: 12.5,
              height: 1.4,
            ),
          ),
          if (secondary != null)
            Text(
              secondary,
              style: const TextStyle(
                color: Clinical.muted,
                fontSize: 11.5,
                height: 1.4,
              ),
            ),
        ],
      ),
    );
  }

  Widget _actions(bool insufficient) {
    final children = <Widget>[];
    switch (status) {
      case _CardStatus.notDownloaded:
        children.add(
          FilledButton(
            key: Key('download-${artifact.id}'),
            onPressed: insufficient ? null : onDownload,
            child: Text('Download (${artifact.sizeLabel})'),
          ),
        );
        break;
      case _CardStatus.downloading:
        children.add(
          OutlinedButton(
            key: Key('pause-${artifact.id}'),
            onPressed: onPause,
            child: const Text('Pause'),
          ),
        );
        children.add(
          TextButton(
            key: Key('cancel-download-${artifact.id}'),
            onPressed: onCancel,
            child: const Text('Cancel'),
          ),
        );
        break;
      case _CardStatus.paused:
      case _CardStatus.downloadFailed:
        children.add(
          FilledButton(
            key: Key('resume-${artifact.id}'),
            onPressed: insufficient ? null : onResume,
            child: const Text('Resume download'),
          ),
        );
        children.add(
          TextButton(
            key: Key('cancel-download-${artifact.id}'),
            onPressed: onCancel,
            child: const Text('Cancel'),
          ),
        );
        break;
      case _CardStatus.downloaded:
        children.add(
          FilledButton(
            key: Key('activate-${artifact.id}'),
            onPressed: onActivate,
            child: const Text('Activate'),
          ),
        );
        children.add(
          OutlinedButton(
            key: Key('delete-${artifact.id}'),
            onPressed: busy ? null : onDelete,
            child: const Text('Delete'),
          ),
        );
        break;
      case _CardStatus.initFailed:
        children.add(
          FilledButton(
            key: Key('retry-${artifact.id}'),
            onPressed: onActivate,
            child: const Text('Try again'),
          ),
        );
        if (!isActive) {
          children.add(
            OutlinedButton(
              key: Key('delete-${artifact.id}'),
              onPressed: onDelete,
              child: const Text('Delete'),
            ),
          );
        }
        break;
      case _CardStatus.initializing:
      case _CardStatus.active:
        break;
    }
    if (children.isEmpty) return const SizedBox(height: 4);
    return Padding(
      padding: const EdgeInsets.only(top: 2, bottom: 4),
      child: Wrap(
        spacing: 8,
        runSpacing: 4,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: children,
      ),
    );
  }

  Widget _techRow(String label, String value, {bool selectable = false}) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 84,
            child: Text(
              label,
              style: const TextStyle(color: Clinical.muted, fontSize: 11.5),
            ),
          ),
          Expanded(
            child: selectable
                ? SelectableText(
                    value,
                    style: const TextStyle(
                      fontSize: 11,
                      fontFamily: 'monospace',
                      color: Clinical.inkSecondary,
                    ),
                  )
                : Text(
                    value,
                    style: const TextStyle(
                      fontSize: 11.5,
                      color: Clinical.inkSecondary,
                    ),
                  ),
          ),
        ],
      ),
    );
  }
}

/// Shows the live activation state: stage, what is happening, and how long it
/// has been running. The ticker only exists while this panel is on screen.
class _ActivationPanel extends StatefulWidget {
  const _ActivationPanel({required this.progress});

  final ActivationProgress progress;

  @override
  State<_ActivationPanel> createState() => _ActivationPanelState();
}

class _ActivationPanelState extends State<_ActivationPanel> {
  Timer? _ticker;

  @override
  void initState() {
    super.initState();
    _ticker = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) setState(() {});
    });
  }

  @override
  void dispose() {
    _ticker?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final started = widget.progress.startedAt;
    final elapsed = started == null
        ? null
        : DateTime.now().difference(started).inSeconds;
    return Column(
      key: const Key('activation-panel'),
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        ClipRRect(
          borderRadius: BorderRadius.circular(999),
          child: const LinearProgressIndicator(minHeight: 6),
        ),
        const SizedBox(height: 8),
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              child: Text(
                widget.progress.message,
                style: const TextStyle(
                  color: Clinical.inkSecondary,
                  fontSize: 12.5,
                  height: 1.4,
                ),
              ),
            ),
            if (elapsed != null)
              Padding(
                padding: const EdgeInsets.only(left: 8),
                child: Text(
                  '${elapsed}s',
                  key: const Key('activation-elapsed'),
                  style: const TextStyle(color: Clinical.muted, fontSize: 11.5),
                ),
              ),
          ],
        ),
        const SizedBox(height: 2),
        const Text(
          'One model is loaded at a time. Keep MediRead open until this finishes.',
          style: TextStyle(color: Clinical.muted, fontSize: 11, height: 1.4),
        ),
      ],
    );
  }
}

class _StatusStyle {
  const _StatusStyle(this.label, this.bg, this.fg);

  final String label;
  final Color bg;
  final Color fg;
}

_StatusStyle _style(_CardStatus status) => switch (status) {
  _CardStatus.notDownloaded => const _StatusStyle(
    'Not downloaded',
    Clinical.well,
    Clinical.muted,
  ),
  _CardStatus.downloading => const _StatusStyle(
    'Downloading',
    Clinical.infoBg,
    Clinical.infoFg,
  ),
  _CardStatus.paused => const _StatusStyle(
    'Paused',
    Clinical.alertBg,
    Clinical.alertFg,
  ),
  _CardStatus.downloadFailed => const _StatusStyle(
    'Download failed',
    Clinical.criticalBg,
    Clinical.criticalFg,
  ),
  _CardStatus.downloaded => const _StatusStyle(
    'Downloaded',
    Clinical.tealWash,
    Clinical.primaryDark,
  ),
  _CardStatus.initializing => const _StatusStyle(
    'Initializing',
    Clinical.infoBg,
    Clinical.infoFg,
  ),
  _CardStatus.active => const _StatusStyle(
    'Active',
    Clinical.normalBg,
    Clinical.normalFg,
  ),
  _CardStatus.initFailed => const _StatusStyle(
    'Initialization failed',
    Clinical.criticalBg,
    Clinical.criticalFg,
  ),
};
