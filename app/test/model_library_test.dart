import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:mediread_app/src/ai/llm_runtime.dart';
import 'package:mediread_app/src/ai/model_artifact.dart';
import 'package:mediread_app/src/ai/model_download_manager.dart';
import 'package:mediread_app/src/ai/model_library.dart';
import 'package:mediread_app/src/ai/model_service.dart';

import 'model_fakes.dart';

void main() {
  late Set<String> resident;
  late List<String> smokeCalls;
  late InMemoryActiveModelStore store;

  TestRuntime runtimeFor(String name) => TestRuntime(
        name: name,
        onLoad: (loaded) {
          expect(resident, isEmpty, reason: 'two model runtimes were resident at once');
          resident.add(loaded);
        },
        onUnload: (unloaded) => resident.remove(unloaded),
      );

  TestModel compactModel() => TestModel(
        ModelArtifact.qwen3Compact,
        runtime: runtimeFor(ModelArtifact.qwen3Compact.id),
      );

  TestModel fp32Model() => TestModel(
        ModelArtifact.qwen3Fp32,
        runtime: runtimeFor(ModelArtifact.qwen3Fp32.id),
      );

  ModelLibrary libraryFor(
    TestModel compact,
    TestModel fp32, {
    bool verify = false,
  }) =>
      ModelLibrary(
        services: [compact.service, fp32.service],
        preferences: store,
        verifyIntegrityOnActivate: verify,
        smokeCheck: (service) async {
          smokeCalls.add(service.artifact.id);
          final generation = await service.runtime.generate(
            systemPrompt: 'check',
            userPrompt: 'Reply OK',
            maxTokens: 4,
          );
          if (generation.text.trim().isEmpty) {
            throw const LlmFailure('smoke_empty', 'empty');
          }
        },
      );

  setUp(() {
    resident = <String>{};
    smokeCalls = <String>[];
    store = InMemoryActiveModelStore();
  });

  test('nothing installed: startup loads nothing and leaves no active model', () async {
    final compact = compactModel();
    final fp32 = fp32Model();
    final library = libraryFor(compact, fp32);

    await library.initialize();

    expect(library.activeModelId.value, isNull);
    expect(library.isReady, isFalse);
    expect(library.runtime, isNull);
    expect(compact.runtime.loadCalls, 0);
    expect(fp32.runtime.loadCalls, 0);
    expect(store.value, isNull);
  });

  test('existing installation keeps the compact model active without a download', () async {
    final compact = compactModel()..downloads.markInstalled();
    final fp32 = fp32Model();
    final library = libraryFor(compact, fp32);

    await library.initialize();

    expect(library.activeModelId.value, compact.artifact.id);
    expect(compact.service.status.value, ModelRuntimeStatus.ready);
    expect(compact.runtime.loaded, isTrue);
    expect(fp32.runtime.loadCalls, 0);
    expect(store.value, compact.artifact.id);
    expect(smokeCalls, [compact.artifact.id]);
  });

  test('a persisted FP32 choice wins over the compact default', () async {
    final compact = compactModel()..downloads.markInstalled();
    final fp32 = fp32Model()..downloads.markInstalled();
    store.value = fp32.artifact.id;
    final library = libraryFor(compact, fp32);

    await library.initialize();

    expect(library.activeModelId.value, fp32.artifact.id);
    expect(fp32.runtime.loaded, isTrue);
    expect(compact.runtime.loadCalls, 0);
    expect(resident, {fp32.artifact.id});
  });

  test('a stale persisted id falls back to an installed model', () async {
    final compact = compactModel()..downloads.markInstalled();
    final fp32 = fp32Model();
    store.value = fp32.artifact.id;
    final library = libraryFor(compact, fp32);

    await library.initialize();

    expect(library.activeModelId.value, compact.artifact.id);
    expect(store.value, compact.artifact.id);
  });

  test('switching unloads the old engine before loading the new one', () async {
    final compact = compactModel()..downloads.markInstalled();
    final fp32 = fp32Model()..downloads.markInstalled();
    final library = libraryFor(compact, fp32);
    await library.initialize();
    smokeCalls.clear();

    final ok = await library.activate(fp32.artifact.id);

    expect(ok, isTrue);
    expect(compact.runtime.loaded, isFalse);
    expect(compact.runtime.unloadCalls, greaterThanOrEqualTo(1));
    expect(fp32.runtime.loaded, isTrue);
    expect(library.activeModelId.value, fp32.artifact.id);
    expect(store.value, fp32.artifact.id);
    expect(smokeCalls, [fp32.artifact.id]);
    expect(resident, {fp32.artifact.id});
  });

  test('activation refuses a model that is not downloaded', () async {
    final compact = compactModel()..downloads.markInstalled();
    final fp32 = fp32Model();
    final library = libraryFor(compact, fp32);
    await library.initialize();

    final ok = await library.activate(fp32.artifact.id);

    expect(ok, isFalse);
    expect(library.lastErrorCode, 'not_downloaded');
    expect(fp32.runtime.loadCalls, 0);
    expect(library.activeModelId.value, compact.artifact.id);
    expect(compact.service.status.value, ModelRuntimeStatus.ready);
  });

  test('failed initialisation restores the previous model and keeps it persisted', () async {
    final compact = compactModel()..downloads.markInstalled();
    final fp32 = fp32Model()..downloads.markInstalled();
    fp32.runtime.loadFailure = const LlmFailure('load_failed', 'out of memory');
    final library = libraryFor(compact, fp32);
    await library.initialize();
    smokeCalls.clear();

    final ok = await library.activate(fp32.artifact.id);

    expect(ok, isFalse);
    expect(library.lastErrorCode, 'load_failed');
    expect(library.activeModelId.value, compact.artifact.id);
    expect(store.value, compact.artifact.id);
    expect(compact.service.status.value, ModelRuntimeStatus.ready);
    expect(compact.runtime.loaded, isTrue);
    expect(fp32.service.status.value, ModelRuntimeStatus.failed);
    expect(fp32.runtime.loaded, isFalse);
    expect(resident, {compact.artifact.id});
  });

  test('a model that loads but fails the smoke prompt is never marked active', () async {
    final compact = compactModel()..downloads.markInstalled();
    final fp32 = fp32Model()..downloads.markInstalled();
    fp32.runtime.text = '';
    final library = libraryFor(compact, fp32);
    await library.initialize();

    final ok = await library.activate(fp32.artifact.id);

    expect(ok, isFalse);
    expect(library.lastErrorCode, 'smoke_failed');
    expect(library.activeModelId.value, compact.artifact.id);
    expect(store.value, compact.artifact.id);
    expect(fp32.service.status.value, ModelRuntimeStatus.failed);
    expect(fp32.runtime.loaded, isFalse);
    expect(compact.runtime.loaded, isTrue);
  });

  test('integrity verification blocks a corrupted file when enabled', () async {
    final compact = compactModel()..downloads.markInstalled();
    final fp32 = fp32Model()..downloads.markInstalled();
    fp32.downloads.verifyResult = false;
    final library = libraryFor(compact, fp32, verify: true);
    await library.initialize();

    final ok = await library.activate(fp32.artifact.id);

    expect(ok, isFalse);
    expect(library.lastErrorCode, 'integrity_failed');
    expect(fp32.downloads.verifyCalls, 1);
    expect(fp32.runtime.loadCalls, 0);
    expect(library.activeModelId.value, compact.artifact.id);
  });

  test('the pipeline only sees a runtime while the active model is Ready', () async {
    final compact = compactModel()..downloads.markInstalled();
    final fp32 = fp32Model();
    final library = libraryFor(compact, fp32);
    await library.initialize();
    expect(library.runtime, isNotNull);

    await compact.service.unload();

    expect(library.isReady, isFalse);
    expect(library.runtime, isNull);
  });

  test('deleting an inactive model leaves the active model untouched', () async {
    final compact = compactModel()..downloads.markInstalled();
    final fp32 = fp32Model()..downloads.markInstalled();
    final library = libraryFor(compact, fp32);
    await library.initialize();

    expect(await library.deleteModel(fp32.artifact.id), isTrue);
    expect(fp32.downloads.deleteCalls, 1);
    expect(fp32.downloads.availability, ModelAvailability.notInstalled);
    expect(compact.downloads.availability, ModelAvailability.installed);
    expect(library.activeModelId.value, compact.artifact.id);
    expect(library.isReady, isTrue);
  });

  test('the active model cannot be deleted', () async {
    final compact = compactModel()..downloads.markInstalled();
    final fp32 = fp32Model();
    final library = libraryFor(compact, fp32);
    await library.initialize();

    expect(await library.deleteModel(compact.artifact.id), isFalse);
    expect(library.lastErrorCode, 'active_model');
    expect(compact.downloads.deleteCalls, 0);
    expect(compact.downloads.availability, ModelAvailability.installed);
  });

  test('download and initialisation are separate steps', () async {
    final compact = compactModel();
    final fp32 = fp32Model();
    final library = libraryFor(compact, fp32);
    await library.initialize();

    final outcome = await compact.service.downloadModel(wifiOnly: false);

    expect(outcome, DownloadOutcome.completed);
    expect(compact.downloads.availability, ModelAvailability.installed);
    expect(compact.service.status.value, ModelRuntimeStatus.installed);
    expect(compact.runtime.loadCalls, 0, reason: 'downloaded must not mean initialised');
    expect(library.activeModelId.value, isNull);

    expect(await library.activate(compact.artifact.id), isTrue);
    expect(compact.runtime.loadCalls, 1);
    expect(library.isReady, isTrue);
  });

  test('per-model download state is independent', () async {
    final compact = compactModel()..downloads.markInstalled();
    final fp32 = fp32Model()..downloads.markPartial(123456);

    expect((await compact.service.downloads.state()).isInstalled, isTrue);
    expect((await fp32.service.downloads.state()).availability, ModelAvailability.partial);
    expect((await fp32.service.downloads.state()).bytesOnDisk, 123456);
  });

  test('restart recovery reloads the persisted model', () async {
    final firstRun = libraryFor(compactModel(), fp32Model());
    await firstRun.initialize();
    expect(firstRun.activeModelId.value, isNull);

    final compactAfterRestart = compactModel()..downloads.markInstalled();
    final fp32AfterRestart = fp32Model()..downloads.markInstalled();
    store.value = fp32AfterRestart.artifact.id;
    final secondRun = libraryFor(compactAfterRestart, fp32AfterRestart);
    await secondRun.initialize();

    expect(secondRun.activeModelId.value, fp32AfterRestart.artifact.id);
    expect(fp32AfterRestart.runtime.loaded, isTrue);
    expect(compactAfterRestart.runtime.loadCalls, 0);
  });

  test('pausing keeps the partial file; cancelling removes it', () async {
    final compact = compactModel();
    final fp32 = fp32Model();
    final library = libraryFor(compact, fp32);
    await library.initialize();

    compact.downloads.gate = Completer<void>();
    final download = compact.service.downloadModel(wifiOnly: false);
    await compact.downloads.started.future;
    compact.service.pauseDownload();
    compact.downloads.gate!.complete();
    expect(await download, DownloadOutcome.paused);
    expect(compact.downloads.deleteCalls, 0);

    // A second attempt resumes the existing partial file.
    compact.downloads.gate = null;
    final resumed = await compact.service.downloadModel(wifiOnly: false);
    expect(resumed, DownloadOutcome.completed);
    expect(compact.downloads.downloadCalls, 2);

    fp32.downloads.gate = Completer<void>();
    final other = fp32.service.downloadModel(wifiOnly: false);
    await fp32.downloads.started.future;
    final cancelling = fp32.service.cancelDownload();
    fp32.downloads.gate!.complete();
    await cancelling;
    expect(await other, DownloadOutcome.cancelled);
    expect(fp32.downloads.deleteCalls, 1);
    expect(fp32.service.lastDownloadOutcome, DownloadOutcome.cancelled);
  });

  test('a failed download is reported without marking the model installed', () async {
    final compact = compactModel();
    final fp32 = fp32Model();
    final library = libraryFor(compact, fp32);
    await library.initialize();
    compact.downloads.failCode = 'insufficient_storage';
    compact.downloads.failMessage = 'Need 1.13 GB free';

    final outcome = await compact.service.downloadModel(wifiOnly: false);

    expect(outcome, DownloadOutcome.failed);
    expect(compact.service.lastDownloadError, 'Need 1.13 GB free');
    expect(compact.service.lastDownloadOutcome, DownloadOutcome.failed);
    expect(compact.service.status.value, ModelRuntimeStatus.notInstalled);
    expect(compact.runtime.loadCalls, 0);
  });

  test('a verified model file with lost metadata is adopted at startup', () async {
    final compact = compactModel();
    compact.downloads.availability = ModelAvailability.versionMismatch;
    compact.downloads.bytesOnDisk = compact.artifact.sizeBytes;
    compact.downloads.adoptResult = true;
    final fp32 = fp32Model();
    final library = libraryFor(compact, fp32);

    await library.initialize();

    expect(library.activeModelId.value, compact.artifact.id);
    expect(compact.service.status.value, ModelRuntimeStatus.ready);
    expect(compact.runtime.loaded, isTrue);
  });

  test('a file whose checksum fails is never adopted', () async {
    final compact = compactModel();
    compact.downloads.availability = ModelAvailability.versionMismatch;
    compact.downloads.adoptResult = false;
    final fp32 = fp32Model();
    final library = libraryFor(compact, fp32);

    await library.initialize();

    expect(library.activeModelId.value, isNull);
    expect(compact.service.status.value, ModelRuntimeStatus.notInstalled);
    expect(compact.runtime.loadCalls, 0);
  });

  test('activation reports its stages in order', () async {
    final compact = compactModel()..downloads.markInstalled();
    final fp32 = fp32Model()..downloads.markInstalled();
    final library = libraryFor(compact, fp32);
    await library.initialize();

    final stages = <ActivationStage>[];
    library.activation.addListener(() => stages.add(library.activation.value.stage));

    expect(await library.activate(fp32.artifact.id), isTrue);

    expect(
      stages,
      containsAllInOrder([
        ActivationStage.checking,
        ActivationStage.unloading,
        ActivationStage.loading,
        ActivationStage.smokeTest,
        ActivationStage.ready,
      ]),
    );
    expect(library.activation.value.message, 'Medi Super is ready');
    expect(library.activation.value.inProgress, isFalse);
  });

  test('closed-loop: a failed activation ends on failed, not restoring', () async {
    final compact = compactModel()..downloads.markInstalled();
    final fp32 = fp32Model()..downloads.markInstalled();
    fp32.runtime.loadFailure = const LlmFailure('load_failed', 'out of memory');
    final library = libraryFor(compact, fp32);
    await library.initialize();

    final stages = <ActivationStage>[];
    library.activation.addListener(() => stages.add(library.activation.value.stage));

    expect(await library.activate(fp32.artifact.id), isFalse);

    expect(
      stages,
      containsAllInOrder([
        ActivationStage.checking,
        ActivationStage.unloading,
        ActivationStage.loading,
        ActivationStage.failed,
        ActivationStage.restoring,
      ]),
    );
    expect(library.activation.value.stage, ActivationStage.failed);
    expect(library.activation.value.inProgress, isFalse);
    expect(library.isReady, isTrue, reason: 'the previous model is restored');
  });
}
