# Birr knowledge pack

This pack describes what identifies each note, taken from clean reference images of the 5, 10, 50, 100 and 200 birr notes, front and back. Real photos are messy: notes are fanned, folded and covered, and often only the back or an edge shows. So the pack lists **every** signal per note, including the ones that still show on a fragment, and the **confusable pairs** the model must watch for.

It feeds the Muse prompt and the backend cross-check. It records what the reference images show; check it against real circulating notes before relying on any single signal.

## 1. Signals per note

| | **5** | **10** | **50** | **100** | **200** |
|---|---|---|---|---|---|
| **Dominant colour** | Grey-blue / slate, with a **green tint on the front** | **Bright green** | **Red / pink** | **Blue**, back has **teal-mint and orange-brown** areas | **Purple / violet** |
| **Ge'ez numeral** (shield, top corners) | ፭ | ፲ | ፶ | ፻ | ፪፻ |
| **Amharic amount** | አምስት ብር | አሥር ብር | አምሳ ብር | መቶ ብር | ሁለት መቶ ብር |
| **English amount** (front) | FIVE BIRR | TEN BIRR | FIFTY BIRR | ONE HUNDRED BIRR | TWO HUNDRED BIRR |
| **Latin numeral** | "5" in a **small box**, bottom left and right | Large outlined "10", bottom corners | Large outlined "50", bottom corners | Large outlined "100", bottom corners | Large outlined "200", bottom corners |
| **Front picture** | A **man picking coffee** (right) | **Camels** (brown) in the centre, a **man picking coffee** (right) | A **tractor ploughing** a field | **Fasil Ghebbi castle** (centre) and the **Aksum obelisk** (right) | A **white dove with an olive branch** |
| **Back picture** | A **kudu** (spiral horns), a **wild cat (caracal)**, mountains, a coffee branch | **Four people with joined hands**, a **mesob** basket (right) | A **factory with three tall chimneys** | **Sof Omar cave** (orange-brown rock) and the **Harar gate** (blue) | A **Walia ibex** (big curved horns) on a cliff |
| **Design series** | **Older layout**: printed dates 2009/2017, a **triangle mark** △ | 2020 series | 2020 series | Same layout as the 2020 series (this sample is dated 2015/2023) | 2020 series |

**Shared by every front, so it can't tell notes apart:** the lion head, the Ethiopia map, "National Bank of Ethiopia" with its Amharic name, the governor's signature, and the serial numbers top-left and right. The 2020-series notes also have a vertical security thread and a segmented circle mark.

**Shared by every back:** the Amharic amount at the top, and Ge'ez numeral + "ብር" + Latin numeral in the top-right and bottom-left corners. **So a back still shows the amount in two corners.** Look there first.

## 2. Confusable pairs: the main risks on messy piles

1. **5 front vs 10 front.** Both are greenish, and both show a man picking coffee. Tell them apart by:
   - colour: 10 is a saturated bright green; 5 is grey-green;
   - picture: camels appear only on the 10;
   - numeral style: the 5 has a boxed small "5" and a △ mark.
2. **100 back vs 50 or 10.** The 100 back has a large **orange-brown cave**, which can read as the 50's red, and **teal-mint** areas, which can read as the 10's green. Tell it apart by the **Harar gate** and the blue "100" in the corners. Never decide a 100 back by colour alone.
3. **200 vs 100 in dim or warm light.** Purple and blue drift toward each other. Tell them apart by the **ibex** (200) vs the cave or gate (100), and the dove (200) vs the castle or obelisk (100).
4. **Folded or covered notes split into two pieces.** Count a note by **continuity**, not by visible pieces. A fold can make one note look like two, as with the 100 in pile 3. SAM fragment masks make the same mistake.
5. **Phantom notes at the edge of a fan.** A thin edge strip has colour but no numeral or picture, so treat it as `unclear`, never as a note. The colour-only rerun on L20 invented two 5s this way.

## 3. Identification rule (prompt + backend)

- A note is **identified** only when **two independent signals agree**. The signals are: a Latin numeral, a Ge'ez numeral, the Amharic or English amount, the front or back picture (or a clear fragment of it, such as ibex horns or the chimneys), and the dominant colour.
- **Colour plus one other signal** is enough. **Colour alone** means `unclear`.
- For each note, Muse returns `{value, evidence: [signals], status}`.
- The backend speaks a total only when every note is identified **and** the SAM count matches.
- Don't judge colour from yellowed paper or a shadow. Judge it from the printed bands.

## 4. Prompt block (paste into the Muse prompt)

```
Ethiopian birr notes in circulation: 5, 10, 50, 100, 200.
5   = grey-blue (front has green tint); boxed "5"; Ge'ez ፭; front: coffee picker; back: kudu + wild cat; older design with △ mark.
10  = bright green; Ge'ez ፲; front: camels + coffee picker; back: four people joining hands + mesob basket.
50  = red/pink; Ge'ez ፶; front: tractor ploughing; back: factory with three chimneys.
100 = blue (back also teal + orange-brown cave); Ge'ez ፻; front: castle + obelisk; back: Sof Omar cave + Harar gate.
200 = purple; Ge'ez ፪፻; front: white dove; back: Walia ibex.
Every back shows the Ge'ez numeral, "ብር" and the Latin numeral in the top-right and bottom-left corners: look there first.
Lion head and Ethiopia map are on every front: they do NOT identify a note.
Count a note once even if a fold or another note splits it into two visible pieces.
A note needs two agreeing signals (numeral, Ge'ez, amount text, picture, colour). Colour alone = "unclear". An edge strip with no numeral or picture = "unclear".
For each note return {"value": 5|10|50|100|200|null, "evidence": [...], "status": "read"|"partial"|"unclear"}. Never add up the notes.
```
