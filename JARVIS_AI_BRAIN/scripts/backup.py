"""JARVIS zaxira nusxalari (terminal orqali).

  python scripts/backup.py create            — yangi nusxa (+ tekshiruv)
  python scripts/backup.py list              — ro'yxat
  python scripts/backup.py verify NOM        — yaxlitlik va sinov-tiklash
  python scripts/backup.py restore NOM       — tiklash (nomni qayta yozib tasdiqlaysiz; oldin xavfsizlik nusxasi olinadi)
Batafsil: docs/BACKUP.md
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from jarvis.core import JarvisCore  # noqa: E402


def main(argv):
    if not argv or argv[0] not in ("create", "list", "verify", "restore"):
        sys.exit(__doc__)
    core = JarvisCore()
    bm = core.backup
    if argv[0] == "create":
        r = bm.create(label="cli")
        v = bm.verify(r["name"])
        print(f"Yaratildi: {r['name']} ({r['size']} bayt) — tekshiruv: {'OK' if v['ok'] else 'XATO'}")
        return 0 if v["ok"] else 1
    if argv[0] == "list":
        for i in bm.list():
            print(f"{i['name']}  {i['size']:>10} bayt  {i['label']}  tekshiruv: {i['last_verify']}")
        return 0
    if len(argv) < 2:
        sys.exit("Nusxa nomini kiriting")
    if argv[0] == "verify":
        v = bm.verify(argv[1])
        for c in v["checks"]:
            print(("OK  " if c["ok"] else "XATO") + f"  {c['check']} {c['note']}")
        return 0 if v["ok"] else 1
    print(f"DIQQAT: joriy ma'lumotlar {argv[1]} holatiga qaytariladi. Undan keyingi o'zgarishlar yo'qoladi.")
    if input("Tasdiqlash uchun nusxa nomini qayta yozing: ").strip() != argv[1]:
        print("Bekor qilindi.")
        return 1
    appr = bm.request_restore(argv[1])
    core.approvals.decide(appr["id"], True, appr["payload_hash"])   # terminaldagi aniq tasdiq
    r = bm.restore(argv[1], appr["id"])
    print(f"Tiklandi. Oldingi holat nusxasi: {r['safety_backup']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
