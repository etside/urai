# Changelog

All notable changes to Urai are documented here.

## [v1.1.1] - 2025-07-25

### Added
- Neuro layer: RAG (jev/rag.py), TF-IDF router (jev/router.py), upgraded context (jev/context.py)
- Unified surface: Android APK improvements, workflow enhancements
- docs/NEURO.md: RAG architecture documentation
- docs/BACKENDS.md: all backend documentation
- docs/SURFACES.md: all surface/access-method documentation
- model/registry.json: model registry with EC2 and S3 URLs
- .github/workflows/urai-integration.yml: smoke test + EC2 deploy + Pages
- studio/README.md: Studio access documentation

### Changed
- README rewritten as model card (HuggingFace format)
- Repo restructured as unified AI model project

## [v1.1.0] - 2025-07-01

### Added
- APK build via GitHub Actions
- TUI improvements
- AWS Polly TTS, Transcribe STT integration
- DynamoDB session memory

## [v1.0.0] - 2025-06-01

### Added
- Initial release
- EC2 API server (Qwen3-0.6B, OpenAI-compatible)
- CLI: ask, chat, tui, vibe, wiki
- GitHub Pages PWA Studio
- MCP stdio server
