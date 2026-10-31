#!/usr/bin/env bash
# End-to-end check of the release APK on an Android emulator, against the live backend.
#   1. install, grant CAMERA + RECORD_AUDIO, launch: the app must start without a crash
#   2. tap the screen: photo from the emulator camera -> POST /scan -> GET /scan/{id} -> spoken answer
#   3. tap Ask, wait, tap again: recording -> POST /intent -> spoken answer
#   4. hold the screen (the other way to ask): same round trip
#   5. switch to Amharic (Oromo must not be offered), scan, then ask by voice: the request carries
#      lang=am and the app stays in Amharic whatever the answer says
# Each answer must come from the backend, never the app's "cannot reach the server" prompt.
# Output: e2e-out/ (screenshots, uiautomator dumps, logcat). Exit code != 0 on any failure.
set -uo pipefail

APK=${1:?apk path}
PKG=com.sgfhnn.birr
OUT=e2e-out
mkdir -p "$OUT"
FAIL=0
NO_NET='cannot reach the server'

log() { echo "[e2e $(date -u +%H:%M:%S)] $*"; }
fail() { echo "::error::$*"; log "FAIL: $*"; FAIL=1; }
shot() { adb exec-out screencap -p > "$OUT/$1.png" || true; }
dump() {
  # The camera preview can keep the UI from going idle; retry a few times.
  for _ in 1 2 3; do
    if adb shell uiautomator dump /sdcard/ui.xml >/dev/null 2>&1 && adb pull /sdcard/ui.xml "$OUT/$1.xml" >/dev/null 2>&1; then
      grep -o 'text="[^"]*"' "$OUT/$1.xml" | sed 's/^text="//;s/"$//' | grep -v '^$' > "$OUT/$1.txt"
      return 0
    fi
    sleep 1
  done
  echo "(uiautomator dump failed)" > "$OUT/$1.txt"
  return 1
}
JSLOG="$OUT/logcat-js.txt" # streamed by a background `adb logcat` from launch on
# Wait until the JS log shows a line matching $1 after line $3, or $2 seconds pass.
wait_js() {
  local pattern=$1 deadline=$((SECONDS + $2)) since=$3
  while ((SECONDS < deadline)); do
    tail -n +"$since" "$JSLOG" 2>/dev/null | grep -qE "$pattern" && return 0
    dismiss_dialogs
    sleep 2
  done
  return 1
}
jslines() { echo $(($(wc -l < "$JSLOG") + 1)); }
# The last "screen:" message after line $1.
screen_after() { tail -n +"$1" "$JSLOG" | grep -o '\[birr\] screen: .*' | tail -1 | sed 's/^\[birr\] screen: //'; }
# CI emulators are slow and Android shows "System UI isn't responding" / "X isn't responding"
# dialogs over the app. Answer "Wait" so taps reach the app.
dismiss_dialogs() {
  adb shell uiautomator dump /sdcard/anr.xml >/dev/null 2>&1 || return 0
  local xml b x1 y1 x2 y2
  xml=$(adb shell cat /sdcard/anr.xml 2>/dev/null)
  if grep -q "isn't responding" <<<"$xml"; then
    b=$(grep -o 'text="Wait"[^>]*bounds="\[[0-9]*,[0-9]*\]\[[0-9]*,[0-9]*\]"' <<<"$xml" | grep -oE '\[[0-9]+,[0-9]+\]\[[0-9]+,[0-9]+\]' | head -1)
    if [ -n "$b" ]; then
      read -r x1 y1 x2 y2 <<<"$(echo "$b" | tr -c '0-9' ' ')"
      log "dismissing an ANR dialog (Wait)"
      adb shell input tap $(((x1 + x2) / 2)) $(((y1 + y2) / 2))
      sleep 1
    fi
  fi
}

