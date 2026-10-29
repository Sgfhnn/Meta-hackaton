// Which camera picture size to ask for. The backend reads notes at 2048 px on the long side, so the
// phone must capture at least that much (the camera's default size isn't documented and can be smaller).

export const UPLOAD_MAX_SIDE = 2048;

type Size = { name: string; w: number; h: number };

/**
 * Pick from CameraView.getAvailablePictureSizesAsync(): the iOS "Photo" preset if offered, else the
 * smallest size whose long side reaches UPLOAD_MAX_SIDE (preferring the 4:3 photo shape), else the
 * largest size there is. Returns undefined when nothing can be parsed, so the camera keeps its default.
 */
export function choosePictureSize(available: string[]): string | undefined {
  if (available.includes('Photo')) return 'Photo';
  const sizes: Size[] = [];
  for (const name of available) {
    const m = /(\d+)x(\d+)/.exec(name);
    if (m) sizes.push({ name, w: Number(m[1]), h: Number(m[2]) });
  }
  if (sizes.length === 0) return undefined;
  const longSide = (s: Size) => Math.max(s.w, s.h);
  const isFourThree = (s: Size) => Math.abs(longSide(s) / Math.min(s.w, s.h) - 4 / 3) < 0.02;
  const byArea = (a: Size, b: Size) => a.w * a.h - b.w * b.h;

  const bigEnough = sizes.filter((s) => longSide(s) >= UPLOAD_MAX_SIDE);
  if (bigEnough.length > 0) {
    const preferred = bigEnough.filter(isFourThree);
    return (preferred.length > 0 ? preferred : bigEnough).sort(byArea)[0].name;
  }
  return sizes.sort(byArea)[sizes.length - 1].name;
}
