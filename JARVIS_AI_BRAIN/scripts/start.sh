#!/usr/bin/env bash
# Linux/macOS yoki bulutli ishlab chiqish muhiti uchun
cd "$(dirname "$0")/.." && exec python -m jarvis.api --port "${PORT:-8765}"
