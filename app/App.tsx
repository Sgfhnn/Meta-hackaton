// Birr: one screen for blind and low-vision users. Tap anywhere, the phone photographs the notes,
// the backend counts them (docs/api.md), and the answer is spoken. Totals come only from the backend.

import { CameraView, useCameraPermissions } from 'expo-camera';
import * as Haptics from 'expo-haptics';
import { StatusBar } from 'expo-status-bar';
import { useEffect, useRef, useState } from 'react';
import { Linking, Pressable, StyleSheet, Text, View } from 'react-native';

import { preparePhoto, scan, usingMock, type ScanOutcome } from './src/scan';
import type { Lang } from './src/types';
import { loadVoices, pickSpeech, PROMPTS, say, sayQueued } from './src/voice';

const MAX_ATTEMPTS = 3; // docs/api.md: app default
const SCAN_TIMEOUT_MS = 60_000; // hard limit, then one quicker retry (agreed with Hark)
const TICK_MS = 2_000; // docs/api.md: a soft tick every 2 s, so silence never means "broken"
const STILL_COUNTING_EVERY = 4; // ticks, so "still counting" every 8 s
const LANG_NAMES: Record<Lang, string> = { en: 'English', am: 'Amharic', om: 'Afaan Oromoo' };

export default function App() {
  const [permission, requestPermission] = useCameraPermissions();
  const camera = useRef<CameraView>(null);
  const attempt = useRef(1);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('Tap anywhere to count your money.');
  const [lang, setLang] = useState<Lang>('en');
  const [langs, setLangs] = useState<Lang[]>(['en']);

  useEffect(() => {
    loadVoices().then((available) => setLangs([...available]));
  }, []);

  useEffect(() => {
    if (permission && !permission.granted) say(PROMPTS.cameraNeeded);
  }, [permission?.granted]);

  // Speak it, and show it for anyone helping the user.
  function announce(text: string, locale?: string) {
    setMessage(text);
    say(text, locale);
  }

  function handle(result: ScanOutcome) {
    if (result.kind === 'ok') {
      const { text, locale } = pickSpeech(result.body.speech, lang);
      if (result.body.outcome === 'total') {
        attempt.current = 1;
        Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      } else {
        // guide or rescan: the next tap is the next attempt. The backend's text already
        // says "stop" on the last one, so start over after that.
        attempt.current = attempt.current >= MAX_ATTEMPTS ? 1 : attempt.current + 1;
        Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning);
      }
      announce(text, locale);
    } else if (result.kind === 'error') {
      const { text, locale } = pickSpeech(result.body.speech, lang);
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
      announce(text || PROMPTS.failed, locale);
    } else {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
      announce(result.kind === 'timeout' ? PROMPTS.failed : PROMPTS.noNetwork);
    }
  }

  async function count() {
    if (busy) {
      sayQueued(PROMPTS.busy);
      return;
    }
    if (!ready || !camera.current) return;
    setBusy(true);
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    announce(PROMPTS.counting);
    let ticks = 0;
    const ticker = setInterval(() => {
      ticks += 1;
      Haptics.selectionAsync();
      if (ticks % STILL_COUNTING_EVERY === 0) sayQueued(PROMPTS.stillCounting);
    }, TICK_MS);
    try {
      const photo = await camera.current.takePictureAsync({ quality: 0.8 });
      const jpeg = await preparePhoto(photo.uri, photo.width, photo.height);
      const req = { lang, attempt: attempt.current, maxAttempts: MAX_ATTEMPTS, fast: false };
      let result = await scan(jpeg, req, SCAN_TIMEOUT_MS);
      if (result.kind === 'timeout') {
        announce(PROMPTS.slowRetry);
        result = await scan(jpeg, { ...req, fast: true }, SCAN_TIMEOUT_MS);
      }
      clearInterval(ticker);
      handle(result);
    } catch {
      clearInterval(ticker);
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
      announce(PROMPTS.failed);
    } finally {
      clearInterval(ticker);
      setBusy(false);
    }
  }

  function nextLanguage() {
    const next = langs[(langs.indexOf(lang) + 1) % langs.length];
    setLang(next);
    announce(`Language: ${LANG_NAMES[next]}.`);
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

  return (
    <View style={styles.screen}>
      <CameraView
        ref={camera}
        style={StyleSheet.absoluteFill}
        facing="back"
        onCameraReady={() => {
          setReady(true);
          say(message);
        }}
        onMountError={() => announce('The camera could not start. Please close the app and open it again.')}
      />
      <Pressable
        style={StyleSheet.absoluteFill}
        onPress={count}
        accessibilityRole="button"
        accessibilityLabel="Count money"
        accessibilityHint="Takes a photo of your notes and says the total"
        accessibilityState={{ busy }}
      />
      <Pressable
        style={styles.langButton}
        onPress={nextLanguage}
        accessibilityRole="button"
        accessibilityLabel={`Language: ${LANG_NAMES[lang]}`}
        accessibilityHint="Changes the spoken language"
      >
        <Text style={styles.langText}>{LANG_NAMES[lang]}</Text>
      </Pressable>
      {usingMock && (
        <Text style={styles.mock} accessibilityLabel="Demo mode, no server">
          Demo mode (no server)
        </Text>
      )}
      <View style={styles.messageBox} pointerEvents="none">
        <Text style={styles.message}>{busy ? 'Counting…' : message}</Text>
      </View>
      <StatusBar style="light" />
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: '#000' },
  center: { alignItems: 'center', justifyContent: 'center', padding: 24 },
  big: { color: '#fff', fontSize: 32, fontWeight: '700', textAlign: 'center' },
  langButton: {
    position: 'absolute',
    top: 48,
    right: 16,
    minHeight: 56,
    minWidth: 120,
    paddingHorizontal: 16,
    justifyContent: 'center',
    borderRadius: 28,
    backgroundColor: 'rgba(0,0,0,0.75)',
    borderWidth: 2,
    borderColor: '#fff',
  },
  langText: { color: '#fff', fontSize: 20, fontWeight: '700', textAlign: 'center' },
  mock: {
    position: 'absolute',
    top: 56,
    left: 16,
    color: '#ffd400',
    fontSize: 16,
    fontWeight: '700',
    backgroundColor: 'rgba(0,0,0,0.75)',
    paddingHorizontal: 8,
    paddingVertical: 4,
  },
  messageBox: {
    position: 'absolute',
    left: 16,
    right: 16,
    bottom: 48,
    padding: 20,
    borderRadius: 16,
    backgroundColor: 'rgba(0,0,0,0.8)',
  },
  message: { color: '#fff', fontSize: 28, fontWeight: '700', textAlign: 'center' },
});
