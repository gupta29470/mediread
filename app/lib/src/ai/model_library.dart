import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import 'llm_runtime.dart';
import 'model_artifact.dart';
import 'model_service.dart';

/// Where the active model id is persisted. Injected so tests never touch
/// platform preferences.
abstract interface class ActiveModelStore {
  Future<String?> read();
  Future<void> write(String id);
  Future<void> clear();
}

class SharedPreferencesActiveModelStore implements ActiveModelStore {
  SharedPreferencesActiveModelStore(this._preferences);

  static const String key = 'mediread.model.active';

  final SharedPreferences _preferences;

  @override
  Future<String?> read() async => _preferences.getString(key);

  @override
  Future<void> write(String id) => _preferences.setString(key, id);

  @override
  Future<void> clear() => _preferences.remove(key);
}

class InMemoryActiveModelStore implements ActiveModelStore {
  InMemoryActiveModelStore([this.value]);

  String? value;

  @override
  Future<String?> read() async => value;

  @override
  Future<void> write(String id) async => value = id;

  @override
  Future<void> clear() async => value = null;
}

/// The steps a model goes through when it is activated. Exposed so the UI can
/// say what is happening during a load that can take a minute or more.
enum ActivationStage {
  idle,
  checking,
  verifying,
  unloading,
  loading,
  smokeTest,
  restoring,
  ready,
  failed,
}

class ActivationProgress {
  const ActivationProgress({
    this.modelId,
    this.previousModelId,
    this.stage = ActivationStage.idle,
    this.message = '',
    this.startedAt,
    this.errorCode,
  });

  final String? modelId;
  final String? previousModelId;
  final ActivationStage stage;
  final String message;
  final DateTime? startedAt;
  final String? errorCode;

  bool get inProgress => switch (stage) {
        ActivationStage.checking ||
        ActivationStage.verifying ||
        ActivationStage.unloading ||
        ActivationStage.loading ||
        ActivationStage.smokeTest ||
        ActivationStage.restoring =>
          true,
        _ => false,
      };

  String get chipLabel => switch (stage) {
        ActivationStage.checking => 'Checking',
        ActivationStage.verifying => 'Verifying',
        ActivationStage.unloading => 'Preparing',
        ActivationStage.loading => 'Loading',
        ActivationStage.smokeTest => 'Testing',
        ActivationStage.restoring => 'Restoring',
        ActivationStage.ready => 'Active',
        ActivationStage.failed => 'Initialization failed',
        ActivationStage.idle => 'Ready',
      };
}

/// A model is only Ready when it has answered a prompt, not merely when its
/// file exists. The check is injectable so tests stay fast and deterministic.
typedef SmokeCheck = Future<void> Function(OnDeviceModelService service);

Future<void> defaultSmokeCheck(OnDeviceModelService service) async {
  final generation = await service.runtime.generate(
    systemPrompt: 'You are checking that an on-device language model works. '
        'Reply with one short word.',
    userPrompt: 'Reply with the word OK.',
    maxTokens: 8,
    timeout: const Duration(seconds: 120),
  );
  final text = generation.text.trim();
  if (text.isEmpty) {
    throw const LlmFailure('smoke_empty', 'The model returned an empty response.');
  }
  if (!generation.totalMs.isFinite) {
    throw const LlmFailure('smoke_invalid', 'The model reported an invalid response time.');
  }
}

/// Coordinates the artifacts that share the device.
///
/// Only one model is loaded at a time. Download state, installed state and
/// metadata stay per artifact; the active model id is the single shared piece
/// of state, and it is persisted only after a model has loaded and answered a
/// smoke prompt.
class ModelLibrary {
  ModelLibrary({
    required List<OnDeviceModelService> services,
    required this.preferences,
    SmokeCheck? smokeCheck,
    this.verifyIntegrityOnActivate = false,
  })  : services = List<OnDeviceModelService>.unmodifiable(services),
        smokeCheck = smokeCheck ?? defaultSmokeCheck;

  final List<OnDeviceModelService> services;
  final ActiveModelStore preferences;
  final SmokeCheck smokeCheck;

