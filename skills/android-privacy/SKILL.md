---
name: android-privacy
description: Android privacy auditing — AppOps detection, tracker scoring, Shizuku blocking, backend verdicts. Use for hidden-access analysis and CyberUrai verdicts.
---

# Android privacy audit skill

## What stock Android allows (no root, no system signature)
- **Detect** mic/camera/location/sensor/SMS/contacts access per package:
  `AppOpsManager.startWatchingMode(op, null, listener)` — null package
  watches all packages; callback names the package.
- **Foreground context**: `UsageStatsManager` (needs PACKAGE_USAGE_STATS
  grant in Settings) tells which app was foreground at detection time.
- **Risk scoring**: requested permissions + bundled tracker SDK package
  substrings (Meta, AppsFlyer, Adjust, Branch, OneSignal, Firebase…).

## What it cannot do (be honest)
- Silently revoke another app's permissions: impossible without system
  rights. Paths: **Shizuku** (`appops set <pkg> <OP> ignore` as shell —
  user grants once), **root** (same commands), else **settings deep-link**
  (`ACTION_APPLICATION_DETAILS_SETTINGS`) guiding the user's own two taps.
- System/preinstalled apps and Play Services: flag, explain, do not touch.

## Verdict format (cyberurai-v1)
RISK low|medium|high, then 3 bullets: why, what data is exposed, what to
do. Under 600 chars. Background access + tracker SDKs = escalate.
