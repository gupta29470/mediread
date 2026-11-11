package app.mediread.mediread_app

import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {

    private var bridge: LiteRtLmBridge? = null

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        val local = LiteRtLmBridge(filesDir)
        bridge = local
        MethodChannel(
            flutterEngine.dartExecutor.binaryMessenger,
            "app.mediread/litertlm",
        ).setMethodCallHandler { call, result ->
            local.handle(call.method, call.arguments as? Map<*, *>, result)
        }
    }

    override fun onDestroy() {
        bridge?.dispose()
        bridge = null
        super.onDestroy()
    }
}
