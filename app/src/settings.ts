// The language the user chose, kept on the phone so the app opens in it next time.
// A small JSON file in the app's documents folder (expo-file-system); localStorage on the web.

import { File, Paths } from 'expo-file-system';
import { Platform } from 'react-native';

import type { Lang } from './types';

const NAME = 'birr-settings.json';
type Settings = { lang?: Lang };

function read(): Settings {
  try {
    if (Platform.OS === 'web') return JSON.parse(globalThis.localStorage?.getItem(NAME) ?? '{}') as Settings;
    const file = new File(Paths.document, NAME);
    return file.exists ? (JSON.parse(file.textSync()) as Settings) : {};
  } catch (e) {
    console.warn('[birr] settings unreadable', e);
    return {};
  }
}

/** The saved language, or null on the first launch. */
export function savedLang(): Lang | null {
  const lang = read().lang;
  return lang === 'en' || lang === 'am' ? lang : null;
}

export function saveLang(lang: Lang): void {
  const text = JSON.stringify({ ...read(), lang });
  try {
    if (Platform.OS === 'web') {
      globalThis.localStorage?.setItem(NAME, text);
      return;
    }
    const file = new File(Paths.document, NAME);
    if (!file.exists) file.create();
    file.writeSync(text);
  } catch (e) {
    console.warn('[birr] could not save the language', e);
  }
}
