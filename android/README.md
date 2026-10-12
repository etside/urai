# Urai Android app — WebView shell for the hosted web playground.
#
# Built on GitHub Actions (.github/workflows/android.yml) — runners have the
# Android SDK preinstalled. Artifacts: app-debug.apk (sideload) attached to
# every run + version-tag Releases.
#
# The app loads your Urai server URL (Settings screen; default is the
# emulator loopback http://10.0.2.2:8777/). On a phone use your LAN/VPS
# address, e.g. http://192.168.1.10:8777/ or https://ai.example.com/.
# Endpoint + API key are saved on-device and injected into the webapp.
# File uploads (See tab) support gallery + camera capture.
