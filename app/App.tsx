// Birr: one screen for blind and low-vision users. Tap anywhere, the phone photographs the notes,
// the backend counts them (docs/api.md), and the answer is spoken. Totals come only from the backend.
// Hold the screen (or use Ask) to ask by voice: "How much do I have?" or "I paid 500 for 320".

import { CameraView, useCameraPermissions } from 'expo-camera';
import * as Haptics from 'expo-haptics';
import * as ImagePicker from 'expo-image-picker';
import { StatusBar } from 'expo-status-bar';
import { useEffect, useRef, useState } from 'react';
import { Linking, Pressable, StyleSheet, Text, View } from 'react-native';

import { choosePictureSize } from './src/pictureSize';
import { preparePhoto, scan, usingMock, type ScanOutcome } from './src/scan';
import type { Lang, PhraseKey, ScanRequest, Spoken } from './src/types';
import { useVoiceQuestion, type Recording } from './src/useVoiceQuestion';
import { loadVoices, promptText, say, sayPrompt, setPhrases, speakAnswer, stopSpeaking } from './src/voice';
import { askIntent, backendTranslates, fetchPhrases, type IntentOutcome } from './src/voiceApi';

const MAX_ATTEMPTS = 3; // docs/api.md: app default
// The backend ends a slow scan itself at 60 s (as a rescan answer). This only covers a lost connection.
const SCAN_TIMEOUT_MS = 90_000;
const INTENT_TIMEOUT_MS = 30_000;
const TICK_MS = 2_000; // docs/api.md: a soft tick every 2 s, so silence never means "broken"
const STILL_COUNTING_AT_TICK = 5; // docs/api.md: "Still counting." once, after about 10 s
// A change check set up by voice applies to the next scans for this long.
const CHANGE_TTL_MS = 5 * 60_000;
const LANG_ORDER: Lang[] = ['en', 'am', 'om'];
// Oromo is parked: the backend still answers in it, but the app does not offer it until a
// native speaker has checked the voice. Remove 'om' here to offer it again.
const HIDDEN_LANGS: Lang[] = ['om'];
const OFFERED = LANG_ORDER.filter((l) => !HIDDEN_LANGS.includes(l));
const LANG_NAMES: Record<Lang, string> = { en: 'English', am: 'Amharic', om: 'Afaan Oromoo' };
const LANG_LABELS: Record<Lang, string> = { en: 'English', am: 'አማርኛ', om: 'Afaan Oromoo' };
const GREEN = '#0B3B2D'; // the logo's colours
const YELLOW = '#FFD23F';

type ChangeCheck = { paid: number; price: number; at: number };

