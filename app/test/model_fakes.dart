import 'dart:async';
import 'dart:io';

import 'package:http/http.dart' as http;
import 'package:mediread_app/src/ai/llm_runtime.dart';
import 'package:mediread_app/src/ai/model_artifact.dart';
import 'package:mediread_app/src/ai/model_download_manager.dart';
import 'package:mediread_app/src/ai/model_service.dart';

/// Runtime double that records exactly which engine is resident.
class TestRuntime implements LlmRuntime {
  TestRuntime({
    this.name = 'test',
    this.text = 'OK',
    this.loadFailure,
    this.generateFailure,
    this.generationDelay = Duration.zero,
    this.loadDelay = Duration.zero,
    this.onLoad,
    this.onUnload,
  });

  final String name;
  String text;
  LlmFailure? loadFailure;
  LlmFailure? generateFailure;
  Duration generationDelay;
  Duration loadDelay;
  final void Function(String name)? onLoad;
  final void Function(String name)? onUnload;

  bool loaded = false;
  int loadCalls = 0;
  int unloadCalls = 0;
  int generateCalls = 0;
  final List<String> prompts = <String>[];

  @override
  String get runtimeName => 'test-runtime';

  @override
  Future<void> load(String modelPath, {String backend = 'auto'}) async {
    loadCalls++;
    if (loadDelay > Duration.zero) {
      await Future<void>.delayed(loadDelay);
    }
    if (loadFailure != null) throw loadFailure!;
    loaded = true;
    onLoad?.call(name);
  }

  @override
  Future<LlmGeneration> generate({
    required String systemPrompt,
    required String userPrompt,
    int maxTokens = 512,
    Duration timeout = const Duration(seconds: 90),
  }) async {
    generateCalls++;
    prompts.add(userPrompt);
    if (generationDelay > Duration.zero) {
      await Future<void>.delayed(generationDelay);
    }
    if (generateFailure != null) throw generateFailure!;
    return LlmGeneration(text: text, totalMs: 7);
  }

  @override
  Future<void> unload() async {
    unloadCalls++;
    if (loaded) onUnload?.call(name);
    loaded = false;
  }

  @override
  Future<bool> isLoaded() async => loaded;
}

class FakeStorageProbe implements StorageProbe {
  FakeStorageProbe([this.free = 8388608000]);

  int free;

  @override
  Future<int> freeBytes() async => free;
}

class FakeWifiProbe implements WifiProbe {
  FakeWifiProbe([this.connected = true]);

  bool connected;

  @override
  Future<bool> isWifi() async => connected;
}

/// Download manager double: never touches the network or a 2.4 GB file, but
/// keeps the real manager's public contract and lifecycle.
class FakeDownloads extends ModelDownloadManager {
  FakeDownloads({required ModelArtifact artifact, int free = 8388608000, bool wifi = true})
      : this._(artifact, FakeStorageProbe(free), FakeWifiProbe(wifi));

  FakeDownloads._(ModelArtifact artifact, this.storageProbe, this.wifiProbe)
      : super(
          artifact: artifact,
          client: http.Client(),
          directory: Directory('/tmp/mediread-test/${artifact.id}'),
          storage: storageProbe,
          wifi: wifiProbe,
          metadataStore: InMemoryMetadataStore(),
        );

  final FakeStorageProbe storageProbe;
  final FakeWifiProbe wifiProbe;

  ModelAvailability availability = ModelAvailability.notInstalled;
  int bytesOnDisk = 0;
  bool verifyResult = true;
  bool adoptResult = false;
  String? failCode;
  String? failMessage;

  Completer<void>? gate;
  final Completer<void> started = Completer<void>();

  int downloadCalls = 0;
  int deleteCalls = 0;
  int verifyCalls = 0;

  void markInstalled() {
    availability = ModelAvailability.installed;
    bytesOnDisk = artifact.sizeBytes;
  }

  void markPartial([int? bytes]) {
    availability = ModelAvailability.partial;
    bytesOnDisk = bytes ?? artifact.sizeBytes ~/ 2;
  }

  @override
  Future<ModelState> state() async => ModelState(
        availability: availability,
        bytesOnDisk: bytesOnDisk,
      );

  @override
  Future<void> download({
    required bool wifiOnly,
    required void Function(DownloadProgress progress) onProgress,
    required Future<bool> Function() isCancelled,
  }) async {
    downloadCalls++;
    final total = artifact.sizeBytes;
    if (failCode != null) {
      throw DownloadException(failCode!, failMessage ?? 'simulated failure');
    }
    onProgress(DownloadProgress(received: total ~/ 2, total: total));
    if (!started.isCompleted) started.complete();
    final held = gate;
    if (held != null) await held.future;
    if (await isCancelled()) {
      throw const DownloadException('cancelled', 'Download cancelled');
    }
    markInstalled();
    onProgress(DownloadProgress(received: total, total: total));
  }

  @override
  Future<bool> verifyInstalled() async {
    verifyCalls++;
    return verifyResult;
  }

  @override
  Future<bool> adoptIfVerified() async {
    if (!adoptResult) return false;
    markInstalled();
    return true;
  }

  @override
  Future<void> delete() async {
    deleteCalls++;
    availability = ModelAvailability.notInstalled;
    bytesOnDisk = 0;
    await metadataStore.clear();
  }
}

/// One artifact wired to fakes, mirroring what buildModelService produces on
/// a device.
class TestModel {
  TestModel(
    this.artifact, {
    TestRuntime? runtime,
    int free = 8388608000,
    bool wifi = true,
  })  : runtime = runtime ?? TestRuntime(name: artifact.id),
        downloads = FakeDownloads(artifact: artifact, free: free, wifi: wifi) {
    service = OnDeviceModelService(
      artifact: artifact,
      downloads: downloads,
      runtime: this.runtime,
    );
  }

  final ModelArtifact artifact;
  final TestRuntime runtime;
  final FakeDownloads downloads;
  late final OnDeviceModelService service;
}
