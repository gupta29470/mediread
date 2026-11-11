# ML Kit text recognition declares the non-Latin scripts as `compileOnly` in the
# Flutter plugin, so R8 sees references to classes that are intentionally absent.
# This app only uses the bundled Latin model.
-dontwarn com.google.mlkit.vision.text.**
-dontwarn com.google.mlkit.vision.text.chinese.**
-dontwarn com.google.mlkit.vision.text.devanagari.**
-dontwarn com.google.mlkit.vision.text.japanese.**
-dontwarn com.google.mlkit.vision.text.korean.**

# ML Kit resolves its component registrars and model descriptors reflectively.
# Debug builds do not run R8, so a missing keep rule only shows up in release:
# without these, release builds crash inside InputImage/TextRecognizer
# (NullPointerException from a stripped class) and every OCR call fails.
-keep class com.google.mlkit.** { *; }
-keep class com.google_mlkit_commons.** { *; }
-keep class com.google_mlkit_text_recognition.** { *; }
-keep class com.google.android.gms.internal.mlkit_vision_text** { *; }
-keepclassmembers class * {
    @com.google.mlkit.common.sdkinternal.MlKitContextInitializer *;
}

# LiteRT-LM's Kotlin API is called from its own JNI library by name. R8 renames
# these classes in release builds, and the native side then aborts with
# "JNI DETECTED ERROR IN APPLICATION: mid == null" while creating a conversation
# (the smoke test on model activation). Keep the whole public surface intact.
-keep class com.google.ai.edge.litertlm.** { *; }
-keepclassmembers class com.google.ai.edge.litertlm.** { *; }
-dontwarn com.google.ai.edge.litertlm.**
