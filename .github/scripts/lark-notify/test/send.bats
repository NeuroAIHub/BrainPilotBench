#!/usr/bin/env bats

SCRIPT="${BATS_TEST_DIRNAME}/../send.sh"

setup() {
  TMP="$(mktemp -d)"
  cat > "$TMP/curl" <<'EOF'
#!/usr/bin/env bash
echo "$@" >> "$ARGS_FILE"
prev=""
for a in "$@"; do
  case "$prev" in
    --data|--data-binary|-d)
      f="${a#@}"; [ -f "$f" ] && cat "$f" > "$BODY_FILE" ;;
  esac
  prev="$a"
done
echo '{"code":0,"msg":"success"}'
EOF
  chmod +x "$TMP/curl"
  export PATH="$TMP:$PATH"
  export ARGS_FILE="$TMP/args" BODY_FILE="$TMP/body"
  unset LARK_NOTIFY_MAX_ATTEMPTS LARK_NOTIFY_BASE_DELAY_SECONDS LARK_NOTIFY_JITTER_SECONDS LARK_NOTIFY_SLEEP_BIN || true
  : > "$ARGS_FILE"; : > "$BODY_FILE"
}

teardown() { rm -rf "$TMP"; }

@test "no secret: body has no timestamp or sign, has card" {
  export LARK_WEBHOOK_URL="https://example.invalid/hook"
  unset LARK_WEBHOOK_SECRET || true
  run bash -c 'echo '\''{"msg_type":"interactive","card":{"x":1}}'\'' | bash "'"$SCRIPT"'"'
  [ "$status" -eq 0 ]
  run cat "$BODY_FILE"
  [ "$(echo "$output" | jq -r '.timestamp // "none"')" = "none" ]
  [ "$(echo "$output" | jq -r '.sign // "none"')" = "none" ]
  [ "$(echo "$output" | jq -r '.msg_type')" = "interactive" ]
}

@test "with secret: body has timestamp and base64 sign" {
  export LARK_WEBHOOK_URL="https://example.invalid/hook"
  export LARK_WEBHOOK_SECRET="mysecret"
  run bash -c 'echo '\''{"msg_type":"interactive","card":{"x":1}}'\'' | bash "'"$SCRIPT"'"'
  [ "$status" -eq 0 ]
  run cat "$BODY_FILE"
  ts="$(echo "$output" | jq -r '.timestamp')"
  sign="$(echo "$output" | jq -r '.sign')"
  [ -n "$ts" ] && [ "$ts" != "null" ]
  [ -n "$sign" ] && [ "$sign" != "null" ]
  echo "$sign" | base64 -d >/dev/null 2>&1
}

@test "posts to configured URL with json content-type" {
  export LARK_WEBHOOK_URL="https://example.invalid/hook"
  unset LARK_WEBHOOK_SECRET || true
  run bash -c 'echo '\''{"msg_type":"interactive","card":{}}'\'' | bash "'"$SCRIPT"'"'
  [ "$status" -eq 0 ]
  grep -q "https://example.invalid/hook" "$ARGS_FILE"
  grep -q "Content-Type: application/json" "$ARGS_FILE"
}

@test "non-zero business code: exits 1" {
  # override the mock curl to return a failure code
  cat > "$TMP/curl" <<'EOF'
#!/usr/bin/env bash
echo '{"code":19021,"msg":"sign match fail"}'
EOF
  chmod +x "$TMP/curl"
  export LARK_WEBHOOK_URL="https://example.invalid/hook"
  unset LARK_WEBHOOK_SECRET || true
  run bash -c 'echo '\''{"msg_type":"interactive","card":{}}'\'' | bash "'"$SCRIPT"'"'
  [ "$status" -eq 1 ]
}

@test "rate limit: retries and then succeeds" {
  echo 0 > "$TMP/count"
  cat > "$TMP/curl" <<EOF
#!/usr/bin/env bash
n=\$(cat "$TMP/count"); n=\$((n+1)); echo "\$n" > "$TMP/count"
if [ "\$n" -eq 1 ]; then echo '{"code":11232,"msg":"frequency limited"}'; else echo '{"code":0,"msg":"success"}'; fi
EOF
  chmod +x "$TMP/curl"
  export LARK_WEBHOOK_URL="https://example.invalid/hook"
  export LARK_NOTIFY_MAX_ATTEMPTS=3 LARK_NOTIFY_BASE_DELAY_SECONDS=0 LARK_NOTIFY_JITTER_SECONDS=0
  run bash -c 'echo '\''{"msg_type":"interactive","card":{}}'\'' | bash "'"$SCRIPT"'"'
  [ "$status" -eq 0 ]
  [ "$(cat "$TMP/count")" -eq 2 ]
}

@test "retry_after: uses the server hint" {
  echo 0 > "$TMP/count"
  cat > "$TMP/curl" <<EOF
#!/usr/bin/env bash
n=\$(cat "$TMP/count"); n=\$((n+1)); echo "\$n" > "$TMP/count"
if [ "\$n" -eq 1 ]; then echo '{"code":11232,"retry_after":3}'; else echo '{"code":0}'; fi
EOF
  cat > "$TMP/sleep" <<EOF
#!/usr/bin/env bash
echo "\$1" >> "$TMP/sleeps"
EOF
  chmod +x "$TMP/curl" "$TMP/sleep"
  export LARK_WEBHOOK_URL="https://example.invalid/hook"
  export LARK_NOTIFY_MAX_ATTEMPTS=2 LARK_NOTIFY_BASE_DELAY_SECONDS=0 LARK_NOTIFY_JITTER_SECONDS=0
  export LARK_NOTIFY_SLEEP_BIN="$TMP/sleep"
  run bash -c 'echo '\''{"msg_type":"interactive","card":{}}'\'' | bash "'"$SCRIPT"'"'
  [ "$status" -eq 0 ]
  [ "$(cat "$TMP/sleeps")" = "3" ]
}

@test "rate limit: fails after bounded attempts" {
  echo 0 > "$TMP/count"
  cat > "$TMP/curl" <<EOF
#!/usr/bin/env bash
n=\$(cat "$TMP/count"); n=\$((n+1)); echo "\$n" > "$TMP/count"
echo '{"code":11232,"msg":"frequency limited"}'
EOF
  chmod +x "$TMP/curl"
  export LARK_WEBHOOK_URL="https://example.invalid/hook"
  export LARK_NOTIFY_MAX_ATTEMPTS=3 LARK_NOTIFY_BASE_DELAY_SECONDS=0 LARK_NOTIFY_JITTER_SECONDS=0
  run bash -c 'echo '\''{"msg_type":"interactive","card":{}}'\'' | bash "'"$SCRIPT"'"'
  [ "$status" -eq 1 ]
  [ "$(cat "$TMP/count")" -eq 3 ]
}