log "runner public IP: $(curl -s -m 10 https://api.ipify.org || echo unknown)"
log "start (UTC): $(date -u +%FT%TZ)"
adb shell getprop ro.build.version.release
adb shell getprop ro.product.cpu.abilist
SIZE=$(adb shell wm size | grep -oE '[0-9]+x[0-9]+' | tail -1)
W=${SIZE%x*}; H=${SIZE#*x}
log "screen ${W}x${H}"

log "install $APK"
adb install -r -g "$APK" || { fail "install failed"; exit 1; }
adb shell pm grant $PKG android.permission.CAMERA
adb shell pm grant $PKG android.permission.RECORD_AUDIO
adb shell dumpsys package $PKG | grep -E 'android.permission.(CAMERA|RECORD_AUDIO|INTERNET)' | tee "$OUT/permissions.txt"
grep -q 'RECORD_AUDIO: granted=true' "$OUT/permissions.txt" || fail "RECORD_AUDIO not granted (missing from manifest?)"

adb shell settings put global hide_error_dialogs 1 || true
dismiss_dialogs
adb logcat -c
adb logcat -v time -s ReactNativeJS:V AndroidRuntime:E > "$JSLOG" 2>/dev/null &
LOGCAT_PID=$!
log "launch"
adb shell monkey -p $PKG -c android.intent.category.LAUNCHER 1 >/dev/null
# The welcome line is the first message, logged once the JS is running.
if wait_js '\[birr\] screen:' 90 1; then log "JS running"; else fail "app JS never started"; fi
sleep 8 # camera ready + welcome
dismiss_dialogs
shot 01-launched
dump 01-launched
cat "$OUT/01-launched.txt"
if ! adb shell pidof $PKG >/dev/null; then fail "app not running after launch (crash)"; fi
grep -q 'Count money' "$OUT/01-launched.xml" 2>/dev/null || log "warning: 'Count money' control not in dump"

# ---- scan: tap the big area (middle of the screen, above the Ask button)
log "scan: tap ${W}/2 x ${H}*4/10"
dismiss_dialogs
SINCE=$(jslines)
adb shell input tap $((W / 2)) $((H * 4 / 10))
sleep 3
shot 02-counting
if wait_js '\[birr\] POST /scan' 60 "$SINCE"; then log "POST /scan answered"; else fail "POST /scan never answered (or never sent)"; fi
if wait_js 'GET /scan/.* (done|error)|POST /scan -> 200|scan failed' 120 "$SINCE"; then log "scan job finished"; else fail "scan job never finished"; fi
sleep 3
shot 03-scan-answer
dump 03-scan-answer
MSG=$(screen_after "$SINCE")
log "scan answer on screen: $MSG"
echo "$MSG" > "$OUT/scan-answer.txt"
case "$MSG" in
  *"$NO_NET"*) fail "scan: app says it cannot reach the server" ;;
  ""|"Counting."|*"could not count that"*) fail "scan: no backend answer on screen ($MSG)" ;;
esac
tail -n +"$SINCE" "$JSLOG" | grep -q 'GET /scan/' || fail "scan: job was never polled"

# ---- voice: Ask button (tap, speak, tap again)
sleep 4
ASK=$(grep -o 'content-desc="Ask a question"[^>]*bounds="\[[0-9]*,[0-9]*\]\[[0-9]*,[0-9]*\]"' "$OUT/03-scan-answer.xml" 2>/dev/null | grep -oE '\[[0-9]+,[0-9]+\]\[[0-9]+,[0-9]+\]' | head -1)
if [ -n "$ASK" ]; then
  read -r X1 Y1 X2 Y2 <<<"$(echo "$ASK" | tr -c '0-9' ' ')"
  AX=$(((X1 + X2) / 2)); AY=$(((Y1 + Y2) / 2))
else
  log "Ask bounds not found in dump, guessing"
  AX=$((W / 2)); AY=$((H * 78 / 100))
fi
log "voice (Ask button): tap $AX,$AY, wait 3 s, tap again"
dismiss_dialogs
SINCE=$(jslines)
adb shell input tap $AX $AY
sleep 3
shot 04-listening
dump 04-listening
adb shell input tap $AX $AY
if wait_js '\[birr\] POST /intent|intent failed' 60 "$SINCE"; then log "intent request finished"; else fail "POST /intent never answered (or never sent)"; fi
sleep 3
shot 05-intent-answer
dump 05-intent-answer
MSG=$(screen_after "$SINCE")
log "intent answer on screen: $MSG"
echo "$MSG" > "$OUT/intent-answer.txt"
tail -n +"$SINCE" "$JSLOG" | grep -qE 'POST /intent( lang=[a-z]+)? -> 200' || fail "intent: no 200 from POST /intent"
case "$MSG" in
  *"$NO_NET"*) fail "intent: app says it cannot reach the server" ;;
  ""|"Listening."|*"Hold the screen"*|*"allow the microphone"*) fail "intent: no backend answer on screen ($MSG)" ;;
