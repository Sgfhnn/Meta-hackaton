// Birr: a voice assistant for blind and low-vision users handling cash. The whole screen is one
// button: tap (or hold) and say what you need. The backend hears it (Meta Omnilingual ASR), Muse
// Spark Open decides what to do, and the app does it: count the notes with live camera guidance,
// check change, switch language, repeat or explain. Totals come only from the backend (docs/api.md).

import { CameraView, useCameraPermissions } from 'expo-camera';
import * as Haptics from 'expo-haptics';
import * as ImagePicker from 'expo-image-picker';
import { StatusBar } from 'expo-status-bar';
import { useEffect, useRef, useState } from 'react';
import { AccessibilityInfo, Linking, Pressable, StyleSheet, Text, View } from 'react-native';

import { assist, checkFrame, smallFrame } from './src/assistApi';
import { guide, type GuideEnd } from './src/guidance';
import { choosePictureSize } from './src/pictureSize';
import { preparePhoto, scan, usingMock, type ScanOutcome } from './src/scan';
import { savedLang, saveLang } from './src/settings';
import type { AssistResponse, AssistState, Lang, PhraseKey, ScanRequest, Spoken } from './src/types';
import { useVoiceQuestion, type Recording } from './src/useVoiceQuestion';
import {
  isAppSpeaking,
  loadVoices,
  playClip,
  promptText,
  recentAudioLog,
  say,
  sayPrompt,
  sayThen,
  setBeforeClip,
  setPhrases,
  speakAnswer,
  stopSpeaking,
  trackPhrases,
  whenQuiet,
} from './src/voice';
import { askIntent, backendTranslates, fetchPhrases, type IntentOutcome } from './src/voiceApi';

const MAX_ATTEMPTS = 3; // docs/api.md: app default
// The backend ends a slow scan itself at 60 s (as a rescan answer). This only covers a lost connection.
const SCAN_TIMEOUT_MS = 90_000;
const ASSIST_TIMEOUT_MS = 30_000;
const FRAME_TIMEOUT_MS = 4_000;
const TICK_MS = 2_000; // docs/api.md: a soft tick every 2 s, so silence never means "broken"
const STILL_COUNTING_AT_TICK = 5; // docs/api.md: "Still counting." once, after about 10 s
const GUIDE_START_MS = 3_500; // let "hold the phone over your notes" finish before the first hint
const REGUIDE_AFTER_MS = 6_000; // after a "move this note" answer, look again by itself
const LISTEN_AFTER_MS = 400; // after the app stops speaking, before the microphone opens
// TalkBack reads the new screen text after our own voice: give it time before listening.
const talkBackMs = (text: string) => Math.min(6_000, 1_000 + 60 * text.length);
const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));
// A change check set up by voice applies to the next scans for this long.
const CHANGE_TTL_MS = 5 * 60_000;
// Oromo is parked: the backend still answers in it, but the app does not offer it until a
// native speaker has checked the voice.
const OFFERED: Lang[] = ['en', 'am'];
const LANG_NAMES: Record<Lang, string> = { en: 'English', am: 'Amharic', om: 'Afaan Oromoo' };
const LANG_LABELS: Record<Lang, string> = { en: 'English', am: 'አማርኛ', om: 'Afaan Oromoo' };
const GREEN = '#0B3B2D'; // the logo's colours
const YELLOW = '#FFD23F';

type ChangeCheck = { paid: number; price: number; at: number };
type Mode = 'idle' | 'thinking' | 'guiding' | 'counting';
type LastAnswer = { answer: Spoken; lang: Lang };

const SESSION_ID = Math.random().toString(36).slice(2) + Date.now().toString(36);

