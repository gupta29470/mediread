import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:mediread_app/src/ai/model_artifact.dart';
import 'package:mediread_app/src/ai/model_download_manager.dart';

class _FakeClient extends http.BaseClient {
  _FakeClient(this.bytes);

  final List<int> bytes;
  int requests = 0;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    requests++;
    var start = 0;
    final range = request.headers['Range'];
    if (range != null && range.startsWith('bytes=')) {
      start = int.parse(range.substring(6).replaceAll('-', ''));
    }
    final slice = bytes.sublist(start.clamp(0, bytes.length));
    return http.StreamedResponse(
      Stream<List<int>>.fromIterable([slice]),
      start > 0 ? 206 : 200,
      contentLength: slice.length,
    );
  }
}

class _Storage implements StorageProbe {
  _Storage(this.free);

  final int free;

  @override
  Future<int> freeBytes() async => free;
}

class _Wifi implements WifiProbe {
  _Wifi(this.connected);

  final bool connected;

  @override
  Future<bool> isWifi() async => connected;
}

ModelArtifact artifactFor(List<int> bytes) => ModelArtifact(
      id: 'test',
      displayName: 'Test model',
      version: '1.0.0',
      revision: 'rev',
      fileName: 'model.litertlm',
      url: 'https://example.test/model.litertlm',
      sha256: sha256.convert(bytes).toString(),
      sizeBytes: bytes.length,
      license: 'Apache-2.0',
      minAppVersion: 1,
    );


class _ResponseClient extends http.BaseClient {
  _ResponseClient(
    this.body,
    this.status, {
    this.headers = const {},
    this.contentLengthOverride,
  });

  final List<int> body;
  final int status;
  final Map<String, String> headers;
  final int? contentLengthOverride;
  int requests = 0;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    requests++;
    return http.StreamedResponse(
      Stream<List<int>>.fromIterable([body]),
      status,
      contentLength: contentLengthOverride ?? body.length,
      headers: headers,
    );
  }
}

