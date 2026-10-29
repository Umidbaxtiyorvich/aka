"""Matndagi 'YYYY-MM-DD ...' qatorlarini eslatma sifatida ajratadi."""
import re


def run(input, ctx):
    found = re.findall(r"(\d{4}-\d{2}-\d{2})\s*[:\-]?\s*(.+)", input.get("text", ""))
    actions = [{"type": "memory.write", "content": f"Eslatma {d}: {t.strip()}"} for d, t in found]
    if found:
        actions.append({"type": "notify", "title": f"{len(found)} ta eslatma topildi", "body": "; ".join(d for d, _ in found)})
    return {"result": {"reminders": [{"date": d, "text": t.strip()} for d, t in found]}, "actions": actions}
