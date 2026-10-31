#!/usr/bin/env bash
# End-to-end check of the release APK (the voice assistant) on an Android emulator, against the
# backend baked into the APK. The whole screen is one tap-to-talk button.
#   1. install, grant CAMERA + RECORD_AUDIO, launch: first launch asks for the language; pick
#      English (top half), then the app greets by voice ("[birr] screen: Hi, I'm Birr")
#   2. tap the screen, wait, tap again: recording -> POST /assist -> 200 and a spoken answer
#   3. a typed turn (birr://assist?text=count my money): /assist says scan -> live guidance posts
#      small frames to POST /frame -> the photo goes to POST /scan -> GET /scan/{id} -> answer
#   4. hold the screen and let go (the other way to talk): POST /assist -> 200
#   5. "speak Amharic" (typed turn): action set_lang, the pill says አማርኛ; a tap-to-talk turn is
#      sent with lang=am and the app stays in Amharic; an Amharic scan turn runs in Amharic
#   6. relaunch: the language is remembered (no language question, lang am)
# The emulator microphone hears silence, so spoken turns are proven by the 200 round trip (the
# backend answers "Sorry, I couldn't hear that"); typed turns prove the actions.
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


# Open a birr://assist link: a typed turn, as an Android shortcut would send it.
link_turn() {
  local enc
  enc=$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1]))' "$1")
  adb shell "am start -W -a android.intent.action.VIEW -d 'birr://assist?text=$enc' $PKG" >/dev/null
}
# Tap, wait $1 s, tap again: one tap-to-talk turn.
tap_talk() {
  adb shell input tap $((W / 2)) $((H * 4 / 10))
  sleep "$1"
  adb shell input tap $((W / 2)) $((H * 4 / 10))
}
no_net_check() { # $1 label, $2 message
  case "$2" in *"$NO_NET"*|*"ሰርቨሩን ማግኘት"*) fail "$1: app says it cannot reach the server" ;; esac
}
# Wait for a scan turn to go through guidance and /scan; $1 label.
scan_round_trip() {
  local since=$2
  if wait_js 'guidance start' 40 "$since"; then log "$1: guidance started"; else fail "$1: guidance never started"; fi
  if wait_js '\[birr\] POST /frame' 40 "$since"; then log "$1: /frame answered"; else fail "$1: POST /frame never answered"; fi
  if wait_js 'guidance end' 60 "$since"; then log "$1: $(tail -n +"$since" "$JSLOG" | grep -o 'guidance end: .*' | tail -1)"; else fail "$1: guidance never ended"; fi
  if wait_js '\[birr\] POST /scan' 60 "$since"; then log "$1: POST /scan answered"; else fail "$1: POST /scan never answered"; fi
  if wait_js 'GET /scan/.* (done|error)|POST /scan -> 200|scan failed' 150 "$since"; then log "$1: scan job finished"; else fail "$1: scan job never finished"; fi
  local frames
  frames=$(tail -n +"$since" "$JSLOG" | grep -c 'POST /frame .*-> 200')
  log "$1: $frames frame checks with 200"
  [ "$frames" -ge 1 ] || fail "$1: no 200 from POST /frame"
  tail -n +"$since" "$JSLOG" | grep -o 'POST /frame .*' | sort | uniq -c | tee "$OUT/$1-frames.txt"
}

# After a scan answer, the app may look again by itself (guide / rescan, up to 3 attempts).
# Wait until no new look starts within 12 s.
settle_scans() {
  local mark looks=0
  for _ in 1 2 3; do
    mark=$(jslines)
    sleep 12
    if tail -n +"$mark" "$JSLOG" | grep -q 'guidance start'; then
      looks=$((looks + 1))
      log "$1: the answer asked for another look ($looks)"
      wait_js 'GET /scan/.* (done|error)|POST /scan -> 200|scan failed' 180 "$mark" || fail "$1: the extra look never finished"
    else
      return 0
    fi
  done
  sleep 12
}

log "runner public IP: $(curl -s -m 10 https://api.ipify.org || echo unknown)"
log "start (UTC): $(date -u +%FT%TZ)"
adb shell getprop ro.build.version.release
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

