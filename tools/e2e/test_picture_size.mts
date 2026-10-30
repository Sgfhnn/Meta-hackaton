import { choosePictureSize } from '../../app/src/pictureSize.ts';
const cases: [string, string[], string | undefined][] = [
  ['android: smallest 4:3 that reaches 2048', ['640x480', '1280x960', '1920x1080', '2048x1536', '3264x2448', '4000x3000', '4000x2250'], '2048x1536'],
  ['android: no 4:3 big enough, smallest big one', ['1280x960', '2560x1440', '3840x2160'], '2560x1440'],
  ['android: nothing reaches 2048, take the largest', ['640x480', '1280x720', '1600x1200'], '1600x1200'],
  ['ios presets: Photo wins', ['cif352x288', 'hd1280x720', 'hd1920x1080', 'hd4K3840x2160', 'High', 'Medium', 'Low', 'Photo', 'vga640x480'], 'Photo'],
  ['nothing parseable', ['High', 'Low'], undefined],
  ['empty list', [], undefined],
];
let fails = 0;
for (const [name, input, want] of cases) {
  const got = choosePictureSize(input);
  const ok = got === want; if (!ok) fails++;
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}: got ${got}${ok ? '' : `, want ${want}`}`);
}
process.exit(fails ? 1 : 0);
