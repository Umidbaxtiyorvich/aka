#!/usr/bin/env bash
# Claude Code'ni OpenRouter orqali ishlatish uchun shell sozlamasini qo'shadi (o'z kompyuteringizda ishga tushiring).
# Key free-api/.env dagi OPENROUTER_API_KEY dan olinadi. Bekor qilish: rc fayldagi "# >>> openrouter" blokini o'chiring.
set -eu
DIR="$(cd "$(dirname "$0")" && pwd)"
[ -f "$DIR/.env" ] && { set -a; . "$DIR/.env"; set +a; }
KEY="${OPENROUTER_API_KEY:-}"
[ -n "$KEY" ] || { read -r -s -p "OpenRouter key (sk-or-v1-...): " KEY; echo; }
case "${SHELL:-}" in *zsh) RC="$HOME/.zshrc";; *) RC="$HOME/.bashrc";; esac
if grep -q '# >>> openrouter' "$RC" 2>/dev/null; then echo "$RC da allaqachon bor."; exit 0; fi
cat >> "$RC" <<EOF

# >>> openrouter (Claude Code)
export ANTHROPIC_BASE_URL="https://openrouter.ai/api"
export ANTHROPIC_AUTH_TOKEN="$KEY"
export ANTHROPIC_API_KEY=""
# <<< openrouter
EOF
echo "Qo'shildi: $RC. Yangi terminal oching, Claude Code ichida /logout qiling, keyin 'claude' va /status."
