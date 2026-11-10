# Urai Android app — WebView shell for the hosted web playground.
#
# Built on GitHub Actions (.github/workflows/android.yml) — runners have the
# Android SDK preinstalled and Gradle 8.10.2 is pinned via
# gradle/actions/setup-gradle@v4, so no ./gradlew wrapper is checked in (the
# wrapper jar is a binary we deliberately don't vendor). Build locally with a
# system Gradle 8.10.2: `cd android && gradle :app:assembleDebug`.
#
# Artifacts: APK (sideload) + AAB (Play) attached to every run and to
# version-tag Releases. Version name comes from the git tag (v1.2.3 -> 1.2.3),
# version code from the CI run number; override with URAI_VERSION_NAME /
# URAI_VERSION_CODE.
#
# The app loads your Urai server URL (Settings screen; default is the
# emulator loopback http://10.0.2.2:8777/). On a phone use your LAN/VPS
# address, e.g. http://192.168.1.10:8777/ or https://ai.example.com/.
# Endpoint + API key are saved on-device and injected into the webapp.
# File uploads (See tab) support gallery + camera capture.
