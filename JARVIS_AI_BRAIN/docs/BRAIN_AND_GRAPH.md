# 3D Brain Mode va Graph Explorer Mode

Ikki rejim bitta sahifada ishlaydi. Ular yuqoridagi tugmalar bilan almashtiriladi: **🧠 3D BRAIN MODE** va **🌐 GRAPH EXPLORER MODE**. Almashganda sahifa qayta yuklanmaydi, tanlangan tugun va filtrlar saqlanadi. Ikkala rejim bir xil backend ma'lumotidan foydalanadi.

## Texnologiya va nima uchun aynan shu
- Dashboard oddiy JavaScript'da yozilgan, React yo'q. Uni qayta yozmaslik uchun **Three.js r160** (MIT) to'g'ridan-to'g'ri ishlatildi.
- Three.js `dashboard/vendor/three/` ichida turadi, ya'ni **internetsiz ham ishlaydi**. U faqat shu sahifalar ochilganda yuklanadi.
- Graf alohida kutubxonasiz qurilgan, Three.js'ning nuqta va chiziqlari bilan chiziladi:
  - joylashuv (force layout) **Web Worker**'da hisoblanadi, shuning uchun interfeys qotmaydi;
  - itarilish kuchi tasodifiy namunalar bilan taxminiy hisoblanadi (O(N·S)), shuning uchun minglab tugunlar ham sig'adi.
- Real vaqt **Server-Sent Events** (`/api/events/stream`) orqali ishlaydi. Uvicorn'ning o'zi yetadi, qo'shimcha `websockets` kutubxonasi kerak emas.
- Aloqa uzilsa, **OFFLINE** belgisi va ogohlantirish chiqadi. EventSource o'zi qayta ulanadi.

## 3D miya qanday yaratilgan
Bu **protsedura yo'li bilan yaratilgan model**, ya'ni skaner qilingan anatomik model emas. Interfeysda ham shunday yozilgan.

Tarkibi:
- **Ikki yarim shar.** Sferadan miya shakliga keltirilgan: peshona va chakka bo'laklari, tekis pastki qism, medial tekislik.
- **Burmalar (giruslar) va egatlar (sulkuslar).** Ko'p oktavali "ridged" shovqin bilan yasalgan, markaziy (Rolando) va lateral (Silviy) egatlar alohida.
- **Miyacha** varaqchalari bilan va **miya ustuni**.
- **Neyronlar va sinapslar.** Ular hajm ichida joylashgan nuqtalar va chiziqlar.

Hududlarning hammasi JARVIS **dasturiy modullarining vizual ifodasi**, biologik miya simulyatsiyasi emas:
- Memory Center
- Reasoning Center
- Planning Center
- Language Center
- Vision Center
- Creative Center
- Agent Control Center
- Security Center

Hududni bosganda quyidagilar ochiladi (`/api/brain/region/{id}`):
- holat;
- agentlar;
- faol vazifalar;
- ishlatilayotgan model;
- oxirgi ishlar (audit jurnalidan);
- shu hududga tegishli xatolar soni.

### Jonli faoliyat — faqat haqiqiy hodisalardan
| Backend hodisasi | Miyada |
|---|---|
| `ai.start` / `ai.end` (Router) | Reasoning + Language hududlari faollashadi |
| `memory.search` | Memory → Reasoning yo'li yoritiladi |
| `memory.add` | Memory'da yangi oltin rang aloqa paydo bo'ladi |
| `task.start` / `task.end` | Agentga tegishli hudud faollashadi |
| `error` | Security hududi qizaradi, miya qisqa vaqt ogohlantirish rangida yonadi |
| `approval` | Security hududi oltin rangda yonadi |

Hodisa bo'lmasa, miya tinch turadi. Sekin "nafas" pulsatsiyasi faqat bezak va bu interfeysda yozilgan.

