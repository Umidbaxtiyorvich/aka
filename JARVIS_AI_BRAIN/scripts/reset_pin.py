"""Dashboard PIN'ini o'chirish (unutilganda). Faqat shu kompyuterda, terminal orqali ishlaydi.
Keyingi kirishda yangi PIN o'rnatiladi. Ishlayotgan server sessiyalari serverni qayta ishga tushirganda tozalanadi."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from jarvis.config import jarvis_home  # noqa: E402

p = jarvis_home() / "auth.json"
if not p.exists():
    sys.exit("PIN o'rnatilmagan.")
if input("Dashboard PIN o'chirilsinmi? 'ha' deb yozing: ").strip().lower() != "ha":
    sys.exit("Bekor qilindi.")
p.unlink()
print("PIN o'chirildi. JARVIS'ni qayta ishga tushiring va yangi PIN o'rnating.")