void main() {
  late Directory dir;

  setUp(() async {
    dir = await Directory.systemTemp.createTemp('mediread_dl_test');
  });

  tearDown(() async {
    if (await dir.exists()) await dir.delete(recursive: true);
  });

  ModelDownloadManager manager(ModelArtifact artifact, http.BaseClient client,
          {int free = 1 << 40, bool wifi = true}) =>
      ModelDownloadManager(
        artifact: artifact,
        client: client,
        directory: dir,
        storage: _Storage(free),
        wifi: _Wifi(wifi),
        metadataStore: InMemoryMetadataStore(),
      );

  test('downloads, verifies and installs', () async {
    final bytes = List<int>.generate(4096, (index) => index % 251);
    final artifact = artifactFor(bytes);
    final download = manager(artifact, _FakeClient(bytes));
    var lastProgress = 0.0;
    final seen = <DownloadProgress>[];
    await download.download(
      wifiOnly: true,
      onProgress: seen.add,
      isCancelled: () async => false,
    );
    lastProgress = seen.last.fraction;
    expect((await download.state()).isInstalled, isTrue);
    expect(await download.verifyInstalled(), isTrue);
    expect(lastProgress, 1.0);
  });

  test('resumes a partial download with a range request', () async {
    final bytes = List<int>.generate(8192, (index) => (index * 7) % 253);
    final artifact = artifactFor(bytes);
    final download = manager(artifact, _FakeClient(bytes));
    await download.partialFile.writeAsBytes(bytes.sublist(0, 3000));
    expect((await download.state()).availability, ModelAvailability.partial);

    await download.download(
      wifiOnly: false,
      onProgress: (_) {},
      isCancelled: () async => false,
    );
    expect(await download.modelFile.readAsBytes(), bytes);
    expect(await download.verifyInstalled(), isTrue);
  });

  test('rejects a checksum mismatch and removes the file', () async {
    final expected = List<int>.filled(2048, 1);
    final served = List<int>.filled(2048, 2);
    final artifact = artifactFor(expected);
    final download = manager(artifact, _FakeClient(served));
    await expectLater(
      download.download(wifiOnly: false, onProgress: (_) {}, isCancelled: () async => false),
      throwsA(isA<DownloadException>()
          .having((error) => error.code, 'code', 'checksum_mismatch')),
    );
    expect(await download.partialFile.exists(), isFalse);
    expect(await download.modelFile.exists(), isFalse);
  });

  test('refuses to start without enough storage', () async {
    final bytes = List<int>.generate(1024, (index) => index % 200);
    final artifact = artifactFor(bytes);
    final client = _FakeClient(bytes);
    final download = manager(artifact, client, free: 1024);
    await expectLater(
      download.download(wifiOnly: false, onProgress: (_) {}, isCancelled: () async => false),
      throwsA(isA<DownloadException>()
          .having((error) => error.code, 'code', 'insufficient_storage')),
    );
    expect(client.requests, 0);
  });

  test('refuses to start when Wi-Fi is required and unavailable', () async {
    final bytes = List<int>.generate(512, (index) => index % 199);
    final artifact = artifactFor(bytes);
    final client = _FakeClient(bytes);
    final download = manager(artifact, client, wifi: false);
    await expectLater(
      download.download(wifiOnly: true, onProgress: (_) {}, isCancelled: () async => false),
      throwsA(isA<DownloadException>()
          .having((error) => error.code, 'code', 'wifi_required')),
    );
    expect(client.requests, 0);
  });

  test('cancellation keeps the partial file for a later resume', () async {
    final bytes = List<int>.generate(4096, (index) => index % 241);
    final artifact = artifactFor(bytes);
    final download = manager(artifact, _FakeClient(bytes));
    await expectLater(
      download.download(wifiOnly: false, onProgress: (_) {}, isCancelled: () async => true),
      throwsA(isA<DownloadException>().having((error) => error.code, 'code', 'cancelled')),
    );
    expect(await download.partialFile.exists(), isTrue);
    expect(await download.modelFile.exists(), isFalse);
  });

  test('a paused transfer can be resumed in the same session (stale future regression)',
      () async {
    final bytes = List<int>.generate(8192, (index) => (index * 7) % 253);
    final artifact = artifactFor(bytes);
    final gate = Completer<void>();
    final client = _PacedClient([bytes.sublist(0, 2048), bytes.sublist(2048)], gate.future);
    final download = manager(artifact, client);

    final writable = Completer<void>();
    final first = download.download(
      wifiOnly: false,
      onProgress: (progress) {
        if (progress.received >= 2048 && !writable.isCompleted) writable.complete();
      },
      isCancelled: () async => false,
    );
    await writable.future;
    download.cancel(); // what a pause does: bump generation, keep the .part file
    gate.complete();

    await expectLater(
      first,
      throwsA(isA<DownloadException>().having((error) => error.code, 'code', 'cancelled')),
    );
    expect(await download.partialFile.exists(), isTrue);

    // The next call must start a new transfer, not hand back the finished one.
    await download.download(wifiOnly: false, onProgress: (_) {}, isCancelled: () async => false);

    expect(client.requests, 2);
    expect(await download.verifyInstalled(), isTrue);
  });

  test('a dropped connection is reported and resumes from the kept bytes', () async {
    final bytes = List<int>.generate(4096, (index) => (index * 3) % 253);
    final artifact = artifactFor(bytes);
    final breaking = _BreakingClient(bytes.sublist(0, 1024), artifact.sizeBytes);
    final live = manager(artifact, breaking);

    await expectLater(
      live.download(wifiOnly: false, onProgress: (_) {}, isCancelled: () async => false),
      throwsA(isA<DownloadException>().having((error) => error.code, 'code', 'network')),
    );
    expect(await live.modelFile.exists(), isFalse);
    expect(await live.partialFile.length(), 1024);

    // A fresh manager (as after a restart) resumes from the bytes on disk.
    final resumed = manager(artifact, _FakeClient(bytes));
    await resumed.download(wifiOnly: false, onProgress: (_) {}, isCancelled: () async => false);
    expect(await resumed.modelFile.readAsBytes(), bytes);
  });

  test('adopts an orphaned file only when its checksum matches', () async {
    final bytes = List<int>.generate(4096, (index) => (index * 5) % 253);
    final artifact = artifactFor(bytes);
    final download = manager(artifact, _FakeClient(bytes));
    await download.modelFile.writeAsBytes(bytes);

    expect((await download.state()).availability, ModelAvailability.versionMismatch);
    expect(await download.adoptIfVerified(), isTrue);
    expect((await download.state()).isInstalled, isTrue);

    final corrupt = manager(artifact, _FakeClient(bytes));
    await corrupt.delete();
    await corrupt.modelFile.writeAsBytes(List<int>.filled(bytes.length, 7));
    expect((await corrupt.state()).availability, ModelAvailability.versionMismatch);
    expect(await corrupt.adoptIfVerified(), isFalse);
    expect((await corrupt.state()).isInstalled, isFalse);
  });

  test('a validated alternate digest installs and is recorded', () async {
    final bytes = List<int>.generate(4096, (index) => (index * 11) % 251);
    final digest = sha256.convert(bytes).toString();
    final artifact = ModelArtifact(
      id: 'test-alt',
      displayName: 'Alternate export',
      version: '1.0.0',
      revision: 'rev',
      fileName: 'model-alt.litertlm',
      url: 'https://example.test/model-alt.litertlm',
      sha256: 'a' * 64,
      alternateSha256: [digest],
      sizeBytes: bytes.length,
      license: 'Apache-2.0',
      minAppVersion: 1,
    );
    expect(artifact.acceptedSha256, contains('a' * 64));
    expect(artifact.acceptedSha256, contains(digest));

    final store = InMemoryMetadataStore();
    final download = ModelDownloadManager(
      artifact: artifact,
      client: _FakeClient(bytes),
      directory: dir,
      storage: _Storage(1 << 40),
      wifi: _Wifi(true),
      metadataStore: store,
    );
    await download.download(wifiOnly: false, onProgress: (_) {}, isCancelled: () async => false);

    expect(await download.verifyInstalled(), isTrue);
    expect((await download.state()).isInstalled, isTrue);
    expect((await store.read())?.sha256, digest);
  });

  test('delete removes the model and its metadata', () async {
    final bytes = List<int>.generate(1024, (index) => index % 197);
    final artifact = artifactFor(bytes);
    final download = manager(artifact, _FakeClient(bytes));
    await download.download(wifiOnly: false, onProgress: (_) {}, isCancelled: () async => false);
    await download.delete();
    expect(await download.modelFile.exists(), isFalse);
    expect((await download.state()).availability, ModelAvailability.notInstalled);
  });


  test('refuses an HTML page served as the model', () async {
    final html = utf8.encode('<!DOCTYPE html><html><body>Confirm download</body></html>');
    final artifact = artifactFor(List<int>.filled(2048, 1));
    final download = manager(
      artifact,
      _ResponseClient(html, 200, headers: {'content-type': 'text/html; charset=utf-8'}),
    );

    await expectLater(
      download.download(wifiOnly: false, onProgress: (_) {}, isCancelled: () async => false),
      throwsA(isA<DownloadException>().having((error) => error.code, 'code', 'html_response')),
    );
    expect(await download.modelFile.exists(), isFalse);
    expect(await download.partialFile.exists(), isFalse);
    expect((await download.state()).availability, ModelAvailability.notInstalled);
  });

  test('sniffs an HTML body even when the content type lies', () async {
    final html = utf8.encode('<!DOCTYPE html><html><body>Sign in</body></html>');
    final artifact = artifactFor(List<int>.filled(4096, 7));
    final download = manager(
      artifact,
      _ResponseClient(
        html,
        200,
        headers: {'content-type': 'application/octet-stream'},
        contentLengthOverride: artifact.sizeBytes,
      ),
    );

    await expectLater(
      download.download(wifiOnly: false, onProgress: (_) {}, isCancelled: () async => false),
      throwsA(isA<DownloadException>().having((error) => error.code, 'code', 'html_response')),
    );
    expect(await download.modelFile.exists(), isFalse);
  });

  test('rejects a response whose declared size is not the artifact size', () async {
    final artifact = artifactFor(List<int>.filled(4096, 3));
    final download = manager(
      artifact,
      _ResponseClient(List<int>.filled(100, 3), 200, contentLengthOverride: 100),
    );

    await expectLater(
      download.download(wifiOnly: false, onProgress: (_) {}, isCancelled: () async => false),
      throwsA(isA<DownloadException>().having((error) => error.code, 'code', 'unexpected_size')),
    );
    expect(await download.modelFile.exists(), isFalse);
  });

  test('a Drive confirmation redirect is reported, not saved', () async {
    final artifact = artifactFor(List<int>.filled(1024, 4));
    final download = manager(artifact, _ResponseClient(const [], 303));

    await expectLater(
      download.download(wifiOnly: false, onProgress: (_) {}, isCancelled: () async => false),
      throwsA(isA<DownloadException>()
          .having((error) => error.code, 'code', 'confirmation_required')),
    );
    expect(await download.modelFile.exists(), isFalse);
  });

  test('an HTTP error status is surfaced', () async {
    final artifact = artifactFor(List<int>.filled(1024, 5));
    final download = manager(artifact, _ResponseClient(const [], 404));

    await expectLater(
      download.download(wifiOnly: false, onProgress: (_) {}, isCancelled: () async => false),
      throwsA(isA<DownloadException>().having((error) => error.code, 'code', 'http_404')),
    );
  });

  test('a truncated transfer keeps the partial file and never installs', () async {
    final artifact = artifactFor(List<int>.filled(4096, 6));
    final download = manager(
      artifact,
      _ResponseClient(List<int>.filled(1000, 6), 200, contentLengthOverride: artifact.sizeBytes),
    );

    await expectLater(
      download.download(wifiOnly: false, onProgress: (_) {}, isCancelled: () async => false),
      throwsA(isA<DownloadException>().having((error) => error.code, 'code', 'incomplete')),
    );
    expect(await download.modelFile.exists(), isFalse);
    expect(await download.partialFile.exists(), isTrue);
    expect((await download.state()).availability, ModelAvailability.partial);
  });

  _concurrencyTests();
}


