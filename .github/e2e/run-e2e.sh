#!/usr/bin/env bash
# End-to-end check of the release APK on an Android emulator, against the live backend.
#   1. install, grant CAMERA + RECORD_AUDIO, launch: the app must start without a crash
#   2. tap the screen: photo from the emulator camera -> POST /scan -> GET /scan/{id} -> spoken answer
#   3. tap Ask, wait, tap again: recording -> POST /intent -> spoken answer
#   4. hold the screen (the other way to ask): same round trip
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
jslog() { adb logcat -d -s ReactNativeJS:V > "$OUT/reactnativejs.txt" 2>/dev/null; cat "$OUT/reactnativejs.txt"; }
# Wait until logcat shows a line matching $1 after the step started (counted by lines), or time out.
wait_js() {
  local pattern=$1 secs=$2 since=$3 i
  for ((i = 0; i < secs; i++)); do
    if adb logcat -d -s ReactNativeJS:V 2>/dev/null | tail -n +"$since" | grep -qE "$pattern"; then return 0; fi
    sleep 1
  done
  return 1
}
jslines() { adb logcat -d -s ReactNativeJS:V 2>/dev/null | wc -l; }
# The last "screen:" message after line $1.
screen_after() { adb logcat -d -s ReactNativeJS:V 2>/dev/null | tail -n +"$1" | grep -o '\[birr\] screen: .*' | tail -1 | sed 's/^\[birr\] screen: //'; }

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

adb logcat -c
log "launch"
adb shell monkey -p $PKG -c android.intent.category.LAUNCHER 1 >/dev/null
# The welcome line is the first message, logged once the JS is running.
if wait_js '\[birr\] screen:' 60 1; then log "JS running"; else fail "app JS never started"; fi
sleep 8 # camera ready + welcome
shot 01-launched
dump 01-launched
cat "$OUT/01-launched.txt"
if ! adb shell pidof $PKG >/dev/null; then fail "app not running after launch (crash)"; fi
grep -q 'Count money' "$OUT/01-launched.xml" 2>/dev/null || log "warning: 'Count money' control not in dump"

# ---- scan: tap the big area (middle of the screen, above the Ask button)
log "scan: tap ${W}/2 x ${H}*4/10"
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
adb logcat -d -s ReactNativeJS:V | tail -n +"$SINCE" | grep -q 'GET /scan/' || fail "scan: job was never polled"

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
adb logcat -d -s ReactNativeJS:V | tail -n +"$SINCE" | grep -q 'POST /intent -> 200' || fail "intent: no 200 from POST /intent"
case "$MSG" in
  *"$NO_NET"*) fail "intent: app says it cannot reach the server" ;;
  ""|"Listening."|*"Hold the screen"*|*"allow the microphone"*) fail "intent: no backend answer on screen ($MSG)" ;;
esac

# ---- voice: hold the screen 3 s and let go
sleep 4
log "voice (hold the screen 3 s)"
SINCE=$(jslines)
adb shell input swipe $((W / 2)) $((H * 4 / 10)) $((W / 2)) $((H * 4 / 10)) 3000
if wait_js '\[birr\] POST /intent|intent failed' 60 "$SINCE"; then log "hold-to-ask finished"; else fail "hold-to-ask: POST /intent never answered"; fi
sleep 3
shot 06-hold-answer
dump 06-hold-answer
MSG=$(screen_after "$SINCE")
log "hold-to-ask answer on screen: $MSG"
case "$MSG" in *"$NO_NET"*) fail "hold-to-ask: app says it cannot reach the server" ;; esac

# ---- language switch, then one more scan so the Amharic clips are fetched and played
sleep 3
log "language: tap the language pill"
LB=$(grep -o 'content-desc="Language: [^"]*"[^>]*bounds="\[[0-9]*,[0-9]*\]\[[0-9]*,[0-9]*\]"' "$OUT/06-hold-answer.xml" 2>/dev/null | grep -oE '\[[0-9]+,[0-9]+\]\[[0-9]+,[0-9]+\]' | head -1)
if [ -n "$LB" ]; then
  read -r X1 Y1 X2 Y2 <<<"$(echo "$LB" | tr -c '0-9' ' ')"
  adb shell input tap $(((X1 + X2) / 2)) $(((Y1 + Y2) / 2))
  sleep 6
  shot 07-language
  dump 07-language
  cat "$OUT/07-language.txt"
else
  log "language pill not found"
fi

sleep 2
adb shell pidof $PKG >/dev/null || fail "app died during the test"
log "end (UTC): $(date -u +%FT%TZ)"

adb logcat -d > "$OUT/logcat-full.txt"
adb logcat -d -s ReactNativeJS:V AndroidRuntime:E > "$OUT/logcat-js.txt"
echo "---- ReactNativeJS"
cat "$OUT/logcat-js.txt"
if grep -qE 'FATAL EXCEPTION|ReactNativeJS.*(Error|TypeError|Unhandled)|Invariant Violation' "$OUT/logcat-js.txt"; then
  fail "JS error or crash in logcat"
fi
grep -E "FATAL EXCEPTION|AndroidRuntime" "$OUT/logcat-full.txt" | grep -i "$PKG" && fail "native crash"

if [ "$FAIL" -ne 0 ]; then log "E2E FAILED"; exit 1; fi
log "E2E PASSED"