  /// A full SHA-256 pass over a 2.39 GB file is slow, so activation trusts the
  /// checksum recorded at install time by default. Turning this on re-hashes
  /// the file before loading it.
  final bool verifyIntegrityOnActivate;

  final ValueNotifier<String?> activeModelId = ValueNotifier<String?>(null);
  final ValueNotifier<bool> busy = ValueNotifier<bool>(false);

  /// What the current (or most recent) activation is doing.
  final ValueNotifier<ActivationProgress> activation =
      ValueNotifier<ActivationProgress>(const ActivationProgress());

  String? lastError;
  String? lastErrorCode;
  bool _initialized = false;

  List<OnDeviceModelService> get installedServices =>
      services.where((service) => service.isInstalled).toList(growable: false);

  OnDeviceModelService? byId(String? id) {
    if (id == null) return null;
    for (final service in services) {
      if (service.artifact.id == id) return service;
    }
    return null;
  }

  OnDeviceModelService? get active => byId(activeModelId.value);

  ModelArtifact? get activeArtifact => active?.artifact;

  bool get isReady => active?.isReady ?? false;

  /// The runtime exposed to the explanation pipeline. Null unless the active
  /// model is Ready, so a half-initialised or unloading model can never be
  /// used for inference.
  LlmRuntime? get runtime {
    final service = active;
    if (service == null || !service.isReady) return null;
    return service.runtime;
  }

  /// Startup path: detect what is installed, then load the persisted model, or
  /// the compact default for an existing/fresh installation that has one.
  ///
  /// Nothing is downloaded here and no model is activated without a file on
  /// disk, so an existing installation keeps working exactly as before.
  Future<void> initialize() async {
    if (_initialized) return;
    _initialized = true;

    for (final service in services) {
      await service.detect();
    }

    final storedId = await preferences.read();
    final candidates = <OnDeviceModelService>[];
    void add(OnDeviceModelService? service) {
      if (service != null && service.isInstalled && !candidates.contains(service)) {
        candidates.add(service);
      }
    }

    add(byId(storedId));
    add(byId(defaultModelArtifact.id));
    for (final service in services) {
      add(service);
    }

    for (final candidate in candidates) {
      if (await activate(candidate.artifact.id)) return;
    }

    activeModelId.value = null;
    if (storedId != null) await preferences.clear();
  }

  /// Switches to [id].
  ///
  /// Order matters: check the file, release the current engine, load the new
  /// one, prove it answers, and only then persist the new active id. On any
  /// failure the previously working model is reloaded and the persisted id is
  /// left untouched.
  Future<bool> activate(String id) async {
    if (busy.value) {
      _fail('busy', 'A model change is already in progress.');
      return false;
    }
    final next = byId(id);
    if (next == null) {
      _fail('unknown_model', 'Unknown model.');
      return false;
    }
    final previous = active;
    if (previous == next && next.isReady) return true;

    busy.value = true;
    lastError = null;
    lastErrorCode = null;
    activation.value = ActivationProgress(
      modelId: next.artifact.id,
      previousModelId: previous?.artifact.id,
      stage: ActivationStage.checking,
      message: 'Checking ${next.artifact.displayName}…',
      startedAt: DateTime.now(),
    );
    try {
      await next.refresh();
      if (!next.isInstalled && await next.downloads.adoptIfVerified()) {
        await next.refresh();
      }
      if (!next.isInstalled) {
        _stage(
          ActivationStage.failed,
          '${next.artifact.displayName} is not downloaded yet.',
          errorCode: 'not_downloaded',
        );
        _fail('not_downloaded', '${next.artifact.displayName} is not downloaded yet.');
        return false;
      }
      if (verifyIntegrityOnActivate) {
        _stage(
          ActivationStage.verifying,
          'Verifying the ${next.artifact.displayName} checksum…',
        );
        if (!await next.downloads.verifyInstalled()) {
          _stage(
            ActivationStage.failed,
            'The ${next.artifact.displayName} file failed its checksum.',
            errorCode: 'integrity_failed',
          );
          _fail(
            'integrity_failed',
            'The ${next.artifact.displayName} file failed its integrity check. '
            'Delete it and download it again.',
          );
          return false;
        }
      }

      // Release the current engine first: two 0.6B models must never be
      // resident at the same time.
      if (previous != null && previous != next) {
        _stage(
          ActivationStage.unloading,
          'Releasing ${previous.artifact.displayName}…',
        );
        await previous.unload();
      }

      _stage(
        ActivationStage.loading,
        'Loading ${next.artifact.displayName} into memory '
        '(${next.artifact.sizeLabel})…',
      );
      final loaded = await next.load();
      if (!loaded) {
        _stage(
          ActivationStage.failed,
          next.lastError ?? 'Initialisation failed.',
          errorCode: next.lastErrorCode ?? 'init_failed',
        );
        _fail(next.lastErrorCode ?? 'init_failed', next.lastError ?? 'Initialisation failed.');
        await _restore(previous, failed: next);
        return false;
      }

      _stage(ActivationStage.smokeTest, 'Running a test prompt…');
      try {
        await smokeCheck(next);
      } catch (error) {
        await next.unload();
        next.markFailed(
          'smoke_failed',
          'The model loaded but did not answer a test prompt. Try again or download it again.',
        );
        _stage(
          ActivationStage.failed,
          next.lastError!,
          errorCode: 'smoke_failed',
        );
        _fail('smoke_failed', next.lastError!);
        await _restore(previous, failed: next);
        return false;
      }

      _stage(
        ActivationStage.ready,
        '${next.artifact.displayName} is ready',
      );
      activeModelId.value = next.artifact.id;
      await preferences.write(next.artifact.id);
      return true;
    } catch (error) {
      _stage(ActivationStage.failed, error.toString(), errorCode: 'unexpected');
      _fail('unexpected', error.toString());
      return false;
    } finally {
      busy.value = false;
    }
  }

