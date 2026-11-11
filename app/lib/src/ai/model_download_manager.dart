import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:http/http.dart' as http;

import 'model_artifact.dart';

class DownloadException implements Exception {
  const DownloadException(this.code, this.message);

  final String code;
  final String message;

  @override
  String toString() => 'DownloadException($code): $message';
}

enum ModelAvailability { notInstalled, partial, installed, versionMismatch }

/// Immutable progress snapshot. Fraction is clamped and never computed from a
/// stale total, so the UI has exactly one source of truth.
class DownloadProgress {
  const DownloadProgress({required this.received, required this.total, this.restarting = false});

  final int received;
  final int total;
  final bool restarting;

  double get fraction => total <= 0 ? 0 : (received / total).clamp(0.0, 1.0);
}

class ModelState {
  const ModelState({required this.availability, this.bytesOnDisk = 0, this.metadata});

  final ModelAvailability availability;
  final int bytesOnDisk;
  final ModelMetadata? metadata;

  bool get isInstalled => availability == ModelAvailability.installed;
}

class ModelMetadata {
  const ModelMetadata({
    required this.version,
    required this.sha256,
    required this.sizeBytes,
    required this.installedAt,
  });

  final String version;
  final String sha256;
  final int sizeBytes;
  final String installedAt;

  Map<String, dynamic> toJson() => {
        'version': version,
        'sha256': sha256,
        'sizeBytes': sizeBytes,
        'installedAt': installedAt,
      };

  factory ModelMetadata.fromJson(Map<String, dynamic> json) => ModelMetadata(
        version: json['version'] as String? ?? '',
        sha256: json['sha256'] as String? ?? '',
        sizeBytes: (json['sizeBytes'] as num?)?.toInt() ?? 0,
        installedAt: json['installedAt'] as String? ?? '',
      );
}

abstract interface class ModelMetadataStore {
  Future<ModelMetadata?> read();
  Future<void> write(ModelMetadata metadata);
  Future<void> clear();
}

class InMemoryMetadataStore implements ModelMetadataStore {
  ModelMetadata? _value;

  @override
  Future<ModelMetadata?> read() async => _value;

  @override
  Future<void> write(ModelMetadata metadata) async => _value = metadata;

  @override
  Future<void> clear() async => _value = null;
}

abstract interface class StorageProbe {
  Future<int> freeBytes();
}

abstract interface class WifiProbe {
  Future<bool> isWifi();
}

class _DigestSink implements Sink<Digest> {
  Digest? value;

  @override
  void add(Digest data) => value = data;

  @override
  void close() {}
}

/// Download-on-first-use with consent, progress, cancel, resume, storage and
/// checksum verification. Never starts without an explicit call from a user
/// consent flow.
class ModelDownloadManager {
  ModelDownloadManager({
    required this.artifact,
    required this.client,
    required this.directory,
    required this.storage,
    required this.wifi,
    required this.metadataStore,
  });

  final ModelArtifact artifact;
  final http.Client client;
  final Directory directory;
  final StorageProbe storage;
  final WifiProbe wifi;
  final ModelMetadataStore metadataStore;

  File get modelFile => File('${directory.path}/${artifact.fileName}');
  File get partialFile => File('${directory.path}/${artifact.fileName}.part');

  Future<ModelState> state() async {
    final metadata = await metadataStore.read();
    if (await modelFile.exists()) {
      final size = await modelFile.length();
      if (metadata != null &&
          metadata.version == artifact.version &&
          artifact.acceptsDigest(metadata.sha256) &&
          size == artifact.sizeBytes) {
        return ModelState(
          availability: ModelAvailability.installed,
          bytesOnDisk: size,
          metadata: metadata,
        );
      }
      return ModelState(
        availability: ModelAvailability.versionMismatch,
        bytesOnDisk: size,
        metadata: metadata,
      );
    }
    if (await partialFile.exists()) {
      return ModelState(
        availability: ModelAvailability.partial,
        bytesOnDisk: await partialFile.length(),
        metadata: metadata,
      );
    }
    return const ModelState(availability: ModelAvailability.notInstalled);
  }

  Future<void>? _active;
  bool _cancelRequested = false;
  int _generation = 0;

  bool get isDownloading => _active != null;

  /// Cancels the running download. Cooperative: the active loop checks the flag
  /// between chunks, and a late second call can never start a second writer.
  void cancel() {
    _cancelRequested = true;
    _generation++;
  }