export default function App() {
  const [permission, requestPermission] = useCameraPermissions();
  const camera = useRef<CameraView>(null);
  const attempt = useRef(1);
  const welcomed = useRef(false);
  const changeFor = useRef<ChangeCheck | null>(null);
  const holding = useRef(false); // recording while the screen is held (let go = send)
  const starting = useRef(false); // the recorder is still starting (slow phones: seconds)
  const guideStop = useRef<'tapped' | 'cancelled' | null>(null);
  const lastAnswer = useRef<LastAnswer | null>(null);
  const convo = useRef<AssistState>({ last_total: null, last_notes: [], pending_paid: null, pending_price: null });
  const assistMissing = useRef(false); // an older backend without /assist: fall back to /intent
  const [pictureSize, setPictureSize] = useState<string | undefined>();
  const ready = useRef(false); // the camera is up (a ref: deep links run in an old closure)
  const [mode, setMode] = useState<Mode>('idle');
  const modeRef = useRef<Mode>('idle');
  const [message, setMessage] = useState('');
  const [changeNote, setChangeNote] = useState<string | null>(null);
  const [lang, setLangState] = useState<Lang | null>(() => savedLang());
  const langRef = useRef<Lang>(lang ?? 'en');
  const question = useVoiceQuestion(onRecorded);
  // A clip is about to play: a hands-free take that has heard nothing yet makes way (and
  // listens again once the clip is over), so the microphone never holds the audio session.
  useEffect(() => {
    setBeforeClip(() => question.yieldToApp());
    return () => setBeforeClip(null);
  });
  // Hands-free: the app listens by itself after it speaks. "Stop" pauses it until the next tap.
  const handsFree = useRef(true);
  const listenToken = useRef(0); // a newer listen request cancels an older one still waiting
  const screenReader = useRef(false);
  const shown = useRef(''); // the last screen text (TalkBack reads it)
  const commandBusy = useRef(false); // a voice command during guidance is at the backend

  const current = () => langRef.current;
  function setModeBoth(m: Mode) {
    modeRef.current = m;
    setMode(m);
  }

  useEffect(() => {
    loadVoices();
    backendTranslates();
    AccessibilityInfo.isScreenReaderEnabled().then((on) => {
      screenReader.current = on;
      console.log(`[birr] screen reader: ${on ? 'on' : 'off'}`);
    });
    const sr = AccessibilityInfo.addEventListener('screenReaderChanged', (on) => {
      screenReader.current = on;
    });
    // First launch: ask for the language by voice, in English and then in Amharic.
    if (savedLang() === null) {
      console.log('[birr] screen: choose a language');
      loadPhrasesFor('am').then((p) => {
        sayThen(promptText('chooseLanguage', 'en'), 'en-US', () => {
          const clip = p.chooseLanguage?.audio;
          if (clip) playClip(clip, () => undefined);
        });
      });
    }
    return () => sr.remove();
  }, []);

  // birr://assist?text=count%20my%20money: a typed turn (Android shortcuts, and the E2E test).
  useEffect(() => {
    const open = (url?: string | null) => {
      const m = url?.match(/^birr:\/\/assist\?(?:.*&)?text=([^&]+)/);
      if (!m) return;
      const text = decodeURIComponent(m[1].replace(/\+/g, ' ')).slice(0, 300);
      console.log(`[birr] link turn (${text.length} chars)`);
      if (savedLang()) void talk({ text });
    };
    Linking.getInitialURL().then(open);
    const sub = Linking.addEventListener('url', (e) => open(e.url));
    return () => sub.remove();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!lang) return;
    langRef.current = lang;
    console.log(`[birr] lang: ${lang}`);
    if (lang !== 'en') void loadPhrasesFor(lang);
  }, [lang]);

  // What the screen says, in logcat too (ReactNativeJS), so a tester can follow it.
  useEffect(() => {
    if (message) console.log(`[birr] screen: ${message}`);
    shown.current = message;
  }, [message]);

  useEffect(() => {
    if (lang && permission && !permission.granted) sayPrompt('cameraNeeded', lang);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [permission?.granted, lang]);

  function chooseLanguage(next: Lang, announce = true) {
    saveLang(next);
    langRef.current = next;
    setLangState(next);
    if (next !== 'en') void loadPhrasesFor(next); // before the announcement asks for its clip
    if (announce) {
      setMessage(LANG_LABELS[next]);
      // Amharic: "Okay, I will speak Amharic now." as its MMS clip (English only if it cannot play).
      if (next === 'en') say(`Language: ${LANG_NAMES[next]}.`);
      else sayPrompt('languageChosen', next, false, `Language: ${LANG_NAMES[next]}.`);
    }
  }

  /** GET /phrases for `l` (one request per language), kept for sayPrompt. */
  function loadPhrasesFor(l: Lang) {
    const loading = fetchPhrases(l).then((p) => {
      setPhrases(l, p);
      return p;
    });
    trackPhrases(l, loading);
    return loading;
  }

  // Speak it, and show it for anyone helping the user.
  function announcePrompt(key: PhraseKey, queued = false) {
    setMessage(promptText(key, current()));
    sayPrompt(key, current(), queued);
  }

  function announceAnswer(answer: Spoken, answerLang: Lang, otherwise: PhraseKey) {
    if (!Object.values(answer.speech ?? {}).some(Boolean)) {
      announcePrompt(otherwise); // nothing to say from the server (e.g. a gateway error page)
      return;
    }
    const shown = speakAnswer(answer.speech, answerLang, answer.speech_audio, !answer.speech_todo);
    if (shown) {
      setMessage(shown);
      lastAnswer.current = { answer, lang: answerLang };
    } else announcePrompt(otherwise);
  }

  function setChange(check: ChangeCheck | null) {
    changeFor.current = check;
    setChangeNote(check ? `Checking change: paid ${check.paid}, price ${check.price}` : null);
  }

  /** Speak a scan answer. Returns true when the backend wants another look (guide / rescan). */
  function handle(result: ScanOutcome): boolean {
    if (result.kind === 'ok') {
      const body = result.body;
      if (body.outcome === 'total') {
        attempt.current = 1;
        setChange(null); // a change check ends with its answer
        convo.current.last_total = body.total;
        convo.current.last_notes = body.notes.map((n) => n.denomination).filter((d): d is NonNullable<typeof d> => d != null);
        Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
        announceAnswer(body, current(), 'failed');
        return false;
      }
      // guide or rescan: look again. The backend's text already says "stop" on the last one.
      const again = attempt.current < MAX_ATTEMPTS;
      attempt.current = again ? attempt.current + 1 : 1;
      if (!again) setChange(null);
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning);
      announceAnswer(body, current(), 'failed');
      return again;
    }
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
    if (result.kind === 'error') announceAnswer(result.body, current(), 'failed');
    else announcePrompt(result.kind === 'timeout' ? 'failed' : 'noNetwork');
    return false;
  }

  function scanRequest(): ScanRequest {
    const base = { lang: current(), attempt: attempt.current, maxAttempts: MAX_ATTEMPTS };
    const change = changeFor.current;
    if (change && Date.now() - change.at < CHANGE_TTL_MS) {
      return { ...base, intent: 'change', paid: change.paid, price: change.price };
    }
    if (change) setChange(null);
    return { ...base, intent: 'count' };
  }

  async function takeFullPhoto() {
    const photo = await camera.current!.takePictureAsync({ quality: 0.9 });
    return { uri: photo.uri, width: photo.width, height: photo.height };
  }

  // Count a photo already on the phone (testing, or a photo someone took for the user).
  async function pickPhoto() {
    if (modeRef.current !== 'idle') {
      sayPrompt('busy', current(), true);
      return;
    }
    let picked: ImagePicker.ImagePickerResult;
    try {
      picked = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ['images'], quality: 1 });
    } catch (e) {
      console.warn('[birr] photo picker failed', e);
      announcePrompt('failed'); // e.g. no photo library permission: say so, never stay silent
      return;
    }
    if (picked.canceled || !picked.assets?.length) return;
    const a = picked.assets[0];
    await run(async () => ({ uri: a.uri, width: a.width, height: a.height }), 'counting');
  }

  /** Photograph (or take) the notes, POST /scan, speak the answer. True = look again. */
  async function run(
    getPhoto: () => Promise<{ uri: string; width: number; height: number }>,
    cue: PhraseKey,
  ): Promise<boolean> {
    setModeBoth('counting');
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    announcePrompt(cue);
    let ticks = 0;
    const ticker = setInterval(() => {
      ticks += 1;
      Haptics.selectionAsync();
      if (ticks === STILL_COUNTING_AT_TICK) sayPrompt('stillCounting', current(), true);
    }, TICK_MS);
    try {
      const photo = await getPhoto();
      const jpeg = await preparePhoto(photo.uri, photo.width, photo.height);
      const result = await scan(jpeg, scanRequest(), SCAN_TIMEOUT_MS);
      clearInterval(ticker);
      return handle(result);
    } catch (e) {
      console.warn('[birr] photo or upload prep failed', e);
      clearInterval(ticker);
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
      announcePrompt('failed');
      return false;
    } finally {
      clearInterval(ticker);
      setModeBoth('idle');
    }
  }

  // ---- live guidance: the camera checks small frames and says what to fix, then takes the photo
  async function guideAndCount() {
    if (!ready.current || !camera.current) {
      announcePrompt('failed');
      return;
    }
    guideStop.current = null;
    setModeBoth('guiding');
    console.log(`[birr] guidance start (attempt ${attempt.current})`);
    void listenSoon('camera'); // "take it", "stop", "speak Amharic" work while the camera is open
    const end: GuideEnd = await guide({
      startDelayMs: GUIDE_START_MS,
      takeFrame: async () => {
        const p = await camera.current!.takePictureAsync({ quality: 0.3, shutterSound: false });
        return smallFrame(p.uri, p.width, p.height);
      },
      check: (uri) => checkFrame(uri, current(), FRAME_TIMEOUT_MS),
      hint: (frame) => {
        if (frame.ready) Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
        if (question.isAuto() && question.heardSpeech()) {
          // The user is talking: show the hint, do not talk over them.
          setMessage(frame.speech[current()] ?? frame.speech.en ?? '');
          return;
        }
        const shown = speakAnswer(frame.speech, current(), frame.speech_audio, !frame.speech_todo);
        if (shown) setMessage(shown);
      },
      good: () => Haptics.selectionAsync(),
      stop: () => guideStop.current,
    });
    console.log(`[birr] guidance end: ${end}`);
    if (end === 'cancelled') {
      setModeBoth('idle');
      return;
    }
    // ready, tapped, the 30 s cap, or a backend without /frame: take the photo now.
    stopAutoListening();
    const again = await run(takeFullPhoto, 'holdStill');
    if (!again) {
      void listenSoon('reply');
      return;
    }
    // The answer asked the user to move a note: give them time, then look again by itself.
    guideStop.current = null;
    setModeBoth('guiding');
    const waited = Date.now();
    while (Date.now() - waited < REGUIDE_AFTER_MS && !guideStop.current) await new Promise((r) => setTimeout(r, 100));
    if (guideStop.current === 'cancelled') {
      setModeBoth('idle');
      return;
    }
    await guideAndCount();
  }

  // ---- hands-free: listen by itself once the app has finished speaking
  async function listenSoon(why: string) {
    if (!handsFree.current) return;
    const token = ++listenToken.current;
    await sleep(LISTEN_AFTER_MS); // let the voice that was just asked for start
    await whenQuiet(); // never record the app's own voice
    if (screenReader.current) {
      const ms = talkBackMs(shown.current);
      console.log(`[birr] listen: waiting ${ms} ms for TalkBack`);
      await sleep(ms);
      await whenQuiet();
    }
    if (token !== listenToken.current || !handsFree.current) return;
    // "stop" / "take it" during guidance: let the camera loop wind down first.
    for (let i = 0; i < 50 && modeRef.current === 'guiding' && guideStop.current; i++) await sleep(100);
    if (token !== listenToken.current) return;
    const m = modeRef.current;
    if (m === 'thinking' || m === 'counting' || question.listening || commandBusy.current) return;
    if (m === 'guiding' && guideStop.current) return;
    console.log(`[birr] listen: auto (${why}${m === 'guiding' ? ', camera open' : ''})`);
    void question.start('auto', { appSpeaking: isAppSpeaking });
  }

  function stopAutoListening() {
    listenToken.current += 1;
    if (question.isAuto()) void question.cancel();
  }

  // ---- talking: tap the screen (tap again to send) or hold it and let go
  async function startListening(hold: boolean) {
    if (modeRef.current === 'counting' || modeRef.current === 'thinking') {
      sayPrompt('busy', current(), true);
      return;
    }
    handsFree.current = true; // any tap or hold turns hands-free back on after "stop"
    if (question.isAuto()) {
      // Already listening hands-free: keep that audio and let the user finish by hand.
      holding.current = hold;
      void question.start(hold ? 'hold' : 'tap');
      return;
    }
    if (modeRef.current === 'guiding') {
      guideStop.current = 'cancelled';
      setModeBoth('idle');
    }
    holding.current = hold;
    stopSpeaking();
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy);
    setMessage(promptText('listening', current()));
    starting.current = true;
    try {
      await question.start();
    } finally {
      starting.current = false;
    }
  }

  function onScreenPress() {
    handsFree.current = true;
    if (modeRef.current === 'guiding') {
      guideStop.current = 'tapped'; // take the photo now
      stopAutoListening();
      return;
    }
    if (question.isAuto()) {
      // Hands-free take running: speech heard -> send it now; nothing yet -> the user takes over.
      if (question.heardSpeech()) void question.stop();
      else void startListening(false);
      return;
    }
    if (question.listening || starting.current) {
      void question.stop();
      return;
    }
    void startListening(false);
  }

  function onScreenRelease() {
    if (holding.current) {
      holding.current = false;
      void question.stop();
    }
  }

  function onRecorded(recording: Recording) {
    if (recording.kind === 'nothing' || recording.kind === 'interrupted') {
      // Hands-free heard nobody (go idle quietly), or the app spoke first (listen again after).
      // While the camera is open, keep listening for "take it" / "stop".
      if (recording.kind === 'interrupted' || modeRef.current === 'guiding') void listenSoon('again');
      return;
    }
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    if (recording.kind === 'denied') announcePrompt('micNeeded');
    else if (recording.kind === 'short') announcePrompt('tooShort');
    else if (recording.kind === 'failed') announcePrompt('heardFailed');
    else void talk({ uri: recording.uri });
  }

  /** One turn: a recording, or typed text (a birr://assist?text=... link, e.g. a shortcut). */
  async function talk(input: { uri: string } | { text: string }) {
    if (modeRef.current === 'guiding') {
      void commandTurn(input);
      return;
    }
    if (question.isAuto()) stopAutoListening(); // a typed turn wins over a hands-free take
    if (modeRef.current !== 'idle') {
      sayPrompt('busy', current(), true);
      return;
    }
    setModeBoth('thinking');
    Haptics.selectionAsync();
    let next: (() => Promise<void>) | null = null;
    try {
      if (!assistMissing.current) {
        let result = await assist(input, current(), SESSION_ID, assistState(false), ASSIST_TIMEOUT_MS);
        // A recogniser or Muse hiccup (502, or a gateway 5xx) or a dropped connection: send the
        // same turn once more before saying sorry. A timeout is not retried (30 s is long enough).
        if ((result.kind === 'error' && result.body.error === 'upstream_error') || result.kind === 'network') {
          console.log(`[birr] /assist ${result.kind === 'network' ? 'network error' : 'upstream error'}, retrying once`);
          result = await assist(input, current(), SESSION_ID, assistState(false), ASSIST_TIMEOUT_MS);
        }
        if (result.kind === 'missing') assistMissing.current = true;
        else {
          next = handleAssist(result);
          if (!next) afterReply(result);
          return;
        }
      }
      if (!('uri' in input)) {
        announcePrompt('heardFailed');
        return;
      }
      next = handleIntent(await askIntent(input.uri, current(), ASSIST_TIMEOUT_MS));
    } finally {
      setModeBoth('idle');
      if (next) void next();
    }
  }

  /** After a spoken reply: listen again by itself (an amount asked for, or anything else). */
  function afterReply(result: Awaited<ReturnType<typeof assist>>) {
    if (result.kind !== 'ok') return; // errors: wait for a tap, never loop on a broken line
    const a = result.body;
    if (a.action === 'stop') {
      handsFree.current = false;
      listenToken.current += 1;
      console.log('[birr] listen: hands-free paused (stop), tap to talk');
      return;
    }
    if (a.heard === false) return; // nothing was heard: do not keep reopening the microphone
    void listenSoon(a.needs === 'ask' ? 'needs an amount' : 'reply');
  }

  function assistState(cameraOpen: boolean): AssistState {
    return { ...convo.current, camera_open: cameraOpen, audio_log: recentAudioLog() };
  }

  /** A voice (or typed) command while the camera is open: take it, stop, switch language... */
  async function commandTurn(input: { uri: string } | { text: string }) {
    if (commandBusy.current) return;
    commandBusy.current = true;
    try {
      let result = await assist(input, current(), SESSION_ID, assistState(true), ASSIST_TIMEOUT_MS);
      if ((result.kind === 'error' && result.body.error === 'upstream_error') || result.kind === 'network') {
        result = await assist(input, current(), SESSION_ID, assistState(true), ASSIST_TIMEOUT_MS);
      }
      if (result.kind !== 'ok' || modeRef.current !== 'guiding') return;
      const a = result.body;
      console.log(`[birr] camera command: ${a.action}`);
      switch (a.action) {
        case 'capture':
          guideStop.current = 'tapped';
          announceAnswer(a, current(), 'holdStill');
          return;
        case 'stop':
          guideStop.current = 'cancelled';
          announceAnswer(a, current(), 'heardFailed');
          return;
        case 'set_lang': {
          const next = OFFERED.includes(a.lang) ? a.lang : current();
          chooseLanguage(next, false);
          announceAnswer(a, next, 'heardFailed');
          return;
        }
        case 'scan':
        case 'change':
          return; // already looking
        default:
          if (a.heard !== false) announceAnswer(a, current(), 'heardFailed');
      }
    } finally {
      commandBusy.current = false;
      if (modeRef.current === 'guiding' && !guideStop.current) void listenSoon('camera');
      else if (guideStop.current === 'cancelled') void listenSoon('reply');
    }
  }

  /** Speak the assistant's answer and do what it says. Returns follow-up work (a scan). */
  function handleAssist(result: Exclude<Awaited<ReturnType<typeof assist>>, { kind: 'missing' }>) {
    if (result.kind !== 'ok') {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
      if (result.kind === 'error') announceAnswer(result.body, current(), 'heardFailed');
      else announcePrompt(result.kind === 'timeout' ? 'heardFailed' : 'noNetwork');
      return null;
    }
    const a: AssistResponse = result.body;
    if (a.needs === 'ask') {
      convo.current.pending_paid = a.paid ?? convo.current.pending_paid;
      convo.current.pending_price = a.price ?? convo.current.pending_price;
    }
    switch (a.action) {
      case 'set_lang': {
        const next = OFFERED.includes(a.lang) ? a.lang : current();
        chooseLanguage(next, false);
        announceAnswer(a, next, 'heardFailed');
        return null;
      }
      case 'repeat': {
        const last = lastAnswer.current;
        if (last) {
          const shown = speakAnswer(last.answer.speech, last.lang, last.answer.speech_audio, !last.answer.speech_todo);
          if (shown) setMessage(shown);
        } else announceAnswer(a, current(), 'heardFailed');
        return null;
      }
      case 'scan':
      case 'change': {
        attempt.current = 1;
        const isChange = a.action === 'change' && a.paid != null && a.price != null;
        setChange(isChange ? { paid: a.paid!, price: a.price!, at: Date.now() } : null);
        if (isChange) {
          convo.current.pending_paid = null;
          convo.current.pending_price = null;
        }
        Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
        announceAnswer(a, current(), 'heardFailed');
        return guideAndCount;
      }
      case 'stop':
        stopSpeaking();
        setMessage(a.speech[current()] ?? a.speech.en ?? '');
        return null;
      default:
        Haptics.notificationAsync(
          a.needs === 'ask' ? Haptics.NotificationFeedbackType.Warning : Haptics.NotificationFeedbackType.Success,
        );
        announceAnswer(a, current(), 'heardFailed');
        return null;
    }
  }

  /** Older backend (no /assist): the /intent answer, then guidance for a scan. */
  function handleIntent(result: IntentOutcome) {
    if (result.kind !== 'ok') {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
      if (result.kind === 'error') announceAnswer(result.body, current(), 'heardFailed');
      else announcePrompt(result.kind === 'timeout' ? 'heardFailed' : 'noNetwork');
      return null;
    }
    const answer = result.body;
    announceAnswer(answer, current(), 'heardFailed');
    if (answer.next !== 'scan') return null;
    attempt.current = 1;
    const { paid, price } = answer;
    const isChange = answer.intent === 'change' && paid != null && price != null;
    setChange(isChange ? { paid, price, at: Date.now() } : null);
    return guideAndCount;
  }

  // Ask the camera for at least 2048 px photos once it is up. Changing the size restarts the
  // preview, so onCameraReady fires again: pick only once, and greet the user only once.
  async function onCameraReady() {
    ready.current = true;
    if (pictureSize === undefined && camera.current) {
      try {
        setPictureSize(choosePictureSize(await camera.current.getAvailablePictureSizesAsync()) ?? '');
      } catch (e) {
        console.warn('[birr] picture sizes unavailable', e);
        setPictureSize(''); // not supported here (e.g. web): keep the camera default
      }
    }
    if (!welcomed.current) {
      welcomed.current = true;
      // Give the Amharic phrase clips a moment to arrive.
      // Let "Okay, I will speak Amharic now." finish first.
      setTimeout(async () => {
        await whenQuiet(10_000);
        announcePrompt('greeting');
        void listenSoon('greeting');
      }, current() === 'en' ? 300 : 1500);
    }
  }

  function nextLanguage() {
    const next = OFFERED[(OFFERED.indexOf(current()) + 1) % OFFERED.length];
    chooseLanguage(next);
  }

  const museNote = (
    <Text style={styles.muse} accessibilityLabel="Built with Muse Spark Open">
      Built with Muse Spark Open
    </Text>
  );

  // First launch: pick the language. Two halves of the screen, each one big button.
  if (!lang) {
    return (
      <View style={styles.screen}>
        <Pressable
          style={[styles.half, styles.center]}
          onPress={() => chooseLanguage('en')}
          accessibilityRole="button"
          accessibilityLabel="English"
          accessibilityHint="Use the app in English"
        >
          <Text style={styles.big}>English</Text>
        </Pressable>
        <Pressable
          style={[styles.half, styles.center, styles.halfBottom]}
          onPress={() => chooseLanguage('am')}
          accessibilityRole="button"
          accessibilityLabel="አማርኛ, Amharic"
          accessibilityHint="መተግበሪያውን በአማርኛ ይጠቀሙ"
        >
          <Text style={styles.big}>አማርኛ</Text>
        </Pressable>
        {museNote}
        <StatusBar style="light" />
      </View>
    );
  }

  if (!permission) return <View style={styles.screen} />;

  if (!permission.granted) {
    const allow = () => (permission.canAskAgain ? requestPermission() : Linking.openSettings());
    return (
      <Pressable
        style={[styles.screen, styles.center]}
        onPress={allow}
        accessibilityRole="button"
        accessibilityLabel="Allow the camera"
        accessibilityHint="The app needs the camera to count your money"
      >
        <Text style={styles.big}>
          {permission.canAskAgain ? 'Tap to allow the camera' : 'Tap to open settings and allow the camera'}
        </Text>
        <StatusBar style="light" />
      </Pressable>
    );
  }

  const status =
    question.listening
      ? promptText('listening', lang)
      : mode === 'thinking'
        ? '…'
        : mode === 'counting'
          ? promptText('counting', lang)
          : message;
  return (
    <View style={styles.screen}>
      <CameraView
        ref={camera}
        style={StyleSheet.absoluteFill}
        facing="back"
        pictureSize={pictureSize || undefined}
        onCameraReady={onCameraReady}
        onMountError={(e) => {
          console.warn('[birr] camera mount error', e.message);
          const text = 'The camera could not start. Please close the app and open it again.';
          setMessage(text);
          say(text);
        }}
      />
      <Pressable
        style={StyleSheet.absoluteFill}
        onPress={onScreenPress}
        onLongPress={() => void startListening(true)}
        onPressOut={onScreenRelease}
        delayLongPress={450}
        accessibilityRole="button"
        accessibilityLabel={mode === 'guiding' ? 'Take the photo now' : 'Talk to Birr'}
        accessibilityHint={
          mode === 'guiding'
            ? 'Birr is checking the camera. Double tap to take the photo now.'
            : 'Double tap, say what you need, like count my money, then double tap again. Or double tap and hold while you speak.'
        }
        accessibilityState={{ busy: mode === 'thinking' || mode === 'counting' }}
      />
      <Pressable
        style={[styles.pill, styles.photoButton]}
        onPress={pickPhoto}
        accessibilityRole="button"
        accessibilityLabel="Count a saved photo"
        accessibilityHint="Opens your photos and counts the notes in the one you choose"
      >
        <Text style={styles.pillText}>Photo</Text>
      </Pressable>
      <Pressable
        style={[styles.pill, styles.langButton]}
        onPress={nextLanguage}
        accessibilityRole="button"
        accessibilityLabel={`Language: ${LANG_NAMES[lang]}`}
        accessibilityHint="Changes the spoken language. You can also say: speak Amharic."
      >
        <Text style={styles.pillText}>{LANG_LABELS[lang]}</Text>
      </Pressable>
      {usingMock && (
        <Text style={styles.mock} accessibilityLabel="Demo mode, no server">
          Demo mode (no server)
        </Text>
      )}
      <View style={styles.bottom} pointerEvents="none">
        <View style={[styles.messageBox, question.listening && styles.messageBoxOn]}>
          {changeNote && <Text style={styles.changeNote}>{changeNote}</Text>}
          <Text style={styles.message} importantForAccessibility="no">
            {status || promptText('greeting', lang)}
          </Text>
        </View>
        {museNote}
      </View>
      <StatusBar style="light" />
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: GREEN },
  center: { alignItems: 'center', justifyContent: 'center', padding: 24 },
  half: { flex: 1 },
  halfBottom: { borderTopWidth: 3, borderTopColor: YELLOW },
  big: { color: '#fff', fontSize: 40, fontWeight: '700', textAlign: 'center' },
  pill: {
    position: 'absolute',
    top: 48,
    minHeight: 56,
    paddingHorizontal: 16,
    justifyContent: 'center',
    borderRadius: 28,
    backgroundColor: 'rgba(0,0,0,0.75)',
    borderWidth: 2,
    borderColor: YELLOW,
  },
  photoButton: { left: 16, minWidth: 100 },
  langButton: { right: 16, minWidth: 120 },
  pillText: { color: '#fff', fontSize: 20, fontWeight: '700', textAlign: 'center' },
  mock: {
    position: 'absolute',
    top: 116,
    left: 16,
    color: YELLOW,
    fontSize: 16,
    fontWeight: '700',
    backgroundColor: 'rgba(0,0,0,0.75)',
    paddingHorizontal: 8,
    paddingVertical: 4,
  },
  bottom: { position: 'absolute', left: 16, right: 16, bottom: 24, gap: 8 },
  messageBox: { padding: 20, borderRadius: 16, backgroundColor: 'rgba(11,59,45,0.9)', borderWidth: 3, borderColor: 'transparent' },
  messageBoxOn: { borderColor: YELLOW },
  changeNote: { color: YELLOW, fontSize: 18, fontWeight: '700', textAlign: 'center', marginBottom: 6 },
  message: { color: '#fff', fontSize: 28, fontWeight: '700', textAlign: 'center' },
  muse: { color: '#fff', opacity: 0.8, fontSize: 12, textAlign: 'center' },
});
