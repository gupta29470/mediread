import 'dart:async';
import 'dart:io';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'llm_runtime.dart';
import 'litert_lm_runtime.dart';
import 'model_artifact.dart';
import 'model_download_manager.dart';

class AndroidStorageProbe implements StorageProbe {
  static const MethodChannel _channel = MethodChannel('app.mediread/litertlm');

  @override
  Future<int> freeBytes() async {
    final value = await _channel.invokeMethod<int>('freeBytes');
    return value ?? 0;
  }
}

class ConnectivityWifiProbe implements WifiProbe {
  @override
  Future<bool> isWifi() async {
    final results = await Connectivity().checkConnectivity();
    return results.contains(ConnectivityResult.wifi) ||
        results.contains(ConnectivityResult.ethernet);
  }
}

enum ModelRuntimeStatus { detecting, notInstalled, installed, loading, ready, failed }

/// How a download attempt ended. A paused download keeps its `.part` file and
/// can be resumed; a cancelled one removes it.
enum DownloadOutcome { completed, paused, cancelled, failed }

/// Owns one artifact's lifecycle: installed state, download, load, unload,
/// delete. There is one instance per [ModelArtifact]; [ModelLibrary] coordinates
/// them so that only one model is loaded at a time.
class OnDeviceModelService {
  OnDeviceModelService({
    required this.artifact,
    required this.downloads,
    required this.runtime,
  });

  final ModelArtifact artifact;
  final ModelDownloadManager downloads;
  final LlmRuntime runtime;

  final ValueNotifier<ModelRuntimeStatus> status =
      ValueNotifier<ModelRuntimeStatus>(ModelRuntimeStatus.detecting);
  final ValueNotifier<DownloadProgress> downloadProgress =
      ValueNotifier<DownloadProgress>(const DownloadProgress(received: 0, total: 1));

  String? lastError;
  String? lastErrorCode;
  String? lastDownloadError;
  DownloadOutcome? lastDownloadOutcome;

  bool _cancelRequested = false;
  bool _pauseRequested = false;
  Future<DownloadOutcome>? _activeDownload;
  Future<bool>? _activeLoad;
  bool _installed = false;

  bool get isInstalled => _installed;
  bool get isReady => status.value == ModelRuntimeStatus.ready;
  bool get isDownloading => _activeDownload != null;
  bool get isPaused => lastDownloadOutcome == DownloadOutcome.paused;

  /// Detects what is on disk without loading anything.
  Future<void> detect() async {
    status.value = ModelRuntimeStatus.detecting;
    await refresh(force: true);
    if (!_installed && await downloads.adoptIfVerified()) {
      _installed = true;
      status.value = ModelRuntimeStatus.installed;
    }
  }

  Future<void> refresh({bool force = false}) async {
    final state = await downloads.state();
    _installed = state.isInstalled;
    if (!force &&
        (status.value == ModelRuntimeStatus.ready ||
            status.value == ModelRuntimeStatus.loading)) {
      return;
    }
    status.value = state.isInstalled
        ? ModelRuntimeStatus.installed
        : ModelRuntimeStatus.notInstalled;
  }

  /// Pauses a running download. The partial file is kept for resume.
  void pauseDownload() {
    _pauseRequested = true;
    _cancelRequested = false;
    downloads.cancel();
  }

  /// Cancels a running download and removes the partial file.
  Future<void> cancelDownload() async {
    final running = _activeDownload;
    if (running == null) {
      await downloads.delete();
      lastDownloadOutcome = DownloadOutcome.cancelled;
      await refresh(force: true);
      return;
    }
    _cancelRequested = true;
    _pauseRequested = false;
    downloads.cancel();
    try {
      await running;
    } catch (_) {
      // The outcome is recorded by the download loop.
    }
    await downloads.delete();
    lastDownloadOutcome = DownloadOutcome.cancelled;
    await refresh(force: true);
  }

  /// Idempotent: a second call while a download is running awaits the same
  /// future instead of starting a second transfer.
  Future<DownloadOutcome> downloadModel({required bool wifiOnly}) {
    final running = _activeDownload;
    if (running != null) return running;
    final future = _runDownload(wifiOnly: wifiOnly);
    _activeDownload = future.whenComplete(() => _activeDownload = null);
    return _activeDownload!;
  }