  /// Downloads the model, resuming a `.part` file when one exists.
  ///
  /// Only one transfer can run at a time; concurrent callers await the same
  /// future. This is what prevents two progress streams from interleaving.
  Future<void> download({
    required bool wifiOnly,
    required void Function(DownloadProgress progress) onProgress,
    required Future<bool> Function() isCancelled,
  }) {
    final running = _active;
    if (running != null) return running;
    final generation = ++_generation;
    _cancelRequested = false;
    final transfer = _download(
      wifiOnly: wifiOnly,
      onProgress: onProgress,
      isCancelled: isCancelled,
      generation: generation,
    );
    // Clear the in-flight slot when *this* transfer ends. Identity, not the
    // generation counter, decides: cancel() bumps the generation, so a
    // generation-based guard left a cancelled/paused transfer installed for
    // ever and made the next resume return the already-finished future.
    late final Future<void> tracked;
    tracked = transfer.whenComplete(() {
      if (identical(_active, tracked)) _active = null;
    });
    _active = tracked;
    return tracked;
  }

  Future<void> _download({
    required bool wifiOnly,
    required void Function(DownloadProgress progress) onProgress,
    required Future<bool> Function() isCancelled,
    required int generation,
  }) async {
    if (!artifact.hasPinnedChecksum) {
      throw const DownloadException('untrusted_artifact', 'No pinned SHA-256 for this artifact');
    }
    if (wifiOnly && !await wifi.isWifi()) {
      throw const DownloadException('wifi_required', 'Connect to Wi-Fi to download the model');
    }
    final free = await storage.freeBytes();
    final existing = await partialFile.exists() ? await partialFile.length() : 0;
    if (free + existing < artifact.requiredFreeBytes) {
      throw DownloadException(
        'insufficient_storage',
        'Need ${(artifact.requiredFreeBytes / (1000 * 1000 * 1000)).toStringAsFixed(2)} GB free, '
            'have ${(free / (1000 * 1000 * 1000)).toStringAsFixed(2)} GB',
      );
    }

    final total = artifact.sizeBytes;
    var lastTenth = -1;
    void emit(int received, {bool restarting = false}) {
      final tenth = total <= 0 ? 0 : (received * 1000 ~/ total);
      if (!restarting && tenth == lastTenth) return;
      lastTenth = tenth;
      onProgress(DownloadProgress(received: received, total: total, restarting: restarting));
    }

    await directory.create(recursive: true);
    var start = existing.clamp(0, total);

    final request = http.Request('GET', Uri.parse(artifact.url));
    if (start > 0) request.headers['Range'] = 'bytes=$start-';
    final http.StreamedResponse response;
    try {
      response = await client.send(request);
    } catch (error) {
      throw DownloadException(
        'network',
        'Could not reach the download server. Check your connection and resume; '
            '${existing > 0 ? 'the bytes already downloaded are kept.' : 'nothing was downloaded.'}',
      );
    }

    // Google Drive and other file hosts can answer a link with a web page
    // (quota warning, virus scan interstitial, sign-in page) instead of bytes.
    // That must never reach the disk as a model file.
    final contentType = (response.headers['content-type'] ?? '').toLowerCase();
    if (contentType.contains('text/html') || contentType.contains('application/xhtml')) {
      throw const DownloadException(
        'html_response',
        'The download server returned a web page instead of the model file. '
            'Check the connection and try again.',
      );
    }
    if (response.statusCode == 302 || response.statusCode == 303) {
      throw const DownloadException(
        'confirmation_required',
        'The download server asked for confirmation instead of sending the file.',
      );
    }

    if (response.statusCode == 200) {
      final encoded = response.headers['content-encoding'];
      final declared = response.contentLength;
      if (encoded == null && declared != null && declared != total) {
        throw DownloadException(
          'unexpected_size',
          'The server sent $declared bytes but ${artifact.fileName} is $total bytes.',
        );
      }
    }

    if (response.statusCode == 200) {
      // The server ignored the range request, so the transfer restarts. This is
      // the only case where the reported fraction may legitimately decrease.
      start = 0;
      lastTenth = -1;
      if (await partialFile.exists()) await partialFile.delete();
      emit(0, restarting: true);
    } else if (response.statusCode != 206 && start > 0) {
      throw DownloadException('http_${response.statusCode}', 'Server rejected the resume request');
    } else if (response.statusCode != 200 && response.statusCode != 206) {
      throw DownloadException('http_${response.statusCode}', 'Download failed');
    }

    var received = start;
    final sink = partialFile.openWrite(mode: start > 0 ? FileMode.append : FileMode.write);
    emit(received); // resume shows the real fraction immediately, never 0
    try {
      await for (final chunk in response.stream) {
        if (_cancelRequested || generation != _generation || await isCancelled()) {
          throw const DownloadException('cancelled', 'Download cancelled');
        }
        // A model file is binary; a leading '<' means an HTML page slipped past
        // the content-type header. Refuse it rather than persisting it.
        if (received == 0 && chunk.isNotEmpty && chunk.first == 0x3C) {
          throw const DownloadException(
            'html_response',
            'The download server returned a web page instead of the model file. '
                'Check the connection and try again.',
          );
        }
        sink.add(chunk);
        received += chunk.length;
        if (received > total) {
          throw const DownloadException('oversize', 'Server sent more bytes than expected');
        }
        emit(received);
      }
    } on DownloadException {
      rethrow;
    } catch (error) {
      // A dropped connection keeps the bytes written so far; the next call
      // resumes with a Range request.
      throw DownloadException(
        'network',
        'The download was interrupted. Resume to continue where it stopped.',
      );
    } finally {
      await sink.close();
    }

    if (received != total) {
      throw DownloadException(
        'incomplete',
        'Incomplete download: $received of $total bytes (kept for resume)',
      );
    }

    emit(received);
    final digest = await _sha256Of(partialFile);
    if (!artifact.acceptsDigest(digest)) {
      await partialFile.delete();
      throw const DownloadException(
        'checksum_mismatch',
        'The downloaded file is not the validated release (checksum mismatch), so it was '
            'deleted. The file on the server may have changed; try again later.',
      );
    }

    if (await modelFile.exists()) await modelFile.delete();
    await partialFile.rename(modelFile.path);
    await metadataStore.write(ModelMetadata(
      version: artifact.version,
      sha256: digest,
      sizeBytes: artifact.sizeBytes,
      installedAt: DateTime.now().toUtc().toIso8601String(),
    ));
  }

