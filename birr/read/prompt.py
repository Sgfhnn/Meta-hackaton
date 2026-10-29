"""The Muse reader prompt: colour rule + reference sheets.

Sources:
- Colour key (5 pale blue-grey, 10 green, 50 red/orange, 100 full blue, 200 purple) and the
  "count each physical note once" rule: the colour prompt Hark ran in the Oct 28 A/B.
- Reference sheets (per-note numerals, Ge'ez, pictures, the corner numerals on every back, the
  lion/map warning): docs/birr-knowledge.md section 4 (branch claude/birr-knowledge-pack, PR #8)
  and the PROMPT in branch claude/knowledge-prompt (PR #9).
- Decision order (numeral or picture first, colour counts when only a back or a band shows) and
  the three colour mix-ups: Claude's results post in #meta-hackathon, Oct 29.

PR #9's two-signal rule ("colour alone = unclear") is deliberately NOT used: it scored 0/20 on
the locked set because back-of-pile notes show only colour. Safety comes from the two-read
agreement and the SAM count check in code instead.
"""

PROMPT = """You are counting cash for a blind user. The photo shows Ethiopian birr notes, often overlapping in a handheld pile. Only these notes exist: 5, 10, 50, 100, 200 birr.

Reference sheets:
5   = pale blue-grey (front has a green tint); small boxed "5"; Ge'ez ፭; front: man picking coffee; back: kudu + wild cat; older design with a triangle mark.
10  = green; Ge'ez ፲; front: camels + man picking coffee; back: four people joining hands + mesob basket.
50  = red/orange; Ge'ez ፶; front: tractor ploughing; back: factory with three chimneys.
100 = full blue (back also has teal and an orange-brown cave); Ge'ez ፻; front: castle + obelisk; back: Sof Omar cave + Harar gate.
200 = purple; Ge'ez ፪፻; front: white dove; back: Walia ibex.
Every back shows the Ge'ez numeral, "ብር" and the Latin numeral in the top-right and bottom-left corners: look there first.
The lion head and the Ethiopia map are on every front: they do NOT identify a note.

How to decide each note:
1. A readable numeral (Latin or Ge'ez) or the main picture decides the value.
2. When only the back or a coloured band of a note shows, its colour counts. Colour key: 5 pale blue-grey, 10 green, 50 red/orange, 100 full blue, 200 purple.
3. Known colour mix-ups: the 100's teal back is still a 100, not a 10; a 200 in warm light is still purple, not a 50; a faded 100 is not a 5.
4. Count each physical note exactly once: a folded or partly hidden note showing in two places is one note. Do not invent notes you cannot see.
5. A note that is not Ethiopian birr is "not_birr". If a note's value cannot be determined, label it "unclear".

Do not add totals. Reply with ONLY JSON: {"notes": [<label>, ...]} with one label per physical note, each label one of "5", "10", "50", "100", "200", "not_birr", "unclear"."""
