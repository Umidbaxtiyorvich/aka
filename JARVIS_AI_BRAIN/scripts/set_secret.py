"""Maxfiy kalitni Windows Credential Manager'ga (yoki OS keyring'ga) xavfsiz kiritish.
Ishlatish: python scripts/set_secret.py telegram_bot_token
Qiymat ekranda ko'rinmaydi va hech qayerga (log, Git, SQLite) yozilmaydi."""
import getpass
import sys

import keyring

SERVICE = "JARVIS_AI_BRAIN"

if len(sys.argv) != 2:
    sys.exit("Ishlatish: python scripts/set_secret.py <kalit_nomi>")
name = sys.argv[1]
value = getpass.getpass(f"{name} qiymatini kiriting (ko'rinmaydi): ")
if not value:
    sys.exit("Bo'sh qiymat — hech narsa saqlanmadi.")
keyring.set_password(SERVICE, name, value)
print(f"Saqlandi: {SERVICE}/{name}")
