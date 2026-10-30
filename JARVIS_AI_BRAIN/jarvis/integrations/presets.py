"""POS / ERP / CRM andozalari (preset). Har biri: qaysi adapter, oldindan to'ldirilgan maydonlar va HALOL izoh.

Muhim: hech bir preset real tizimga ulanib tekshirilmagan (bulut muhitida ularning hisoblari yo'q). Andoza faqat
boshlang'ich sozlama beradi; haqiqiy ulanish "Ulanishni tekshirish" muvaffaqiyatli bo'lgandagina tasdiqlanadi.
"""
PRESETS = {
    "yespos": {"title": "YesPOS", "system_type": "pos", "adapter": "website",
               "config": {"base_url": "https://app.yespos.uz", "pages": "https://app.yespos.uz/reports"},
               "note": "Ommaviy API topilmadi — veb-panel orqali (login + hisobot jadvallarini o'qish). Alternativa: Excel eksport → Fayl importi."},
    "bito": {"title": "BITO ERP", "system_type": "erp", "adapter": "website", "config": {},
             "note": "Manzilni o'zingiz kiriting (BITO hisobingizdagi panel manzili). API hujjati bo'lsa — REST adapterini tanlang."},
    "1c_ut": {"title": "1C: Управление торговлей / магазином", "system_type": "erp", "adapter": "odata",
              "config": {"base_url": "https://server/baza/odata/standard.odata",
                         "entity_sets": "Catalog_Номенклатура,Document_ЧекККМ,Document_РеализацияТоваровУслуг,AccumulationRegister_ТоварыНаСкладах"},
              "note": "1C'da 'standart OData interfeysi' veb-serverda e'lon qilingan bo'lishi kerak (administrator sozlaydi). "
                      "Bo'lmasa — MS SQL/PostgreSQL bazasiga read-only ulanish yoki Excel eksport."},
    "info_enterprise": {"title": "Info-Enterprise Trade", "system_type": "erp", "adapter": "database", "config": {"engine": "mssql"},
                        "note": "Odatda lokal SQL bazasi bilan ishlaydi — administrator bergan read-only foydalanuvchi bilan bazaga ulaning "
                                "(drayver: pyodbc). Bo'lmasa — hisobotni Excel'ga eksport qilib Fayl importi."},
    "cloudshop": {"title": "CloudShop", "system_type": "pos", "adapter": "rest", "config": {"auth_type": "bearer"},
                  "note": "API manzili va token CloudShop kabinetidan olinadi; obyektlar yo'llarini API hujjatidan kiriting. Tekshirilmagan andoza."},
    "generic_rest": {"title": "Boshqa POS/ERP/CRM (REST API)", "system_type": "pos", "adapter": "rest", "config": {"auth_type": "bearer"}, "note": ""},
    "generic_web": {"title": "Boshqa sayt / web panel", "system_type": "website", "adapter": "website", "config": {}, "note": ""},
    "generic_db": {"title": "Ma'lumotlar bazasi", "system_type": "database", "adapter": "database", "config": {"engine": "postgresql"}, "note": ""},
    "mcp": {"title": "MCP Server", "system_type": "mcp", "adapter": "mcp", "config": {}, "note": ""},
    "files": {"title": "Fayllar (CSV/Excel/JSON/XML)", "system_type": "files", "adapter": "files", "config": {}, "note": ""},
    "desktop": {"title": "Kompyuterdagi dasturlar (Windows)", "system_type": "desktop", "adapter": "desktop", "config": {},
                "note": "O'rnatilgan dasturlar, jarayonlar va lokal portlarni faqat o'qiydi. UI Automation bu versiyada yo'q."},
}