esac

# ---- voice: hold the screen 3 s and let go
sleep 4
# 7.5 s (the app stops by itself at 8 s): the CI emulator can take several seconds to start the
# recorder (logged as "recording started after N ms"); a phone takes a fraction of a second.
log "voice (hold the screen 7.5 s)"
dismiss_dialogs
SINCE=$(jslines)
adb shell input swipe $((W / 2)) $((H * 4 / 10)) $((W / 2)) $((H * 4 / 10)) 7500
if wait_js '\[birr\] POST /intent|intent failed' 60 "$SINCE"; then log "hold-to-ask finished"; else fail "hold-to-ask: POST /intent never answered"; fi
sleep 3
shot 06-hold-answer
dump 06-hold-answer
MSG=$(screen_after "$SINCE")
log "hold-to-ask answer on screen: $MSG"
tail -n +"$SINCE" "$JSLOG" | grep -qE 'POST /intent( lang=[a-z]+)? -> 200' || fail "hold-to-ask: no 200 from POST /intent"
case "$MSG" in
  *"$NO_NET"*) fail "hold-to-ask: app says it cannot reach the server" ;;
  ""|"Listening."|*"Hold the screen"*|*"allow the microphone"*) fail "hold-to-ask: no backend answer on screen ($MSG)" ;;
esac

# ---- language switch, then one more scan so the Amharic clips are fetched and played
sleep 3
log "language: tap the language pill"
LB=$(grep -o 'content-desc="Language: [^"]*"[^>]*bounds="\[[0-9]*,[0-9]*\]\[[0-9]*,[0-9]*\]"' "$OUT/06-hold-answer.xml" 2>/dev/null | grep -oE '\[[0-9]+,[0-9]+\]\[[0-9]+,[0-9]+\]' | head -1)
if [ -n "$LB" ]; then
  read -r X1 Y1 X2 Y2 <<<"$(echo "$LB" | tr -c '0-9' ' ')"
  dismiss_dialogs
  adb shell input tap $(((X1 + X2) / 2)) $(((Y1 + Y2) / 2))
  sleep 6
  shot 07-language
  dump 07-language
  cat "$OUT/07-language.txt"
else
  log "language pill not found"
fi

