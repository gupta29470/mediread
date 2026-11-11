import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mediread_app/src/ai/llm_runtime.dart';
import 'package:mediread_app/src/ai/model_artifact.dart';
import 'package:mediread_app/src/ai/model_library.dart';
import 'package:mediread_app/src/ai/model_service.dart';
import 'package:mediread_app/src/ui/model_setup_page.dart';
import 'package:mediread_app/src/ui/theme.dart';

import 'model_fakes.dart';

void main() {
  late Set<String> resident;
  late InMemoryActiveModelStore store;

  TestRuntime runtimeFor(String name) => TestRuntime(
        name: name,
        onLoad: (loaded) => resident.add(loaded),
        onUnload: (unloaded) => resident.remove(unloaded),
      );

  TestModel compactModel({int free = 8388608000}) => TestModel(
        ModelArtifact.qwen3Compact,
        runtime: runtimeFor('compact'),
        free: free,
      );

  TestModel fp32Model({int free = 8388608000}) => TestModel(
        ModelArtifact.qwen3Fp32,
        runtime: runtimeFor('fp32'),
        free: free,
      );

  ModelLibrary libraryFor(TestModel compact, TestModel fp32) => ModelLibrary(
        services: [compact.service, fp32.service],
        preferences: store,
        smokeCheck: (service) async {
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
    store = InMemoryActiveModelStore();
  });

  Future<void> pumpPage(WidgetTester tester, ModelLibrary library) async {
    // A tall surface so both cards are laid out; the real page is a scroll view.
    tester.view.physicalSize = const Size(1200, 3200);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(MaterialApp(
      theme: Clinical.theme(),
      home: ModelSetupPage(library: library),
    ));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 20));
  }

  Finder inCard(ModelArtifact artifact, Finder matching) =>
      find.descendant(of: find.byKey(Key('model-card-${artifact.id}')), matching: matching);

  Future<void> confirmDownload(WidgetTester tester) async {
    await tester.tap(find.widgetWithText(FilledButton, 'Download'));
    await tester.pump();
  }

  testWidgets('both model cards are shown with size and initial state', (tester) async {
    final compact = compactModel();
    final fp32 = fp32Model();
    final library = libraryFor(compact, fp32);

    await pumpPage(tester, library);

    expect(find.text('Medi Lite — Compact AI'), findsOneWidget);
    expect(find.text('Medi Super — Detailed AI'), findsOneWidget);
    expect(find.byKey(Key('model-credit-${compact.artifact.id}')), findsOneWidget);
    expect(find.byKey(Key('model-credit-${fp32.artifact.id}')), findsOneWidget);
    expect(find.text('Powered by Qwen3 0.6B'), findsOneWidget);
    expect(find.text('Powered by Qwen3 0.6B FP32'), findsOneWidget);
    expect(inCard(compact.artifact, find.text('Not downloaded')), findsOneWidget);
    expect(inCard(fp32.artifact, find.text('Not downloaded')), findsOneWidget);
    expect(inCard(compact.artifact, find.textContaining('613.7 MB')), findsWidgets);
    expect(inCard(fp32.artifact, find.textContaining('2.39 GB')), findsWidgets);
    expect(find.text('Download over Wi-Fi only'), findsOneWidget);
  });

  testWidgets('download asks for consent and can be declined', (tester) async {
    final compact = compactModel();
    final fp32 = fp32Model();
    final library = libraryFor(compact, fp32);
    await pumpPage(tester, library);

    await tester.tap(find.byKey(Key('download-${compact.artifact.id}')));
    await tester.pumpAndSettle();
    expect(find.text('Download Medi Lite — Compact AI?'), findsOneWidget);

    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();
    expect(compact.downloads.downloadCalls, 0);
  });

  testWidgets('FP32 download warns about size and storage', (tester) async {
    final compact = compactModel();
    final fp32 = fp32Model();
    final library = libraryFor(compact, fp32);
    await pumpPage(tester, library);

    await tester.tap(find.byKey(Key('download-${fp32.artifact.id}')));
    await tester.pumpAndSettle();

    expect(find.text('Download Medi Super — Detailed AI?'), findsOneWidget);
    final dialog = find.byType(AlertDialog);
    expect(
      find.descendant(of: dialog, matching: find.textContaining('approximately 2.39 GB')),
      findsOneWidget,
    );
    expect(
      find.descendant(of: dialog, matching: find.textContaining('never uploaded')),
      findsOneWidget,
    );
  });

  testWidgets('download shows progress, then pause keeps the partial file', (tester) async {
    final compact = compactModel();
    final fp32 = fp32Model();
    final library = libraryFor(compact, fp32);
    await pumpPage(tester, library);

    compact.downloads.gate = Completer<void>();
    await tester.tap(find.byKey(Key('download-${compact.artifact.id}')));
    await tester.pumpAndSettle();
    await confirmDownload(tester);
    await tester.pump(const Duration(milliseconds: 10));

    expect(find.text('50.0%'), findsOneWidget);
    expect(find.text('0.31 of 0.61 GB'), findsOneWidget);
    expect(find.byKey(Key('pause-${compact.artifact.id}')), findsOneWidget);

    await tester.tap(find.byKey(Key('pause-${compact.artifact.id}')));
    await tester.pump();
    compact.downloads.gate!.complete();
    await tester.pumpAndSettle();

    expect(inCard(compact.artifact, find.text('Paused')), findsOneWidget);
    expect(compact.downloads.deleteCalls, 0, reason: 'pausing must keep the .part file');
  });

  testWidgets('resume completes the download and offers activation', (tester) async {
    final compact = compactModel();
    final fp32 = fp32Model();
    final library = libraryFor(compact, fp32);
    await pumpPage(tester, library);

    compact.downloads.gate = Completer<void>();
    await tester.tap(find.byKey(Key('download-${compact.artifact.id}')));
    await tester.pumpAndSettle();
    await confirmDownload(tester);
    await tester.pump(const Duration(milliseconds: 10));
    await tester.tap(find.byKey(Key('pause-${compact.artifact.id}')));
    await tester.pump();
    compact.downloads.gate!.complete();
    await tester.pumpAndSettle();

    compact.downloads.gate = null;
    await tester.tap(find.byKey(Key('resume-${compact.artifact.id}')));
    await tester.pumpAndSettle();

    expect(inCard(compact.artifact, find.text('Downloaded')), findsOneWidget);
    expect(find.byKey(Key('activate-${compact.artifact.id}')), findsOneWidget);
    expect(compact.service.status.value, ModelRuntimeStatus.installed);
    expect(compact.runtime.loadCalls, 0, reason: 'downloaded is not initialised');
  });

  testWidgets('cancel removes the partial download', (tester) async {
    final compact = compactModel();
    final fp32 = fp32Model();
    final library = libraryFor(compact, fp32);
    await pumpPage(tester, library);

    compact.downloads.gate = Completer<void>();
    await tester.tap(find.byKey(Key('download-${compact.artifact.id}')));
    await tester.pumpAndSettle();
    await confirmDownload(tester);
    await tester.pump(const Duration(milliseconds: 10));

    await tester.tap(find.byKey(Key('cancel-download-${compact.artifact.id}')));
    await tester.pump();
    compact.downloads.gate!.complete();
    await tester.pumpAndSettle();

    expect(compact.downloads.deleteCalls, 1);
    expect(inCard(compact.artifact, find.text('Not downloaded')), findsOneWidget);
  });

  testWidgets('download failure is shown with a retry action', (tester) async {
    final compact = compactModel();
    final fp32 = fp32Model();
    final library = libraryFor(compact, fp32);
    await pumpPage(tester, library);

    compact.downloads.failCode = 'http_500';
    await tester.tap(find.byKey(Key('download-${compact.artifact.id}')));
    await tester.pumpAndSettle();
    await confirmDownload(tester);
    await tester.pumpAndSettle();

    expect(inCard(compact.artifact, find.text('Download failed')), findsOneWidget);
    expect(find.byKey(Key('resume-${compact.artifact.id}')), findsOneWidget);
    expect(find.textContaining('simulated failure'), findsWidgets);
  });

  testWidgets('insufficient storage disables the download and warns', (tester) async {
    const free = 1200000000; // 1.2 GB: enough for compact, too small for FP32
    final compact = compactModel(free: free);
    final fp32 = fp32Model(free: free);
    final library = libraryFor(compact, fp32);
    await pumpPage(tester, library);

    expect(inCard(fp32.artifact, find.textContaining('Not enough free storage')), findsOneWidget);
    final button = tester.widget<FilledButton>(
      find.byKey(Key('download-${fp32.artifact.id}')),
    );
    expect(button.onPressed, isNull);
    final compactButton = tester.widget<FilledButton>(
      find.byKey(Key('download-${compact.artifact.id}')),
    );
    expect(compactButton.onPressed, isNotNull);
  });

  testWidgets('the active model is marked and cannot be deleted', (tester) async {
    final compact = compactModel()..downloads.markInstalled();
    final fp32 = fp32Model();
    final library = libraryFor(compact, fp32);
    await library.initialize();
    await pumpPage(tester, library);

    expect(inCard(compact.artifact, find.text('Active')), findsOneWidget);
    expect(inCard(compact.artifact, find.textContaining('Active model')), findsOneWidget);
    expect(inCard(fp32.artifact, find.text('Not downloaded')), findsOneWidget);
    expect(find.byKey(Key('delete-${compact.artifact.id}')), findsNothing);
  });

  testWidgets('activating a downloaded model switches the active card', (tester) async {
    final compact = compactModel()..downloads.markInstalled();
    final fp32 = fp32Model()..downloads.markInstalled();
    final library = libraryFor(compact, fp32);
    await library.initialize();
    await pumpPage(tester, library);
    expect(inCard(compact.artifact, find.text('Active')), findsOneWidget);

    await tester.tap(find.byKey(Key('activate-${fp32.artifact.id}')));
    await tester.pumpAndSettle();

    expect(inCard(fp32.artifact, find.text('Active')), findsOneWidget);
    expect(inCard(compact.artifact, find.text('Downloaded')), findsOneWidget);
    expect(library.activeModelId.value, fp32.artifact.id);
    expect(store.value, fp32.artifact.id);
    expect(fp32.runtime.loaded, isTrue);
    expect(compact.runtime.loaded, isFalse);
    expect(find.text('Medi Super is now active'), findsOneWidget);
    await tester.pump(const Duration(seconds: 5));
  });

  testWidgets('initialisation failure is shown and the old model is restored', (tester) async {
    final compact = compactModel()..downloads.markInstalled();
    final fp32 = fp32Model()..downloads.markInstalled();
    fp32.runtime.loadFailure = const LlmFailure('load_failed', 'out of memory');
    final library = libraryFor(compact, fp32);
    await library.initialize();
    await pumpPage(tester, library);

    await tester.tap(find.byKey(Key('activate-${fp32.artifact.id}')));
    await tester.pumpAndSettle();

    expect(inCard(fp32.artifact, find.text('Initialization failed')), findsOneWidget);
    expect(find.byKey(Key('retry-${fp32.artifact.id}')), findsOneWidget);
    expect(inCard(compact.artifact, find.text('Active')), findsOneWidget);
    expect(store.value, compact.artifact.id);
    expect(compact.runtime.loaded, isTrue);
  });

  testWidgets('deleting a model requires confirmation', (tester) async {
    final compact = compactModel()..downloads.markInstalled();
    final fp32 = fp32Model()..downloads.markInstalled();
    final library = libraryFor(compact, fp32);
    await library.initialize();
    await pumpPage(tester, library);

    await tester.tap(find.byKey(Key('delete-${fp32.artifact.id}')));
    await tester.pumpAndSettle();
    expect(find.text('Delete Medi Super?'), findsOneWidget);
    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();
    expect(fp32.downloads.deleteCalls, 0);

    await tester.tap(find.byKey(Key('delete-${fp32.artifact.id}')));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Delete'));
    await tester.pumpAndSettle();

    expect(fp32.downloads.deleteCalls, 1);
    expect(inCard(fp32.artifact, find.text('Not downloaded')), findsOneWidget);
  });

  testWidgets('technical details are expandable and carry the pinned checksum', (tester) async {
    final compact = compactModel();
    final fp32 = fp32Model();
    final library = libraryFor(compact, fp32);
    await pumpPage(tester, library);

    expect(find.text('Model ID'), findsNothing);
    await tester.tap(find.byKey(Key('technical-${fp32.artifact.id}')));
    await tester.pumpAndSettle();

    expect(find.text('Model ID'), findsOneWidget);
    expect(find.text(ModelArtifact.qwen3Fp32.id), findsOneWidget);
    expect(find.text(ModelArtifact.qwen3Fp32.sha256), findsOneWidget);
  });

  testWidgets('activation shows live stages, elapsed time and hides the button', (tester) async {
    final compact = compactModel()..downloads.markInstalled();
    final fp32 = fp32Model()..downloads.markInstalled();
    fp32.runtime.loadDelay = const Duration(milliseconds: 600);
    final library = libraryFor(compact, fp32);
    await library.initialize();
    await pumpPage(tester, library);

    await tester.tap(find.byKey(Key('activate-${fp32.artifact.id}')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 250));

    expect(find.byKey(const Key('activation-panel')), findsOneWidget);
    expect(find.textContaining('Loading Medi Super into memory'), findsOneWidget);
    expect(inCard(fp32.artifact, find.text('Loading')), findsOneWidget);
    expect(find.byKey(const Key('activation-elapsed')), findsOneWidget);
    expect(find.byKey(Key('activate-${fp32.artifact.id}')), findsNothing);

    await tester.pump(const Duration(milliseconds: 700));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('activation-panel')), findsNothing);
    expect(inCard(fp32.artifact, find.text('Active')), findsOneWidget);
    await tester.pump(const Duration(seconds: 5));
  });
}