  Future<DownloadOutcome> _runDownload({required bool wifiOnly}) async {
    lastError = null;
    lastErrorCode = null;
    lastDownloadError = null;
    lastDownloadOutcome = null;
    _cancelRequested = false;
    _pauseRequested = false;
    try {
      await downloads.download(
        wifiOnly: wifiOnly,
        onProgress: (progress) => downloadProgress.value = progress,
        isCancelled: () async => _cancelRequested || _pauseRequested,
      );
      await refresh(force: true);
      lastDownloadOutcome = DownloadOutcome.completed;
      return DownloadOutcome.completed;
    } on DownloadException catch (error) {
      if (error.code == 'cancelled') {
        final outcome = _cancelRequested ? DownloadOutcome.cancelled : DownloadOutcome.paused;
        lastDownloadOutcome = outcome;
        await refresh(force: true);
        return outcome;
      }
      lastDownloadError = error.message;
      lastError = error.message;
      lastErrorCode = error.code;
      lastDownloadOutcome = DownloadOutcome.failed;
      await refresh(force: true);
      return DownloadOutcome.failed;
    }
  }

  Future<bool> load() {
    final running = _activeLoad;
    if (running != null) return running;
    final future = _load().whenComplete(() => _activeLoad = null);
    _activeLoad = future;
    return future;
  }

  Future<bool> _load() async {
    lastError = null;
    lastErrorCode = null;
    final state = await downloads.state();
    if (!state.isInstalled) {
      lastError = 'Model is not installed';
      lastErrorCode = 'not_installed';
      status.value = ModelRuntimeStatus.notInstalled;
      _installed = false;
      return false;
    }
    _installed = true;
    status.value = ModelRuntimeStatus.loading;
    try {
      await runtime.load(downloads.modelFile.path);
      status.value = ModelRuntimeStatus.ready;
      return true;
    } catch (error) {
      // A failed native load can still hold engine resources; release them
      // before another model is attempted.
      try {
        await runtime.unload();
      } catch (_) {
        // best effort
      }
      if (error is LlmFailure) {
        lastError = error.message;
        lastErrorCode = error.code;
      } else {
        lastError = error.toString();
        lastErrorCode = 'load_failed';
      }
      status.value = ModelRuntimeStatus.failed;
      return false;
    }
  }

  /// Records an initialisation failure without touching the runtime (used when
  /// the smoke test rejects a model that did load).
  void markFailed(String code, String message) {
    lastErrorCode = code;
    lastError = message;
    status.value = ModelRuntimeStatus.failed;
  }

  Future<void> unload() async {
    await runtime.unload();
    if (status.value == ModelRuntimeStatus.ready ||
        status.value == ModelRuntimeStatus.failed ||
        status.value == ModelRuntimeStatus.loading) {
      status.value = _installed
          ? ModelRuntimeStatus.installed
          : ModelRuntimeStatus.notInstalled;
    }
  }

  Future<void> deleteModel() async {
    if (isDownloading) await cancelDownload();
    await unload();
    await downloads.delete();
    lastDownloadOutcome = null;
    lastDownloadError = null;
    lastError = null;
    lastErrorCode = null;
    await refresh(force: true);
  }
}

/// Builds the real service for one artifact. The metadata key is per artifact,
/// so two artifacts never share installed state.
Future<OnDeviceModelService> buildModelService({
  ModelArtifact artifact = defaultModelArtifact,
  http.Client? client,
  LlmRuntime? runtime,
  Directory? directory,
}) async {
  final support = await getApplicationSupportDirectory();
  final models = directory ?? Directory('${support.path}/models');
  final prefs = await SharedPreferences.getInstance();
  final key = 'mediread.model.meta.${artifact.id}';
  final downloads = ModelDownloadManager(
    artifact: artifact,
    client: client ?? http.Client(),
    directory: models,
    storage: AndroidStorageProbe(),
    wifi: ConnectivityWifiProbe(),
    metadataStore: JsonMetadataStore(
      () async => prefs.getString(key),
      (value) async => prefs.setString(key, value),
      () async => prefs.remove(key),
    ),
  );
  return OnDeviceModelService(
    artifact: artifact,
    downloads: downloads,
    runtime: runtime ?? LiteRtLmRuntime(),
  );
}
