# Keyingi bosqichlar

Har bir bosqich tartibi: kod → testlar → haqiqiy ishga tushirib tekshirish → commit.

## Bajarilgan
- 0.1: Core, Memory, Audit, Approval, 6 agent.
- 0.2: BI, POS (file_export), Telegram, Instagram, Research, Studio, Voice, Browser, Planner, Notifications, Self-improvement.

## Sizdan ma'lumot kerak
1. **POS manzili** — brauzer agenti bilan faqat o'qish rejimida o'rganiladi, keyin `api` yoki `browser` konnektori yoziladi.
2. **GPU/VRAM** (`check_system.ps1` natijasi) — shunga qarab Ollama modeli tanlanadi va real sinov o'tkaziladi.
3. **Telegram va Instagram** — siz token kiritganingizdan keyin real xizmat bilan sinaladi.

## Texnik reja
- Dashboard uchun lokal autentifikatsiya (PIN yoki parol). Bu tarmoqqa ochishdan oldin shart.
- Planner'ni AI bilan kuchaytirish (Ollama ulangach).
- Self-improvement: xatolar jurnalidan AI yordamida patch loyihasi.
- Instagram: rejalashtirilgan postlarni vaqtida nashrga tayyorlash (har biri baribir tasdiq bilan).
- Telefon qo'ng'irog'i provayder adapteri (siz provayder va narxni tanlagandan keyin).