# ---- 1. first launch: the language question, then the greeting
log "launch"
adb shell monkey -p $PKG -c android.intent.category.LAUNCHER 1 >/dev/null
if wait_js '\[birr\] screen: choose a language' 90 1; then log "language question shown"; else fail "first launch did not ask for the language"; fi
sleep 4
dismiss_dialogs
shot 01-language
dump 01-language
cat "$OUT/01-language.txt"
grep -q 'Built with Muse Spark Open' "$OUT/01-language.txt" || fail "'Built with Muse Spark Open' not on the start screen"
SINCE=$(jslines)
adb shell input tap $((W / 2)) $((H / 4)) # top half: English
if wait_js "\[birr\] screen: Hi, I'm Birr" 40 "$SINCE"; then log "greeted"; else fail "no greeting after choosing English"; fi
sleep 6
dismiss_dialogs
shot 02-greeting
dump 02-greeting
cat "$OUT/02-greeting.txt"
adb shell pidof $PKG >/dev/null || fail "app not running after launch (crash)"
grep -q 'content-desc="Talk to Birr"' "$OUT/02-greeting.xml" 2>/dev/null || fail "'Talk to Birr' control not in dump"
grep -q 'Built with Muse Spark Open' "$OUT/02-greeting.txt" || fail "'Built with Muse Spark Open' not on the main screen"
grep -q 'content-desc="Ask a question"' "$OUT/02-greeting.xml" 2>/dev/null && fail "the old Ask button is still there"

# ---- 2. tap to talk
log "tap to talk: tap, 4 s, tap"
dismiss_dialogs
SINCE=$(jslines)
tap_talk 4
if wait_js '\[birr\] POST /assist|/assist failed' 60 "$SINCE"; then log "assist turn finished"; else fail "POST /assist never answered (or never sent)"; fi
sleep 4
shot 03-talk
MSG=$(screen_after "$SINCE")
log "tap-to-talk answer on screen: $MSG"
tail -n +"$SINCE" "$JSLOG" | grep -o '\[birr\] POST /assist.*' | tee "$OUT/talk-request.txt"
grep -q 'POST /assist lang=en -> 200' "$OUT/talk-request.txt" || fail "tap to talk: no 200 from POST /assist with lang=en"
no_net_check "tap to talk" "$MSG"
case "$MSG" in ""|"Listening."|*"Hold the screen"*|*"allow the microphone"*) fail "tap to talk: no backend answer on screen ($MSG)" ;; esac

# ---- 3. a scan turn: /assist -> guidance (/frame) -> /scan
sleep 3
log "typed turn: count my money"
dismiss_dialogs
SINCE=$(jslines)
link_turn "count my money"
if wait_js '\[birr\] POST /assist .*action=scan' 60 "$SINCE"; then log "assist said scan"; else fail "count my money: /assist did not answer action=scan"; fi
scan_round_trip scan "$SINCE"
sleep 4
shot 04-scan-answer
MSG=$(screen_after "$SINCE")
log "scan answer on screen: $MSG"
echo "$MSG" > "$OUT/scan-answer.txt"
no_net_check scan "$MSG"
case "$MSG" in ""|"Counting."|*"could not count that"*) fail "scan: no backend answer on screen ($MSG)" ;; esac
# A guide/rescan answer starts another look by itself (up to 3 attempts): let them finish.
settle_scans scan

# ---- 4. hold to talk
log "hold to talk (7.5 s)"
dismiss_dialogs
SINCE=$(jslines)
adb shell input swipe $((W / 2)) $((H * 4 / 10)) $((W / 2)) $((H * 4 / 10)) 7500
if wait_js '\[birr\] POST /assist|/assist failed' 60 "$SINCE"; then log "hold-to-talk finished"; else fail "hold to talk: POST /assist never answered"; fi
sleep 3
shot 05-hold
tail -n +"$SINCE" "$JSLOG" | grep -q 'POST /assist lang=en -> 200' || fail "hold to talk: no 200 from POST /assist"
no_net_check "hold to talk" "$(screen_after "$SINCE")"

# ---- 5. switch to Amharic by voice (typed), then Amharic must stay Amharic
sleep 3
log "typed turn: speak Amharic"
dismiss_dialogs
SINCE=$(jslines)
link_turn "please speak Amharic"
if wait_js '\[birr\] POST /assist .*action=set_lang lang=am' 60 "$SINCE"; then log "assist switched to Amharic"; else fail "speak Amharic: no set_lang to am"; fi
wait_js '\[birr\] lang: am' 10 "$SINCE" || fail "the app did not switch to Amharic"
sleep 12 # the confirmation clip plays; the phrase clips download
dismiss_dialogs
shot 06-amharic
dump 06-amharic
cat "$OUT/06-amharic.txt"
grep -q 'አማርኛ' "$OUT/06-amharic.txt" || fail "language pill does not say አማርኛ after set_lang"

