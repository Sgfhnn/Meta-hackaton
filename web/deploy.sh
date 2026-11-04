#!/usr/bin/env bash
# Build a deploy folder for the Birr web demo and push it to Vercel.
# Needs: VERCEL_TOKEN (read from the env), VERCEL_ORG_ID, VERCEL_PROJECT_ID, and REFS_SRC pointing at the folder with clean_sheet.jpg + real_sheet.jpg
# (kept out of the repo). BASETEN_API_KEY is set once in the Vercel project settings.
set -euo pipefail
cd "$(dirname "$0")"
OUT=$(mktemp -d)
cp -r api public vercel.json requirements.txt "$OUT"/
cp -r ../birr "$OUT"/birr
find "$OUT"/birr -name __pycache__ -prune -exec rm -rf {} +
mkdir -p "$OUT"/refs && cp "${REFS_SRC:?set REFS_SRC}"/clean_sheet.jpg "${REFS_SRC}"/real_sheet.jpg "$OUT"/refs/
cd "$OUT"
mkdir -p .vercel
printf '{"orgId":"%s","projectId":"%s"}' "${VERCEL_ORG_ID:?}" "${VERCEL_PROJECT_ID:?}" > .vercel/project.json
npx --yes vercel@latest deploy --prod --yes