# ---- one scan in Amharic: prompts and the answer play as clips from the backend (GET /speak)
if grep -q 'አማርኛ' "$OUT/07-language.txt" 2>/dev/null; then
  sleep 10 # let the phrase clips download
  dismiss_dialogs
  SINCE=$(jslines)
  log "scan in Amharic"
  adb shell input tap $((W / 2)) $((H * 4 / 10))
  if wait_js 'GET /scan/.* (done|error)|POST /scan -> 200|scan failed' 150 "$SINCE"; then log "Amharic scan finished"; else fail "Amharic scan never finished"; fi
  sleep 8 # the answer clip plays
  shot 08-amharic-answer
  dump 08-amharic-answer
  MSG=$(screen_after "$SINCE")
  log "Amharic answer on screen: $MSG"
  echo "$MSG" > "$OUT/amharic-answer.txt"
  case "$MSG" in *"$NO_NET"*|*"ሰርቨሩን ማግኘት"*) fail "Amharic scan: app says it cannot reach the server" ;; esac
  if tail -n +"$SINCE" "$JSLOG" | grep -qE 'clip failed|clip did not start'; then fail "Amharic clip did not play"; fi

  # ---- a voice question in Amharic: the app must stay in Amharic (the phone bug: it flipped back
  # to English when the backend guessed the question was English)
  sleep 4
  log "voice in Amharic (Ask button): tap $AX,$AY, wait 3 s, tap again"
  dismiss_dialogs
  SINCE=$(jslines)
  adb shell input tap $AX $AY
  sleep 3
  adb shell input tap $AX $AY
  if wait_js '\[birr\] POST /intent|intent failed' 60 "$SINCE"; then log "Amharic intent finished"; else fail "Amharic: POST /intent never answered"; fi
  sleep 8 # the answer (clip or voice) plays
  shot 09-amharic-intent
  dump 09-amharic-intent
  MSG=$(screen_after "$SINCE")
  log "Amharic intent answer on screen: $MSG"
  echo "$MSG" > "$OUT/amharic-intent-answer.txt"
  tail -n +"$SINCE" "$JSLOG" | grep -o '\[birr\] POST /intent.*' | tee "$OUT/amharic-intent-request.txt"
  grep -q 'POST /intent lang=am -> 200' "$OUT/amharic-intent-request.txt" || fail "Amharic: /intent was not sent with lang=am (or not 200)"
  tail -n +"$SINCE" "$JSLOG" | grep -o '\[birr\] intent answered in .*' || true
  if tail -n +"$SINCE" "$JSLOG" | grep -qE '\[birr\] lang: (en|om)'; then fail "Amharic: the app switched language after a voice question"; fi
  grep -q 'content-desc="Language: Amharic"' "$OUT/09-amharic-intent.xml" 2>/dev/null || fail "Amharic: language pill no longer says Amharic after the voice question"
  grep -q 'አማርኛ' "$OUT/09-amharic-intent.txt" 2>/dev/null || fail "Amharic: pill label አማርኛ gone after the voice question"
  case "$MSG" in *"$NO_NET"*|*"ሰርቨሩን ማግኘት"*) fail "Amharic intent: app says it cannot reach the server" ;; esac

  # ---- the pill cycles Amharic -> English: Oromo is parked and must not be offered
  LB=$(grep -o 'content-desc="Language: [^"]*"[^>]*bounds="\[[0-9]*,[0-9]*\]\[[0-9]*,[0-9]*\]"' "$OUT/09-amharic-intent.xml" 2>/dev/null | grep -oE '\[[0-9]+,[0-9]+\]\[[0-9]+,[0-9]+\]' | head -1)
  if [ -n "$LB" ]; then
    read -r X1 Y1 X2 Y2 <<<"$(echo "$LB" | tr -c '0-9' ' ')"
    dismiss_dialogs
    adb shell input tap $(((X1 + X2) / 2)) $(((Y1 + Y2) / 2))
    sleep 4
    shot 10-language-next
    dump 10-language-next
    grep -q 'content-desc="Language: English"' "$OUT/10-language-next.xml" 2>/dev/null || fail "language pill after Amharic is not English (Oromo offered?)"
  else
    fail "language pill not found after the Amharic voice question"
  fi
else
  fail "Amharic not offered (backend /health said no translation?)"
fi

# Oromo is parked: never offered, never selected.
grep -o '\[birr\] langs offered: .*' "$JSLOG" | tail -1 | tee "$OUT/langs-offered.txt"
grep -qE 'offered: (.*,)?om(,|$)' "$OUT/langs-offered.txt" && fail "Oromo is offered"
grep -qE '\[birr\] lang: om|Afaan Oromoo' "$JSLOG" "$OUT"/*.txt 2>/dev/null && fail "Oromo was selected or shown"

sleep 2
adb shell pidof $PKG >/dev/null || fail "app died during the test"
log "end (UTC): $(date -u +%FT%TZ)"

adb logcat -d > "$OUT/logcat-full.txt"
kill $LOGCAT_PID 2>/dev/null || true
echo "---- ReactNativeJS"
cat "$OUT/logcat-js.txt"
# console.error / red box / unhandled rejections log at E; the app's own console.warn lines (W) are
# listed for reading, and the checks above already fail on any that broke a flow.
if grep -qE 'E/ReactNativeJS|Unhandled promise rejection|Invariant Violation' "$OUT/logcat-js.txt"; then
  fail "JS error or crash in logcat"
fi
echo "---- app warnings"
grep 'W/ReactNativeJS' "$OUT/logcat-js.txt" || echo "(none)"
# Only our process: other emulator apps (Gmail, Play services) crash on CI images now and then.
grep -A1 'FATAL EXCEPTION' "$OUT/logcat-full.txt" | grep -q "Process: $PKG" && fail "native crash in $PKG"

if [ "$FAIL" -ne 0 ]; then log "E2E FAILED"; exit 1; fi
log "E2E PASSED"