## Graph Explorer
- **Ma'lumot.** `kg_nodes` / `kg_edges` jadvallaridan olinadi. Har tugun haqiqiy yozuvni bildiradi: xotira, loyiha, fayl, vazifa, agent, suhbat, qaror, ko'nikma, xato, taklif yoki test, API, Instagram, Telegram, biznes ma'lumoti.
- **Kategoriyalar.** 15 ta, har birining o'z rangi va belgisi bor.
- **Yangilash.** "Knowledge Graph → qayta qurish" tugmasi barcha jadvallardan tugun yaratadi.
- **Imkoniyatlar:**
  - global qidiruv;
  - kategoriya, sana va manba bo'yicha filtr;
  - tanlangan tugun atrofi (faqat bog'langanlar);
  - ikki tugun orasidagi yo'l;
  - aloqalarni yashirish yoki ko'rsatish;
  - to'liq ekran;
  - PNG va SVG eksport;
  - batafsil panel va tegishli bo'limga o'tish.
- **Katta graflar.**
  - Tugunlar sahifalab, 2000 tadan yuklanadi.
  - Sifat chegarasi: Low 2000, Medium 5000, High 10000 tugun.
  - Yozuvlar faqat eng ko'p bog'langan va tanlangan tugunlarda chiqadi, ustma-ust tushmaydi.
- **Rejimlararo bog'lanish.**
  - Graf tugunidagi "🧠 3D'da" tugmasi tegishli hududni yoritadi.
  - 3D hududidagi "🌐 Graph'da ko'rish" tugmasi shu hududning kategoriyalari bilan filtrlaydi.
  - Memory Explorer'dagi "🌐 Graph'da" tugmasi aynan o'sha tugunni tanlab ochadi.

## Memory Explorer va Memory Connection Engine
- **Toifalar:**
  - Short-term, Long-term, Working, Episodic, Semantic, Project va Technical Memory;
  - User-approved Preferences — faqat foydalanuvchi kiritadi, AI yoki modul kiritolmaydi;
  - shuningdek mavjud Knowledge, Task, Decision va Conversation toifalari.
- **Imkoniyatlar:** qidirish, ko'rish, tahrirlash (nomi, mazmuni, toifasi), JSON eksport. O'chirish faqat tasdiqlash oynasi orqali.
- **Ziddiyatlar** birlashtirilmaydi, "⚠ ziddiyat" deb ko'rsatiladi.
- **Yangi ma'lumot qo'shilganda Connection Engine:**
  1. turini aniqlaydi;
  2. o'xshash xotiralarni topadi;
  3. tegishli loyihani aniqlaydi;
  4. takrorlar (o'xshashlik ≥ 0.9) yangi yozuv sifatida saqlanmaydi;
  5. o'xshashlik ≥ 0.6 bo'lsa, avtomatik aloqa yaratadi;
  6. o'xshashlik 0.3–0.6 bo'lsa, aloqani **taklif** qiladi va u sizning tasdig'ingizni kutadi.
- **"Tahlil qilish"** tugmasi saqlashdan oldin nima bo'lishini ko'rsatadi.

## Ishlash tezligi (8 GB RAM)
- **Sifat rejimlari.** Low, Medium va High tanlovi geometriya aniqligiga, neyronlar soniga, piksel zichligiga va grafdagi tugunlar chegarasiga ta'sir qiladi.
- **FPS monitoring.** FPS bir necha soniya davomida 18 dan past bo'lsa, miya avtomatik **2D rejimga** o'tadi. WebGL umuman yo'q bo'lsa ham 2D rejim ishlaydi.
- **Resurs tejash.**
  - Yashirin tabda chizish to'xtaydi.
  - Bo'limdan chiqilganda sahna, worker va tinglovchilar tozalanadi, shuning uchun xotira sizib chiqmaydi.
  - Eskirgan so'rov natijalari tashlab yuboriladi (avlod hisoblagichi).

## API
`/api/brain/state`, `/api/brain/region/{id}`, `/api/events/stream` (SSE), `/api/events/recent`, `/api/kg/graph`, `/api/kg/find`, `/api/kg/path`,
`/api/memory/categories`, `/api/memory/explore`, `/api/memory/{id}/related`, `/api/memory/analyze`, `/api/memory/ingest`, `/api/memory/suggestions`, `/api/memory/duplicates`.
