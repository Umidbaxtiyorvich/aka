#!/usr/bin/env bash
# Har bir provider'ga bitta kichik so'rov yuboradi va natijani ko'rsatadi.
# Ishlatish: bash free-api/test.sh   (key'lar free-api/.env da bo'lishi kerak)
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$DIR/.env" ]; then set -a; . "$DIR/.env"; set +a; else
  echo "free-api/.env topilmadi: cp free-api/env.example free-api/.env va key'larni yozing"; exit 1; fi

test_provider() { # name key base model
  local name="$1" key="$2" base="$3" model="$4"
  if [ -z "$key" ] || [ -z "$model" ]; then echo "[$name] o'tkazib yuborildi (key yoki model yo'q)"; return; fi
  local out code
  out=$(curl -sS -w '\n%{http_code}' "$base/chat/completions" \
    -H "Authorization: Bearer $key" -H "Content-Type: application/json" \
    -d "{\"model\":\"$model\",\"max_tokens\":20,\"messages\":[{\"role\":\"user\",\"content\":\"Salom! Bir so'z bilan javob ber.\"}]}")
  code=$(printf '%s' "$out" | tail -n1)
  case "$code" in
    200) echo "[$name] OK ($model)";;
    401|403) echo "[$name] $code: key noto'g'ri yoki base URL boshqa providerniki";;
    404) echo "[$name] 404: model nomi noto'g'ri yoki model olib tashlangan (freellm.net/models)";;
    429) echo "[$name] 429: limit. Bir daqiqa kuting";;
    *) echo "[$name] $code: $(printf '%s' "$out" | head -n -1 | head -c 300)";;
  esac
}

test_provider NVIDIA     "${NVIDIA_API_KEY:-}"     "${NVIDIA_BASE_URL:-}"     "${NVIDIA_MODEL:-}"
test_provider OpenRouter "${OPENROUTER_API_KEY:-}" "${OPENROUTER_BASE_URL:-}" "${OPENROUTER_MODEL:-}"
test_provider Baseten    "${BASETEN_API_KEY:-}"    "${BASETEN_BASE_URL:-}"    "${BASETEN_MODEL:-}"
