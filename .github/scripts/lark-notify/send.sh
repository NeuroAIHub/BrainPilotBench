#!/usr/bin/env bash
# 从 stdin 读卡片 JSON，按需签名，POST 到飞书自定义机器人。失败退出非 0。
set -euo pipefail

URL="${LARK_WEBHOOK_URL:?LARK_WEBHOOK_URL required}"
SECRET="${LARK_WEBHOOK_SECRET:-}"

CARD_JSON="$(cat)"

if [ -n "$SECRET" ]; then
  TS="$(date +%s)"
  # 飞书签名：HMAC-SHA256，key = "<timestamp>\n<secret>"，data 为空，结果 base64
  STRING_TO_SIGN="${TS}"$'\n'"${SECRET}"
  SIGN="$(printf '%s' "" | openssl dgst -sha256 -hmac "$STRING_TO_SIGN" -binary | base64)"
  PAYLOAD="$(jq -n --arg ts "$TS" --arg sign "$SIGN" --argjson card "$CARD_JSON" \
    '$card + { timestamp: $ts, sign: $sign }')"
else
  PAYLOAD="$CARD_JSON"
fi

REQ_BODY_FILE="$(mktemp)"
trap 'rm -f "$REQ_BODY_FILE"' EXIT
printf '%s' "$PAYLOAD" > "$REQ_BODY_FILE"

MAX_ATTEMPTS="${LARK_NOTIFY_MAX_ATTEMPTS:-4}"
BASE_DELAY="${LARK_NOTIFY_BASE_DELAY_SECONDS:-2}"
JITTER="${LARK_NOTIFY_JITTER_SECONDS:-1}"
SLEEP_BIN="${LARK_NOTIFY_SLEEP_BIN:-sleep}"
for value in "$MAX_ATTEMPTS" "$BASE_DELAY" "$JITTER"; do
  [[ "$value" =~ ^[0-9]+$ ]] || { echo "invalid retry setting: $value" >&2; exit 1; }
done
[ "$MAX_ATTEMPTS" -ge 1 ] || { echo "LARK_NOTIFY_MAX_ATTEMPTS must be >= 1" >&2; exit 1; }

attempt=1
while true; do
  transport_failed=0
  if ! RESP="$(curl -sS -m 15 -X POST "$URL" \
    -H 'Content-Type: application/json' \
    --data-binary "@$REQ_BODY_FILE")"; then
    transport_failed=1
    RESP='{"code":"transport_error","msg":"curl failed"}'
  fi

  printf '飞书响应(attempt %s/%s): %s\n' "$attempt" "$MAX_ATTEMPTS" "$RESP" >&2
  if ! CODE="$(printf '%s' "$RESP" | jq -r '.code // .StatusCode // "missing"' 2>/dev/null)"; then
    echo "推送失败：响应非合法 JSON" >&2
    exit 1
  fi
  [ "$CODE" = "0" ] && exit 0

  retryable=0
  [ "$transport_failed" -eq 1 ] && retryable=1
  case "$CODE" in
    11232|429|frequency_limited) retryable=1 ;;
  esac
  if [ "$retryable" -ne 1 ] || [ "$attempt" -ge "$MAX_ATTEMPTS" ]; then
    echo "推送失败，code=${CODE}，attempts=${attempt}" >&2
    exit 1
  fi

  retry_after="$(printf '%s' "$RESP" | jq -r '.retry_after // .data.retry_after // .RetryAfter // empty' 2>/dev/null || true)"
  if [[ "$retry_after" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
    delay="$retry_after"
  else
    delay=$((BASE_DELAY * (2 ** (attempt - 1))))
    if [ "$JITTER" -gt 0 ]; then delay=$((delay + RANDOM % (JITTER + 1))); fi
  fi
  echo "飞书限流/传输失败，${delay}s 后重试" >&2
  if [ "$delay" != "0" ] && [ "$delay" != "0.0" ]; then "$SLEEP_BIN" "$delay"; fi
  attempt=$((attempt + 1))
done