export default function App() {
  const [permission, requestPermission] = useCameraPermissions();
  const camera = useRef<CameraView>(null);
  const attempt = useRef(1);
  const welcomed = useRef(false);
  const changeFor = useRef<ChangeCheck | null>(null);
  const [pictureSize, setPictureSize] = useState<string | undefined>();
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState<false | 'scan' | 'ask'>(false);
  const [message, setMessage] = useState('Tap anywhere to count your money. Hold to ask a question.');
  const [changeNote, setChangeNote] = useState<string | null>(null);
  const [lang, setLang] = useState<Lang>('en');
  const [langs, setLangs] = useState<Lang[]>(['en']);
  const question = useVoiceQuestion(onRecorded);

  useEffect(() => {
    // Amharic is offered when the backend translates, or when the phone has a voice (Oromo is
    // hidden, see HIDDEN_LANGS). Separate calls: on some browsers the voice list never arrives.
    const add = (more: Lang[]) => setLangs((now) => OFFERED.filter((l) => now.includes(l) || more.includes(l)));
    loadVoices().then((voices) => add([...voices]));
    backendTranslates().then((translates) => translates && add(['am', 'om']));
  }, []);

  useEffect(() => {
    console.log(`[birr] lang: ${lang}`);
    if (lang !== 'en') fetchPhrases(lang).then((p) => setPhrases(lang, p));
  }, [lang]);

  useEffect(() => {
    console.log(`[birr] langs offered: ${langs.join(',')}`);
  }, [langs]);

  // What the screen says, in logcat too (ReactNativeJS), so a tester can follow it.
  useEffect(() => {
    console.log(`[birr] screen: ${message}`);
  }, [message]);

  useEffect(() => {
    if (permission && !permission.granted) sayPrompt('cameraNeeded', lang);
  }, [permission?.granted]);

  // Speak it, and show it for anyone helping the user.
  function announcePrompt(key: PhraseKey) {
    setMessage(promptText(key, lang));
    sayPrompt(key, lang);
  }

  function announceAnswer(answer: Spoken, answerLang: Lang, otherwise: PhraseKey) {
    const shown = speakAnswer(answer.speech, answerLang, answer.speech_audio, !answer.speech_todo);
    if (shown) setMessage(shown);
    else announcePrompt(otherwise);
  }

  function setChange(check: ChangeCheck | null) {
    changeFor.current = check;
    setChangeNote(check ? `Checking change: paid ${check.paid}, price ${check.price}` : null);
  }

  function handle(result: ScanOutcome) {
    if (result.kind === 'ok') {
      if (result.body.outcome === 'total') {
        attempt.current = 1;
        setChange(null); // a change check ends with its answer
        Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      } else {
        // guide or rescan: the next tap is the next attempt. The backend's text already
        // says "stop" on the last one, so start over after that.
        attempt.current = attempt.current >= MAX_ATTEMPTS ? 1 : attempt.current + 1;
        if (attempt.current === 1) setChange(null);
        Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning);
      }
      announceAnswer(result.body, lang, 'failed');
    } else if (result.kind === 'error') {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
      announceAnswer(result.body, lang, 'failed');
    } else {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
      announcePrompt(result.kind === 'timeout' ? 'failed' : 'noNetwork');
    }
  }

  function scanRequest(): ScanRequest {
    const base = { lang, attempt: attempt.current, maxAttempts: MAX_ATTEMPTS };
    const change = changeFor.current;
    if (change && Date.now() - change.at < CHANGE_TTL_MS) {
      return { ...base, intent: 'change', paid: change.paid, price: change.price };
    }
    if (change) setChange(null);
    return { ...base, intent: 'count' };
  }

  async function count() {
    if (busy || question.listening) {
      if (busy) sayPrompt('busy', lang, true);
      return;
    }
    if (!ready || !camera.current) return;
    const cam = camera.current;
    await run(async () => {
      const photo = await cam.takePictureAsync({ quality: 0.9 });
      return { uri: photo.uri, width: photo.width, height: photo.height };
    });
  }

  // Count a photo already on the phone (testing, or a photo someone took for the user).
  async function pickPhoto() {
    if (busy) {
      sayPrompt('busy', lang, true);
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
    await run(async () => ({ uri: a.uri, width: a.width, height: a.height }));
  }

  async function run(getPhoto: () => Promise<{ uri: string; width: number; height: number }>) {
    setBusy('scan');
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    announcePrompt('counting');
    let ticks = 0;
    const ticker = setInterval(() => {
      ticks += 1;
      Haptics.selectionAsync();
      if (ticks === STILL_COUNTING_AT_TICK) sayPrompt('stillCounting', lang, true);
    }, TICK_MS);
    try {
      const photo = await getPhoto();
      const jpeg = await preparePhoto(photo.uri, photo.width, photo.height);
      const result = await scan(jpeg, scanRequest(), SCAN_TIMEOUT_MS);
      clearInterval(ticker);
      handle(result);
    } catch (e) {
      console.warn('[birr] photo or upload prep failed', e);
      clearInterval(ticker);
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
      announcePrompt('failed');
    } finally {
      clearInterval(ticker);
      setBusy(false);
    }
  }

  // Voice questions: hold the screen and let go, or tap Ask twice. Nothing is spoken while
  // recording (it would be recorded too); a strong vibration marks the start.
  async function startListening() {
    if (busy) {
      sayPrompt('busy', lang, true);
      return;
    }
    stopSpeaking();
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy);
    setMessage(promptText('listening', lang));
    await question.start();
  }

  function toggleListening() {
    if (question.listening) void question.stop();
    else void startListening();
  }

  function onRecorded(recording: Recording) {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    if (recording.kind === 'denied') announcePrompt('micNeeded');
    else if (recording.kind === 'short') announcePrompt('tooShort');
    else if (recording.kind === 'failed') announcePrompt('heardFailed');
    else void ask(recording.uri);
  }

  async function ask(uri: string) {
    setBusy('ask');
    try {
      handleIntent(await askIntent(uri, lang, INTENT_TIMEOUT_MS));
    } finally {
      setBusy(false);
    }
  }

  function handleIntent(result: IntentOutcome) {
    if (result.kind !== 'ok') {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
      if (result.kind === 'error') announceAnswer(result.body, lang, 'heardFailed');
      else announcePrompt(result.kind === 'timeout' ? 'heardFailed' : 'noNetwork');
      return;
    }
    const answer = result.body;
    // The language the user chose is sticky: an answer never switches it. The backend answers in
    // the lang we sent; there is no "change language" intent (docs/api.md), only the language pill.
    if (answer.lang !== lang) console.log(`[birr] intent answered in ${answer.lang}; staying in ${lang}`);
    if (answer.next === 'scan') {
      // The user now spreads the notes and taps; that scan checks the change if they asked.
      attempt.current = 1;
      const { paid, price } = answer;
      const isChange = answer.intent === 'change' && paid != null && price != null;
      setChange(isChange ? { paid, price, at: Date.now() } : null);
    }
    Haptics.notificationAsync(
      answer.next === 'ask'
        ? Haptics.NotificationFeedbackType.Warning
        : Haptics.NotificationFeedbackType.Success,
    );
    announceAnswer(answer, lang, 'heardFailed');
  }

  // Ask the camera for at least 2048 px photos once it is up. Changing the size restarts the
  // preview, so onCameraReady fires again: pick only once, and welcome the user only once.
  async function onCameraReady() {
    setReady(true);
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
      say(message);
    }
  }

  function nextLanguage() {
    const next = langs[(langs.indexOf(lang) + 1) % langs.length];
    setLang(next);
    setMessage(LANG_LABELS[next]);
    say(`Language: ${LANG_NAMES[next]}.`);
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

  const shown = busy === 'scan' ? 'Counting…' : busy === 'ask' ? '…' : message;
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
        onPress={count}
        onLongPress={startListening}
        onPressOut={() => void question.stop()}
        delayLongPress={450}
        accessibilityRole="button"
        accessibilityLabel="Count money"
        accessibilityHint="Takes a photo of your notes and says the total. Touch and hold to ask a question."
        accessibilityState={{ busy: busy !== false }}
        accessibilityActions={[{ name: 'longpress', label: 'Ask a question' }]}
        onAccessibilityAction={(event) => {
          if (event.nativeEvent.actionName === 'longpress') toggleListening();
        }}
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
        accessibilityHint="Changes the spoken language"
      >
        <Text style={styles.pillText}>{LANG_LABELS[lang]}</Text>
      </Pressable>
      {usingMock && (
        <Text style={styles.mock} accessibilityLabel="Demo mode, no server">
          Demo mode (no server)
        </Text>
      )}
      <View style={styles.bottom} pointerEvents="box-none">
        <Pressable
          style={[styles.askButton, question.listening && styles.askButtonOn]}
          onPress={toggleListening}
          accessibilityRole="button"
          accessibilityLabel="Ask a question"
          accessibilityHint="Tap, ask how much money you have or say what you paid and the price, then tap again to send"
          accessibilityState={{ busy: busy !== false }}
        >
          <Text style={[styles.askText, question.listening && styles.askTextOn]}>
            {question.listening ? 'Listening… tap to send' : 'Ask'}
          </Text>
        </Pressable>
        <View style={styles.messageBox} pointerEvents="none">
          {changeNote && <Text style={styles.changeNote}>{changeNote}</Text>}
          <Text style={styles.message}>{shown}</Text>
        </View>
      </View>
      <StatusBar style="light" />
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: GREEN },
  center: { alignItems: 'center', justifyContent: 'center', padding: 24 },
  big: { color: '#fff', fontSize: 32, fontWeight: '700', textAlign: 'center' },
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
  bottom: { position: 'absolute', left: 16, right: 16, bottom: 40, gap: 12 },
  askButton: {
    minHeight: 64,
    borderRadius: 32,
    justifyContent: 'center',
    backgroundColor: YELLOW,
    borderWidth: 3,
    borderColor: YELLOW,
  },
  askButtonOn: { backgroundColor: GREEN },
  askText: { color: GREEN, fontSize: 24, fontWeight: '800', textAlign: 'center' },
  askTextOn: { color: YELLOW },
  messageBox: { padding: 20, borderRadius: 16, backgroundColor: 'rgba(11,59,45,0.9)' },
  changeNote: { color: YELLOW, fontSize: 18, fontWeight: '700', textAlign: 'center', marginBottom: 6 },
  message: { color: '#fff', fontSize: 28, fontWeight: '700', textAlign: 'center' },
});