  Future<bool> verifyInstalled() async {
    if (!await modelFile.exists()) return false;
    if (await modelFile.length() != artifact.sizeBytes) return false;
    return artifact.acceptsDigest(await _sha256Of(modelFile));
  }

  /// Adopts a complete model file whose metadata was lost (an OS backup/restore,
  /// or a file restored outside the app). The checksum is the gate: a file that
  /// does not match the pinned digest is never adopted.
  Future<bool> adoptIfVerified() async {
    if (!await modelFile.exists()) return false;
    if (await modelFile.length() != artifact.sizeBytes) return false;
    final digest = await _sha256Of(modelFile);
    if (!artifact.acceptsDigest(digest)) return false;
    await metadataStore.write(ModelMetadata(
      version: artifact.version,
      sha256: digest,
      sizeBytes: artifact.sizeBytes,
      installedAt: DateTime.now().toUtc().toIso8601String(),
    ));
    return true;
  }

  Future<void> delete() async {
    if (await modelFile.exists()) await modelFile.delete();
    if (await partialFile.exists()) await partialFile.delete();
    await metadataStore.clear();
  }

  Future<String> _sha256Of(File file) async {
    final sink = _DigestSink();
    final input = sha256.startChunkedConversion(sink);
    await for (final chunk in file.openRead()) {
      input.add(chunk);
    }
    input.close();
    return (sink.value ?? sha256.convert(const [])).toString();
  }
}

class JsonMetadataStore implements ModelMetadataStore {
  JsonMetadataStore(this._read, this._write, this._clear);

  final Future<String?> Function() _read;
  final Future<void> Function(String) _write;
  final Future<void> Function() _clear;

  @override
  Future<ModelMetadata?> read() async {
    final raw = await _read();
    if (raw == null || raw.isEmpty) return null;
    try {
      return ModelMetadata.fromJson(jsonDecode(raw) as Map<String, dynamic>);
    } catch (_) {
      return null;
    }
  }

  @override
  Future<void> write(ModelMetadata metadata) => _write(jsonEncode(metadata.toJson()));

  @override
  Future<void> clear() => _clear();
}
