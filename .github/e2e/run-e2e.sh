#!/usr/bin/env bash
# End-to-end check of the release APK (the voice assistant) on an Android emulator, against the
# backend baked into the APK. The whole screen is one tap-to-talk button.
#   1. install, grant CAMERA + RECORD_AUDIO, launch: first launch asks for the language; pick
#      English (top half), then the app greets by voice ("[birr] screen: Hi, I'm Birr")
#   2. tap the screen, wait, tap again: recording -> POST /assist -> 200 and a spoken answer
#   3. a typed turn (birr://assist?text=count my money): /assist says scan -> live guidance posts
#      small frames to POST /frame -> the photo goes to POST /scan -> GET /scan/{id} -> answer
#   4. hold the screen and let go (the other way to talk): POST /assist -> 200
#   5. "speak Amharic" (typed turn): action set_lang, its Amharic clip starts ('[birr] clip started',
#      no 'clip did not start' / 'clip failed' anywhere in the run), the pill says አማርኛ; a tap-to-talk turn is
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
  for _ in 1 2 3 4 5; do
    if adb shell uiautomator dump /sdcard/ui.xml >/dev/null 2>&1 && adb pull /sdcard/ui.xml "$OUT/$1.xml" >/dev/null 2>&1; then
      grep -o 'text="[^"]*"' "$OUT/$1.xml" | sed 's/^text="//;s/"$//' | grep -v '^$' > "$OUT/$1.txt"
      return 0
    fi
    sleep 2
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
LAST_DIALOG_CHECK=-100
dismiss_dialogs() {
  # A uiautomator dump costs the slow emulator seconds of CPU: look at most every 8 s.
  ((SECONDS - LAST_DIALOG_CHECK < 8)) && return 0
  LAST_DIALOG_CHECK=$SECONDS
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
# Tap, speak for $1 s once the recorder runs (the CI emulator takes seconds to start it; a tap
# before that cancels the turn), tap again: one tap-to-talk turn.
tap_talk() {
  local mark
  mark=$(jslines)
  adb shell input tap $((W / 2)) $((H * 4 / 10))
  # a fresh recording, or a hands-free take that the tap turned into a manual one
  wait_js 'recording started|listen: manual' 25 "$mark" || log "recorder start not logged within 25 s"
  sleep "$1"
  adb shell input tap $((W / 2)) $((H * 4 / 10))
}
# Hold the screen, speak for $1 s once the recorder runs, let go: one hold-to-talk turn.
hold_talk() {
  local mark x=$((W / 2)) y=$((H * 4 / 10))
  mark=$(jslines)
  adb shell input motionevent DOWN $x $y
  wait_js 'recording started|listen: manual' 25 "$mark" || log "recorder start not logged within 25 s"
  sleep "$1"
  adb shell input motionevent UP $x $y
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

# After a scan answer, the app may look again by itself (guide / rescan, up to 3 attempts), and
# that look can start before the test gets here. Count looks and finished scans since the turn
# began ($2); wait until every look has finished and no new one starts within 12 s.
SCAN_DONE='GET /scan/.* (done|error)|POST /scan -> 200|scan failed'
settle_scans() {
  local since=$2 starts ends mark
  for _ in 1 2 3 4 5; do
    starts=$(tail -n +"$since" "$JSLOG" | grep -c 'guidance start')
    ends=$(tail -n +"$since" "$JSLOG" | grep -cE "$SCAN_DONE|guidance end: cancelled")
    if ((starts > ends)); then
      log "$1: look $starts still running, waiting for it"
      mark=$(jslines)
      wait_js "$SCAN_DONE|guidance end: cancelled" 180 "$mark" || { fail "$1: look $starts never finished"; return 1; }
      continue
    fi
    mark=$(jslines)
    sleep 12
    tail -n +"$mark" "$JSLOG" | grep -q 'guidance start' || return 0
  done
  fail "$1: the app kept looking again by itself (more than 4 looks)"
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
if wait_js "\[birr\] screen: Hi, I'm Birr" 90 "$SINCE"; then log "greeted"; else fail "no greeting after choosing English"; fi
sleep 6
dismiss_dialogs
shot 02-greeting
dump 02-greeting
cat "$OUT/02-greeting.txt"
adb shell pidof $PKG >/dev/null || fail "app not running after launch (crash)"
grep -q 'content-desc="Talk to Birr"' "$OUT/02-greeting.xml" 2>/dev/null || fail "'Talk to Birr' control not in dump"
grep -q 'Built with Muse Spark Open' "$OUT/02-greeting.txt" || fail "'Built with Muse Spark Open' not on the main screen"
grep -q 'content-desc="Ask a question"' "$OUT/02-greeting.xml" 2>/dev/null && fail "the old Ask button is still there"

# ---- 1b. hands-free: after the greeting the app opens the microphone by itself; the emulator
# microphone hears silence, so the take ends quietly ("no speech") and nothing is sent.
GREET_SINCE=$SINCE
if wait_js '\[birr\] listen: auto-start' 40 "$GREET_SINCE"; then log "hands-free listening started after the greeting"; else fail "hands-free: no '[birr] listen: auto-start' after the greeting"; fi
if wait_js '\[birr\] listen: auto-stop' 40 "$GREET_SINCE"; then log "hands-free: $(tail -n +"$GREET_SINCE" "$JSLOG" | grep -o 'listen: auto-stop.*' | head -1)"; else fail "hands-free: no '[birr] listen: auto-stop'"; fi
# It must not have listened while the greeting was still being spoken.
GREETED_AT=$(tail -n +"$GREET_SINCE" "$JSLOG" | grep -n "screen: Hi, I'm Birr" | head -1 | cut -d: -f1)
STARTED_AT=$(tail -n +"$GREET_SINCE" "$JSLOG" | grep -n 'listen: auto-start' | head -1 | cut -d: -f1)
[ -n "$GREETED_AT" ] && [ -n "$STARTED_AT" ] && [ "$STARTED_AT" -lt "$GREETED_AT" ] && fail "hands-free: listening started before the greeting"
tail -n +"$GREET_SINCE" "$JSLOG" | grep -q 'listen: auto-stop (no speech)' &&
  tail -n +"$GREET_SINCE" "$JSLOG" | grep -q 'POST /assist' && fail "hands-free: a silent take was sent to /assist"
sleep 3

# ---- 2. tap to talk
log "tap to talk: tap, 4 s, tap"
dismiss_dialogs
SINCE=$(jslines)
tap_talk 2
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
settle_scans scan "$SINCE"

# ---- 4. hold to talk
log "hold to talk: finger down, 2 s after the recorder starts, finger up"
dismiss_dialogs
SINCE=$(jslines)
hold_talk 2
if wait_js '\[birr\] POST /assist|/assist failed' 60 "$SINCE"; then log "hold-to-talk finished"; else fail "hold to talk: POST /assist never answered"; fi
sleep 3
shot 05-hold
tail -n +"$SINCE" "$JSLOG" | grep -q 'POST /assist lang=en -> 200' || fail "hold to talk: no 200 from POST /assist"
no_net_check "hold to talk" "$(screen_after "$SINCE")"

# ---- 4b. voice commands while the camera is open (typed, as the recogniser would pass them on):
# "take it" takes the photo now; "cancel" closes the camera without a scan.
sleep 3
log "camera command: take it"
dismiss_dialogs
SINCE=$(jslines)
link_turn "count my money"
if wait_js 'guidance start' 60 "$SINCE"; then log "take-it: guidance started"; else fail "take-it: guidance never started"; fi
if wait_js 'listen: auto \(camera.*camera open\)|listen: auto \(.*camera open\)' 30 "$SINCE"; then log "take-it: listening while the camera is open"; else fail "take-it: not listening while the camera is open"; fi
sleep 2
link_turn "take it"
if wait_js 'camera command: capture' 40 "$SINCE"; then log "take-it: /assist said capture"; else fail "take-it: no capture action"; fi
if wait_js 'guidance end: tapped' 30 "$SINCE"; then log "take-it: guidance ended (tapped)"; else fail "take-it: guidance did not end by the voice command"; fi
if wait_js '\[birr\] POST /scan' 60 "$SINCE"; then log "take-it: photo sent to /scan"; else fail "take-it: no /scan after capture"; fi
tail -n +"$SINCE" "$JSLOG" | grep -o 'POST /assist .*' | tee "$OUT/take-it-assist.txt"
grep -q 'action=capture' "$OUT/take-it-assist.txt" || fail "take-it: /assist did not answer action=capture"
wait_js "$SCAN_DONE" 150 "$SINCE" || fail "take-it: scan never finished"
settle_scans take-it "$SINCE"

log "camera command: cancel"
dismiss_dialogs
SINCE=$(jslines)
link_turn "count my money"
if wait_js 'guidance start' 60 "$SINCE"; then log "cancel: guidance started"; else fail "cancel: guidance never started"; fi
sleep 2
link_turn "cancel"
if wait_js 'camera command: stop' 40 "$SINCE"; then log "cancel: /assist said stop"; else fail "cancel: no stop action"; fi
if wait_js 'guidance end: cancelled' 30 "$SINCE"; then log "cancel: camera closed"; else fail "cancel: guidance did not end by the voice command"; fi
sleep 6
tail -n +"$SINCE" "$JSLOG" | grep -q '\[birr\] POST /scan' && fail "cancel: a photo was still sent to /scan"
MSG=$(screen_after "$SINCE")
log "cancel answer on screen: $MSG"
case "$MSG" in *"closed the camera"*) ;; *) fail "cancel: the app did not say it closed the camera ($MSG)" ;; esac
if wait_js 'listen: auto \(reply' 30 "$SINCE"; then log "cancel: listening again after the reply"; else fail "cancel: no hands-free listening after the reply"; fi
settle_scans cancel "$SINCE"

# ---- 5. switch to Amharic by voice (typed), then Amharic must stay Amharic
sleep 3
log "typed turn: speak Amharic"
dismiss_dialogs
SINCE=$(jslines)
link_turn "please speak Amharic"
if wait_js '\[birr\] POST /assist .*action=set_lang lang=am' 60 "$SINCE"; then log "assist switched to Amharic"; else fail "speak Amharic: no set_lang to am"; fi
wait_js '\[birr\] lang: am' 10 "$SINCE" || fail "the app did not switch to Amharic"
# The Amharic confirmation is an MMS clip: it must start (from a downloaded file), never fall
# back to the English phone voice.
if wait_js '\[birr\] clip started' 30 "$SINCE"; then
  log "Amharic clip: $(tail -n +"$SINCE" "$JSLOG" | grep -o '\[birr\] clip started.*' | head -1)"
else
  fail "Amharic: the set_lang answer clip never started"
fi
if tail -n +"$SINCE" "$JSLOG" | grep -qE 'clip did not start|clip failed'; then fail "Amharic: a clip did not start after switching"; fi
wait_js 'listen: auto \(reply' 40 "$SINCE" || fail "hands-free: no listening after the language reply"
sleep 12 # the confirmation clip plays; the phrase clips download
dismiss_dialogs
shot 06-amharic
dump 06-amharic
cat "$OUT/06-amharic.txt"
grep -q 'አማርኛ' "$OUT/06-amharic.txt" || fail "language pill does not say አማርኛ after set_lang"

log "tap to talk in Amharic"
SINCE=$(jslines)
tap_talk 2
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
settle_scans amharic-scan "$SINCE"

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

grep -qE 'clip did not start|clip failed' "$JSLOG" && fail "a clip did not start somewhere in the run: $(grep -oE '\[birr\] clip (did not start|failed).*' "$JSLOG" | head -3)"
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
