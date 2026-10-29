# JARVIS kengaytmalari

Har bir kengaytma alohida papkada joylashadi:

```
plugins/<nom>/plugin.json   — manifest
plugins/<nom>/main.py       — def run(input: dict, ctx: dict) -> dict
```

Manifest namunasi:

```json
{
  "name": "narx_kalkulyator",
  "version": "1.0.0",
  "description": "...",
  "entry": "main.py",
  "permissions": [],
  "dependencies": [],
  "config": {"vat_percent": {"type": "number", "default": 12, "required": true, "description": "QQS %"}}
}
```

## Ruxsatlar

Faqat kerakli ruxsatlarni so'rang:

| Ruxsat | Nima beradi |
|---|---|
| `memory.read` | `input.query` bo'yicha qidiruv natijalari `ctx.memory` ga beriladi |
| `memory.write` | `{"type": "memory.write", "content": ...}` amali bilan xotiraga yozish |
| `notify` | `{"type": "notify", "title": ..., "body": ...}` amali bilan bildirishnoma yuborish |
| `network` | sandbox ichida internetga chiqish |

## Ishga tushirish tartibi

1. Dashboard → Kengaytmalar → "Qayta skanerlash".
2. "Yoqishni so'rash" → Tasdiqlashlar bo'limida tasdiqlang.
3. Qaytib, "Yoqish" tugmasini bosing.

## Xavfsizlik

- Kengaytma fayllari tasdiqdan keyin o'zgarsa, u `untrusted` holatiga o'tadi va qayta tasdiqlanmaguncha ishlamaydi.
- Kod JARVIS jarayonida emas, sandbox ichida ishlaydi.
