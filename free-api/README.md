# Bepul API: NVIDIA NIM, Baseten, OpenRouter

Manba: @Shams.labs "API uchun to'lamasdan ishlang" qo'llanmasi (14 sahifa).

> Bular bepul tier'lar, cheksiz tarif emas. O'rganish, test va prototip uchun yetarli;
> production uchun pullik tarifni rejalashtiring.

## Kim nima beradi

| Provider | Bepul | Limit | Base URL | Model (misol) |
|---|---|---|---|---|
| **NVIDIA NIM** | 100+ model (DeepSeek, Llama, Qwen, Kimi K3, GLM 5.3), bitta key | ~40 request / daqiqa | `https://integrate.api.nvidia.com/v1` | `z-ai/glm-5.3` |
| **Baseten** | $30 kredit (bir martalik), eng yangi open modellar | kredit tugaguncha | Model APIs → endpoint'ni nusxalang | Kimi K3, GLM 5.3 |
| **OpenRouter** | `:free` bilan tugaydigan modellar | 20 / daqiqa, 50 / kun ($10 to'lovdan keyin 1000 / kun) | `https://openrouter.ai/api/v1` | `nvidia/nemotron-3-ultra-550b-a55b:free` |

**Qaysi biridan boshlash:** kundalik ish uchun NVIDIA, yangi modelni sinash uchun Baseten, Claude Code uchun
OpenRouter. Limitga tez urilsangiz, ikkita providerdan key olib, almashtirib ishlating.

Havolalar: build.nvidia.com · baseten.co · openrouter.ai ·
github.com/open-free-llm-api/awesome-freellm-apis (30+ provider ro'yxati) · freellm.net/config (config shablonlari) ·
freellm.net/models (modellar va limitlar).

## Key olish (buni faqat o'zingiz qila olasiz: email va telefon tasdig'i kerak)

**NVIDIA NIM:** build.nvidia.com ga email yoki Google bilan kiring → telefon raqamni tasdiqlang → modelni tanlab
**Get API Key** ni bosing → key'ni maxfiy saqlang.

**Baseten:** baseten.co da workspace yarating ($30 kredit beriladi) → **Model APIs** → model tanlang → endpoint'ni
nusxalang → Workspace settings'da API key yarating. Avval Kimi K3 / GLM 5.3 ni NVIDIA'da bepul sinab ko'ring:
$30 kredit kerakli payt uchun qolsin.

**OpenRouter:** openrouter.ai da ro'yxatdan o'ting → **Keys** bo'limida key yarating → ID'si `:free` bilan
tugaydigan modelni tanlang. `:free` ni tushirib qoldirsangiz, modelning pullik varianti chaqiriladi.

## Ulash

1. `cp free-api/env.example free-api/.env` buyrug'ini bering va key'larni `.env` ga yozing. `.env` git'ga tushmaydi.
2. Tekshirish: `bash free-api/test.sh`. Har bir provider uchun "OK" yoki xato kodi chiqadi.

**Cursor:** Settings → Models → Add Model. Model name: `z-ai/glm-5.3` · Override OpenAI Base URL:
`https://integrate.api.nvidia.com/v1` · OpenAI API Key: NVIDIA key'ingiz → Verify → modelni yoqing.
OpenRouter uchun base URL `https://openrouter.ai/api/v1`, model esa `:free` bilan tugaydigan ID bo'ladi.

**Claude Code:** u faqat Anthropic formatidagi API bilan ishlaydi, shuning uchun OpenRouter orqali ulanadi.
Buni o'z kompyuteringizda qiling:
`bash free-api/claude-code-openrouter.sh` buyrug'ini bering, keyin yangi terminal oching, Claude Code ichida
`/logout` qiling, `claude` ni ishga tushiring va `/status` bilan tekshiring.
Eslatma: OpenRouter Claude Code faqat Claude modellari bilan kafolatli ishlashini yozadi, ular esa pullik.
Bepul modellarda ba'zi funksiyalar ishlamasligi mumkin. To'liq bepul variant kerak bo'lsa, Cursor'dan foydalaning.

**Kichik test** (ulangandan keyin): `utils.ts faylga hello-world funksiya qo'sh va nima qilganingni tushuntir.`
Model javob bersa, tool'lar ishlasa (fayl yaratilsa) va hech qanday to'lov so'ralmasa, ulanish ishlayapti.

## Ishlamasa

- **Key qabul qilinmayapti:** base URL va key bitta providerdan ekanini tekshiring.
- **429 Too Many Requests:** bu limit, key buzilgan emas. Bir daqiqa kuting yoki ishni ikki providerga bo'ling.
- **Model yo'qolib qoldi:** bepul modellar almashib turadi. freellm.net/models dan boshqasini tanlang.
- **Tool config'ni ko'rmayapti:** Claude Code yoki Cursor'ni to'liq yopib, qayta oching.
- **Model nomi:** saytdagidan bitta belgi farq qilsa ham ulanmaydi, shuning uchun nusxalab qo'ying.
- **Baseten pul ola boshladi:** $30 tugagan. NVIDIA yoki OpenRouter'ga o'ting.

## Chek-list

- [ ] Kamida bitta key bor (NVIDIA, Baseten yoki OpenRouter)
- [ ] Base URL, key va model nomi Claude Code yoki Cursor'ga qo'yilgan
- [ ] Tool to'liq yopilib, qayta ochilgan
- [ ] Kichik test to'lov so'ramasdan ishladi
- [ ] Limitingizni bilasiz
- [ ] Key'lar hech kimga berilmagan va GitHub'ga yuklanmagan (`.env` git'ga kirmaydi)