  void _stage(ActivationStage stage, String message, {String? errorCode}) {
    final current = activation.value;
    activation.value = ActivationProgress(
      modelId: current.modelId,
      previousModelId: current.previousModelId,
      stage: stage,
      message: message,
      startedAt: current.startedAt,
      errorCode: errorCode,
    );
  }

  Future<bool> deleteModel(String id) async {
    final service = byId(id);
    if (service == null) {
      _fail('unknown_model', 'Unknown model.');
      return false;
    }
    if (activeModelId.value == id) {
      _fail('active_model', 'Switch to another model before deleting this one.');
      return false;
    }
    await service.deleteModel();
    return true;
  }

  Future<void> _restore(
    OnDeviceModelService? previous, {
    required OnDeviceModelService failed,
  }) async {
    if (previous == null || identical(previous, failed)) {
      // Nothing was active before, or the model that failed is the one we were
      // trying to keep: leave the persisted id alone.
      if (identical(previous, failed)) {
        await failed.unload();
      }
      return;
    }
    _stage(ActivationStage.restoring, 'Restoring ${previous.artifact.displayName}…');
    final restored = await previous.load();
    if (restored) {
      try {
        await smokeCheck(previous);
      } catch (_) {
        await previous.unload();
      }
    }
    // The activation itself still failed; end on a terminal stage so the card
    // does not stay on "Restoring…" for ever.
    _stage(
      ActivationStage.failed,
      failed.lastError ?? 'Initialisation failed.',
      errorCode: failed.lastErrorCode,
    );
  }

  void _fail(String code, String message) {
    lastErrorCode = code;
    lastError = message;
  }

  Future<void> dispose() async {
    for (final service in services) {
      await service.unload();
    }
  }
}

/// Builds the real library: one service per artifact, one shared HTTP client,
/// and the active id in shared preferences.
Future<ModelLibrary> buildModelLibrary({
  http.Client? client,
  LlmRuntime Function(ModelArtifact artifact)? runtimeFactory,
}) async {
  final preferences = await SharedPreferences.getInstance();
  final sharedClient = client ?? http.Client();
  final services = <OnDeviceModelService>[];
  for (final artifact in ModelArtifact.allArtifacts) {
    services.add(await buildModelService(
      artifact: artifact,
      client: sharedClient,
      runtime: runtimeFactory?.call(artifact),
    ));
  }
  return ModelLibrary(
    services: services,
    preferences: SharedPreferencesActiveModelStore(preferences),
  );
}
