# CyberUrai-v1 — cybersecurity specialist model + Android guard

Brand id **`cyberurai-v1`** (tier `urai-cyber`): Qwen3-4B wired to the cyber
skill stack (cyber-security, threat-analysis, android-privacy), consistency
sampling + verify-first, evidence-only verdicts. Weights upgrade later via
the Laya pipeline; the brand, tier and gates are live now.

## Model side (live, no keys)
- `POST /agent {"tier": "urai-cyber"}` or `"model": "cyberurai-v1"` on chat
  endpoints (brand resolves to the cyber tier).
- Verdict format: RISK + 3 bullets, under 600 chars.

## Android guard (APK module `android/.../cyber/`)
- **Detect** (no special rights): AppOps watchers for mic, camera, fine/
  coarse/background location, body sensors, activity recognition, SMS,
  contacts + UsageStats foreground correlation + tracker SDK scoring.
- **Notify + prompt**: notification per op+pkg (1/min cap) → review dialog
  → Block / Allow / Ask CyberUrai (backend verdict via `/agent`).
- **Block** (honest tiers): Shizuku shell `appops set … ignore` → root
  shell → system settings deep-link. Detection never over-claims.
- Needs install-time grants: Usage Access (Settings), notifications,
  Shizuku (optional, one-time) for silent blocking.
- Build: existing `Urai Android` workflow (debug APK artifact).

## Permissions truth table
| Capability | Stock | Shizuku/ADB | Root |
|---|---|---|---|
| Detect mic/camera/location per app | yes | yes | yes |
| Background-vs-foreground context | yes (UsageStats) | yes | yes |
| Silent revoke other apps | no | yes | yes |
| Guided user revoke | yes | yes | yes |
