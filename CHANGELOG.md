# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.0.0] - 2026-06-05

### Added

- Emporia Vue energy monitor collector with MQTT Discovery for Home Assistant
- AWS Cognito SRP authentication (stdlib only, no external auth dependencies)
- Support for Vue Gen 1, Gen 2, and Gen 3 devices
- Power (W) and energy (kWh) sensors per circuit
- Energy cost sensor from Emporia API utility rate
- Automatic MQTT Discovery (sensors auto-appear in HA)
- 60-second polling with jitter to avoid API rate limits
- Graceful shutdown on SIGTERM
- Docker deployment with security hardening (non-root, read-only fs, no capabilities)
- GitHub Actions CI with 75% coverage gate
- Dependabot for dependency updates
- Contributing guide, security policy, and issue/PR templates

### Security

- Container runs as non-root with all capabilities dropped
- MQTT authentication required (connects to HA's Mosquitto add-on)
- Credentials isolated in `.env` (never committed)
- Workflow permissions restricted to read-only

[1.0.0]: https://github.com/sutterj/emporia-collector/releases/tag/v1.0.0
