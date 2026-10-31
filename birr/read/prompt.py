"""The Muse reader prompt (Claude's tested prompt, pasted verbatim Oct 29 19:40 from Slack): colour rule + reference sheets.

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

PROMPT = """You are reading cash for a blind user. The photo shows Ethiopian birr banknotes, often held in a hand, fanned, folded or overlapping. List EVERY banknote you can see, including notes at the back of the pile that show only a strip or a corner.

Ethiopian birr notes in circulation: 5, 10, 50, 100, 200.
5   = grey-blue (front has a green tint); boxed "5"; Ge'ez ፭; front: coffee picker; back: kudu + wild cat; older design with a triangle mark.
10  = bright green; Ge'ez ፲; front: camels + coffee picker; back: four people joining hands + mesob basket.
50  = red/pink; Ge'ez ፶; front: tractor ploughing; back: factory with three chimneys.
100 = periwinkle blue (back also mint/teal + peach-orange cave); Ge'ez ፻; front: castle + obelisk; back: Sof Omar cave + Harar gate.
200 = purple/lilac; Ge'ez ፪፻; front: white dove; back: Walia ibex.
Every back shows the Ge'ez numeral, "ብር" and the Latin numeral in the top-right and bottom-left corners: look there first.
The lion head and the Ethiopia map are on every front: they do NOT identify a note.
Count a note once even if a fold or another note splits it into two visible pieces. Count a strip as its own note only when it is clearly a separate piece of paper.

How to decide a value:
- Use every signal you can see: a Latin or Ge'ez numeral, the amount text, the front or back picture (or a fragment of it), and the colour.
- Colour alone can decide a value: purple/lilac = 200, red/pink = 50, bright green = 10, periwinkle blue = 100, grey-blue = 5.
- Two colour families are easy to confuse, so take extra care:
  * Blue: a faded 100 can look as pale as a 5. The 100 is periwinkle with mint/teal areas and a peach cave on the back; the 5 is grey-blue engraving on whitish or yellowed paper. If you cannot tell which, mark the note "unclear".
  * Pink: in warm light the 200's lilac turns pink like the 50, and the 50 can look orange. Look for the ibex or dove (200) versus the chimneys or tractor (50). If only a pink strip shows and you cannot tell, mark it "unclear".

Reply with ONLY JSON, no other text:
{"notes": [{"value": 5|10|50|100|200|null, "evidence": ["latin numeral"|"geez numeral"|"amount text"|"picture"|"colour"], "status": "read"|"unclear"}]}
Use value null with status "unclear" for a note you cannot identify. Never add up the notes."""


# The narrow count check (COUNT_CHECK=1, Claude's spec Oct 31): one call per repeated denomination.
COUNT_PROMPT = (
    "How many {d}-birr notes are in this photo? Count whole physical notes, not pieces or layers. "
    "Reply with ONLY a single integer, no other text."
)
