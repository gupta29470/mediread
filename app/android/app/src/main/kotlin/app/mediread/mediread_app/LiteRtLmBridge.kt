package app.mediread.mediread_app

import android.os.StatFs
import com.google.ai.edge.litertlm.Backend
import com.google.ai.edge.litertlm.Contents
import com.google.ai.edge.litertlm.ConversationConfig
import com.google.ai.edge.litertlm.Engine
import com.google.ai.edge.litertlm.EngineConfig
import com.google.ai.edge.litertlm.SamplerConfig
import io.flutter.plugin.common.MethodChannel
import java.io.File
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout

/**
 * Thin bridge over the official LiteRT-LM Kotlin API.
 *
 * It exposes only load / generate / unload / info / freeBytes. All prompt
 * construction, validation and fallback live in Dart; this class never decides
 * what is safe to show.
 */
class LiteRtLmBridge(private val filesDir: File) {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private var engine: Engine? = null

    @Volatile
    private var backendName: String = "cpu"

    fun handle(method: String, args: Map<*, *>?, result: MethodChannel.Result) {
        when (method) {
            "load" -> load(args, result)
            "generate" -> generate(args, result)
            "unload" -> {
                unloadInternal()
                result.success(null)
            }
            "info" -> result.success(mapOf("loaded" to (engine != null), "backend" to backendName))
            "freeBytes" -> result.success(StatFs(filesDir.path).availableBytes)
            else -> result.notImplemented()
        }
    }

    private fun load(args: Map<*, *>?, result: MethodChannel.Result) {
        val modelPath = args?.get("modelPath") as? String
        if (modelPath.isNullOrBlank()) {
            result.error("bad_args", "modelPath is required", null)
            return
        }
        val requested = (args?.get("backend") as? String) ?: "auto"
        if (!File(modelPath).exists()) {
            result.error("model_missing", "Model file not found", null)
            return
        }
        scope.launch {
            val started = System.currentTimeMillis()
            var loaded: Engine? = null
            var backendUsed = "cpu"
            try {
                // GPU is opt-in only. A failed GPU delegate aborts natively, so the
                // catch below cannot save the process. "auto" now means CPU.
                if (requested == "gpu") {
                    try {
                        loaded = Engine(
                            EngineConfig(
                                modelPath = modelPath,
                                backend = Backend.GPU(),
                                cacheDir = filesDir.absolutePath,
                            )
                        )
                        loaded.initialize()
                        backendUsed = "gpu"
                    } catch (gpuError: Throwable) {
                        loaded?.close()
                        loaded = null
                    }
                }
                if (loaded == null) {
                    loaded = Engine(
                        EngineConfig(
                            modelPath = modelPath,
                            cacheDir = filesDir.absolutePath,
                        )
                    )
                    loaded.initialize()
                    backendUsed = "cpu"
                }
                unloadInternal()
                engine = loaded
                backendName = backendUsed
                val elapsed = System.currentTimeMillis() - started
                withContext(Dispatchers.Main) {
                    result.success(
                        mapOf(
                            "loaded" to true,
                            "backend" to backendUsed,
                            "loadMs" to elapsed,
                        )
                    )
                }
            } catch (error: Throwable) {
                loaded?.close()
                withContext(Dispatchers.Main) {
                    result.error("load_failed", error.message ?: error.toString(), null)
                }
            }
        }
    }

    private fun generate(args: Map<*, *>?, result: MethodChannel.Result) {
        val current = engine
        if (current == null) {
            result.error("not_loaded", "No model is loaded", null)
            return
        }
        val systemPrompt = (args?.get("systemPrompt") as? String) ?: ""
        val userPrompt = (args?.get("userPrompt") as? String) ?: ""
        val maxTokens = (args?.get("maxTokens") as? Number)?.toInt() ?: 512
        if (userPrompt.isBlank()) {
            result.error("bad_args", "userPrompt is required", null)
            return
        }
        scope.launch {
            val started = System.currentTimeMillis()
            try {
                val text = withTimeout(240_000L) {
                    val config = ConversationConfig(
                        systemInstruction = Contents.of(systemPrompt),
                        samplerConfig = SamplerConfig(
                            topK = 1,
                            topP = 1.0,
                            temperature = 0.0,
                        ),
                    )
                    current.createConversation(config).use { conversation ->
                        conversation.sendMessage(userPrompt).toString()
                    }
                }
                val elapsed = System.currentTimeMillis() - started
                withContext(Dispatchers.Main) {
                    result.success(
                        mapOf(
                            "text" to text,
                            "totalMs" to elapsed,
                            "backend" to backendName,
                            "maxTokens" to maxTokens,
                        )
                    )
                }
            } catch (timeout: Throwable) {
                withContext(Dispatchers.Main) {
                    result.error("generate_failed", timeout.message ?: timeout.toString(), null)
                }
            }
        }
    }

    private fun unloadInternal() {
        try {
            engine?.close()
        } catch (_: Throwable) {
            // best effort
        }
        engine = null
    }

    fun dispose() {
        unloadInternal()
    }
}
