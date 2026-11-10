# Urai — R8 rules for the release build.
#
# The app is a thin WebView shell plus the CyberUrai guard. Nothing is
# reached through @JavascriptInterface, but several pieces are reflective:
# the optional Shizuku helper is looked up with Class.forName, activities
# and the foreground service are instantiated by the framework from the
# manifest, and org.json is used directly. Keep all of it so R8 cannot
# strip entry points the platform resolves at runtime.

# App classes: keep names/members (activities, service, receivers, guard).
-keep class io.github.tukitattu.urai.** { *; }

# org.json objects are constructed reflectively/duck-typed in places.
-keep class org.json.** { *; }

# Optional Shizuku privileged-API bridge, resolved by reflection only.
-dontwarn moe.shizuku.**

# Preserve metadata needed for reflective lookups and JSON handling.
-keepattributes *Annotation*, Signature, InnerClasses, EnclosingMethod