class _BreakingClient extends http.BaseClient {
  _BreakingClient(this.firstChunk, this.total);

  final List<int> firstChunk;
  final int total;
  int requests = 0;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    requests++;
    Stream<List<int>> body() async* {
      yield firstChunk;
      throw http.ClientException('connection reset by peer');
    }

    return http.StreamedResponse(body(), 200, contentLength: total);
  }
}

class _PacedClient extends http.BaseClient {
  _PacedClient(this.chunks, this.gate);

  final List<List<int>> chunks;
  final Future<void> gate;
  int requests = 0;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    requests++;
    final total = chunks.fold<int>(0, (sum, chunk) => sum + chunk.length);
    Stream<List<int>> body() async* {
      yield chunks.first;
      await gate;
      for (final chunk in chunks.skip(1)) {
        yield chunk;
      }
    }

    return http.StreamedResponse(body(), 200, contentLength: total);
  }
}

class _GatedClient extends http.BaseClient {
  _GatedClient(this.bytes, this.gate);

  final List<int> bytes;
  final Future<void> gate;
  int requests = 0;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    requests++;
    final stream = Stream<List<int>>.fromFuture(gate.then((_) => bytes));
    return http.StreamedResponse(stream, 200, contentLength: bytes.length);
  }
}

void _concurrencyTests() {
  late Directory dir;
  setUp(() async => dir = await Directory.systemTemp.createTemp('mediread_conc'));
  tearDown(() async {
    if (await dir.exists()) await dir.delete(recursive: true);
  });

  test('two concurrent download calls share one transfer', () async {
    final bytes = List<int>.generate(4096, (index) => index % 251);
    final artifact = artifactFor(bytes);
    final gate = Completer<void>();
    final client = _GatedClient(bytes, gate.future);
    final download = ModelDownloadManager(
      artifact: artifact,
      client: client,
      directory: dir,
      storage: _Storage(1 << 40),
      wifi: _Wifi(true),
      metadataStore: InMemoryMetadataStore(),
    );
    final first = download.download(
        wifiOnly: false, onProgress: (_) {}, isCancelled: () async => false);
    await Future<void>.delayed(const Duration(milliseconds: 20));
    final second = download.download(
        wifiOnly: false, onProgress: (_) {}, isCancelled: () async => false);
    expect(client.requests, 1);
    gate.complete();
    await Future.wait([first, second]);
    expect(await download.verifyInstalled(), isTrue);
  });

  test('resume reports the existing fraction immediately, never zero', () async {
    final bytes = List<int>.generate(8192, (index) => (index * 3) % 253);
    final artifact = artifactFor(bytes);
    final download = ModelDownloadManager(
      artifact: artifact,
      client: _FakeClient(bytes),
      directory: dir,
      storage: _Storage(1 << 40),
      wifi: _Wifi(true),
      metadataStore: InMemoryMetadataStore(),
    );
    await download.partialFile.writeAsBytes(bytes.sublist(0, 4096));
    final seen = <DownloadProgress>[];
    await download.download(
        wifiOnly: false, onProgress: seen.add, isCancelled: () async => false);
    expect(seen.first.fraction, closeTo(0.5, 0.01));
    for (var i = 1; i < seen.length; i++) {
      expect(seen[i].fraction, greaterThanOrEqualTo(seen[i - 1].fraction));
    }
    expect(seen.last.fraction, 1.0);
  });
}