log "tap to talk in Amharic"
SINCE=$(jslines)
tap_talk 4
if wait_js '\[birr\] POST /assist|/assist failed' 60 "$SINCE"; then log "Amharic assist turn finished"; else fail "Amharic: POST /assist never answered"; fi
sleep 8
tail -n +"$SINCE" "$JSLOG" | grep -o '\[birr\] POST /assist.*' | tee "$OUT/amharic-talk-request.txt"
grep -q 'POST /assist lang=am -> 200' "$OUT/amharic-talk-request.txt" || fail "Amharic: /assist was not sent with lang=am (or not 200)"
grep -q 'lang=am by=' "$OUT/amharic-talk-request.txt" || fail "Amharic: /assist did not answer in am"
if tail -n +"$SINCE" "$JSLOG" | grep -qE '\[birr\] lang: (en|om)'; then fail "Amharic: the app switched language after a voice turn"; fi
dump 07-amharic-talk
grep -q 'content-desc="Language: Amharic"' "$OUT/07-amharic-talk.xml" 2>/dev/null || fail "Amharic: pill no longer Amharic after a voice turn"
no_net_check "Amharic talk" "$(screen_after "$SINCE")"

log "typed Amharic scan turn"
SINCE=$(jslines)
link_turn "ብሬን ቁጠርልኝ"
if wait_js '\[birr\] POST /assist lang=am .*action=scan lang=am' 60 "$SINCE"; then log "Amharic scan turn"; else fail "Amharic count: /assist did not answer scan in am"; fi
scan_round_trip amharic-scan "$SINCE"
sleep 8
shot 08-amharic-answer
MSG=$(screen_after "$SINCE")
log "Amharic scan answer on screen: $MSG"
echo "$MSG" > "$OUT/amharic-answer.txt"
no_net_check "Amharic scan" "$MSG"
tail -n +"$SINCE" "$JSLOG" | grep -q 'POST /frame lang=am' || fail "Amharic: /frame not sent with lang=am"
if tail -n +"$SINCE" "$JSLOG" | grep -qE 'clip failed|clip did not start'; then fail "Amharic clip did not play"; fi
if tail -n +"$SINCE" "$JSLOG" | grep -qE '\[birr\] lang: (en|om)'; then fail "Amharic: language switched during the scan"; fi
settle_scans amharic-scan

# ---- 6. relaunch: the language is remembered
sleep 10
log "relaunch"
adb shell am force-stop $PKG
sleep 2
SINCE=$(jslines)
adb shell monkey -p $PKG -c android.intent.category.LAUNCHER 1 >/dev/null
if wait_js '\[birr\] lang: ' 60 "$SINCE"; then log "$(tail -n +"$SINCE" "$JSLOG" | grep -o '\[birr\] lang: .*' | head -1)"; else fail "relaunch: app JS never started"; fi
sleep 8
tail -n +"$SINCE" "$JSLOG" | grep -q 'choose a language' && fail "relaunch: asked for the language again"
tail -n +"$SINCE" "$JSLOG" | grep -q '\[birr\] lang: am' || fail "relaunch: language not remembered (expected am)"
shot 09-relaunch

grep -qE '\[birr\] lang: om|Afaan Oromoo' "$JSLOG" "$OUT"/*.txt 2>/dev/null && fail "Oromo was selected or shown"

sleep 2
adb shell pidof $PKG >/dev/null || fail "app died during the test"
log "end (UTC): $(date -u +%FT%TZ)"

adb logcat -d > "$OUT/logcat-full.txt"
kill $LOGCAT_PID 2>/dev/null || true
echo "---- ReactNativeJS"
cat "$OUT/logcat-js.txt"
if grep -qE 'E/ReactNativeJS|Unhandled promise rejection|Invariant Violation' "$OUT/logcat-js.txt"; then
  fail "JS error or crash in logcat"
fi
echo "---- app warnings"
grep 'W/ReactNativeJS' "$OUT/logcat-js.txt" || echo "(none)"
grep -A1 'FATAL EXCEPTION' "$OUT/logcat-full.txt" | grep -q "Process: $PKG" && fail "native crash in $PKG"

if [ "$FAIL" -ne 0 ]; then log "E2E FAILED"; exit 1; fi
log "E2E PASSED"
