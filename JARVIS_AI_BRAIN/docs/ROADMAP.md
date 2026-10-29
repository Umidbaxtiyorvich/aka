# Keyingi bosqichlar

Har bir bosqich tartibi: kod → testlar → haqiqiy ishga tushirib tekshirish → commit.

## Bajarilgan
- 0.1: Core, Memory, Audit, Approval, 6 agent.
- 0.2: BI, POS (file_export), Telegram, Instagram, Research, Studio, Voice, Browser, Planner, Notifications, Self-improvement.

- 0.3: Router, Cost Guard, Policy, Provenance, Decisions, Sandbox, Backup, DAG, Knowledge Graph, Plugins, Diagnostics, Release gate.
- 0.4: Instagram Reels/Direct/rejali postlar, PIN + Host/Origin himoyasi, dastur ochish, Whisper subtitr, espeak-ng TTS,
  AI planner va AI patch taklifi, SD/vision adapterlari, POS REST, Twilio, BI Excel, Windows autostart.

## Sizdan ma'lumot kerak
1. **POS manzili** — brauzer agenti bilan faqat o'qish rejimida o'rganiladi, keyin `api` yoki `browser` konnektori yoziladi.
2. **GPU/VRAM** (`check_system.ps1` natijasi) — shunga qarab Ollama modeli tanlanadi va real sinov o'tkaziladi.
3. **Telegram va Instagram** — siz token kiritganingizdan keyin real xizmat bilan sinaladi.

## Texnik reja
- POS brauzer konnektori (yozish) — POS sayti ma'lum bo'lgach, faqat o'qish tahlilidan keyin.
- HTTPS (agar dashboard tarmoqqa ochilsa).
- Windows'da real sinov: Ollama, espeak-ng, Whisper, autostart.
