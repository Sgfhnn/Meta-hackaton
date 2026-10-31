"""Amharic and Oromo versions of every sentence the backend speaks. DRAFT: a native speaker checks
and corrects these before the demo; edit the text here, keeping the {placeholders}.

Placeholders are filled in by birr/voice/localize.py: amounts as digits for the screen and as words
for the voice (birr/voice/numbers.py). The keys match birr/voice/speech.py: fixed phrases by
constant name, the app's prompts by APP_PHRASES key.
"""

AM = {
    "fixed": {
        "RESCAN": "ሁሉንም ብሮች ማንበብ አልቻልኩም። ብሮቹን ዘርግተው ስልኩን ከላይ ይያዙ።",
        "NO_NOTES": "ምንም ብር አላየሁም። ስልኩን ከብሮችዎ በላይ ይዘው እንደገና ይሞክሩ።",
        "GIVE_UP": "ይቅርታ፣ እነዚህን ብሮች መቁጠር አልቻልኩም። እባክዎ የሚያምኑትን ሰው እርዳታ ይጠይቁ።",
        "TRY_AGAIN": "ይቅርታ፣ ማረጋገጥ አልቻልኩም። እባክዎ እንደገና ይሞክሩ።",
        "TOO_SLOW": "ይቅርታ፣ በጣም ዘገየ። እባክዎ እንደገና ይሞክሩ።",
        "SLOW_RESCAN": "በጣም ዘገየ። ብሮቹን ዘርግተው ስልኩን ሳያንቀሳቅሱ ይያዙና እንደገና ይቃኙ።",
        "STILL_COUNTING": "አሁንም እየቆጠርኩ ነው።",
        "BAD_REQUEST": "ይቅርታ፣ ያንን ፎቶ መጠቀም አልቻልኩም። እባክዎ እንደገና ያንሱ።",
        "NEED_PRICE": "ምን ያህል እንደከፈሉና ዋጋውን ይንገሩኝ፣ ከዚያ መልሱን ይቃኙ።",
        "VOICE_TODO": "የድምፅ ጥያቄዎች ገና ዝግጁ አይደሉም። ብሮችዎን ለመቁጠር ስክሪኑን ይንኩ።",
        "COUNT_PROMPT": "ብሮችዎን ዘርግተው ስልኩን ከላይ ይያዙና ስክሪኑን ይንኩ።",
        "INTENT_UNKNOWN": "ይቅርታ፣ አልገባኝም። ምን ያህል ብር እንዳለዎት ይጠይቁ፣ ወይም መልስዎን ለማረጋገጥ"
        " የከፈሉትንና ዋጋውን ይንገሩኝ።",
        "PRICE_OVER_PAID": "የነገሩኝ ዋጋ ከከፈሉት ይበልጣል። የከፈሉትንና ዋጋውን እንደገና ይንገሩኝ።",
        "BAD_AUDIO": "ይቅርታ፣ ያንን ቅጂ መጠቀም አልቻልኩም። እባክዎ እንደገና ይጠይቁ።",
        "NOT_HEARD": "ይቅርታ፣ አልሰማሁዎትም። እባክዎ እንደገና ይሞክሩ።",
        "FRAME_OK": "ጥሩ ነው። ሳያንቀሳቅሱ ይያዙ።",
        "FRAME_DARK": "በጣም ጨለማ ነው። ብርሃን ወዳለበት ቦታ ይሂዱ።",
        "FRAME_BRIGHT": "ብርሃኑ በጣም ያንጸባርቃል። ስልኩን ትንሽ ያዘንብሉ ወይም ከቀጥታ ብርሃን ይራቁ።",
        "FRAME_BLURRY": "ምስሉ ደብዝዟል። ስልኩን ሳያንቀሳቅሱ ይያዙ።",
        "FRAME_NO_NOTES": "ምንም ብር አላየሁም። ስልኩን ወደ ብሮችዎ ወደታች ያዙሩ።",
        "FRAME_FAR": "ስልኩን ወደ ብሮቹ ያቅርቡ።",
        "FRAME_CUT_LEFT": "አንዳንድ ብሮች በግራ በኩል ተቆርጠዋል። ስልኩን ትንሽ ወደ ግራ ያንቀሳቅሱ።",
        "FRAME_CUT_RIGHT": "አንዳንድ ብሮች በቀኝ በኩል ተቆርጠዋል። ስልኩን ትንሽ ወደ ቀኝ ያንቀሳቅሱ።",
        "FRAME_CUT_TOP": "አንዳንድ ብሮች ከላይ በኩል ተቆርጠዋል። ስልኩን ትንሽ ከእርስዎ ያርቁ።",
        "FRAME_CUT_BOTTOM": "አንዳንድ ብሮች ከታች በኩል ተቆርጠዋል። ስልኩን ትንሽ ወደ እርስዎ ያቅርቡ።",
        "ASSIST_SCAN": "እሺ። ስልኩን ከብሮችዎ በላይ ይያዙ። ጥሩ ሲሆን እነግርዎታለሁ።",
        "ASSIST_HELP": "ገንዘብዎን መቁጠርና መልስዎን ማረጋገጥ እችላለሁ። ስክሪኑን ነክተው ብሬን ቁጠር ይበሉ፣"
        " ወይም የከፈሉትንና ዋጋውን ይንገሩኝ።",
        "ASSIST_REPEAT": "እንደገና እነሆ።",
        "ASSIST_STOP": "እሺ። ሲፈልጉኝ ስክሪኑን ይንኩ።",
        "ASSIST_OFF_TOPIC": "ገንዘብዎን መቁጠር ወይም መልስዎን ማረጋገጥ እችላለሁ። ነክተው የሚፈልጉትን ይንገሩኝ።",
        "ASSIST_CAPTURE": "አሁን ፎቶውን አነሳለሁ። ሳያንቀሳቅሱ ይያዙ።",
        "ASSIST_CLOSED": "እሺ፣ ካሜራውን ዘግቻለሁ።",
        "LANG_SET_EN": "Okay, I will speak English now.",
        "LANG_SET_AM": "እሺ፣ ከአሁን ጀምሮ በአማርኛ እናገራለሁ።",
    },
    "app": {
        "counting": "እየቆጠርኩ ነው።",
        "stillCounting": "አሁንም እየቆጠርኩ ነው።",
        "failed": "ይቅርታ፣ መቁጠር አልቻልኩም። እባክዎ ስክሪኑን ነክተው እንደገና ይሞክሩ።",
        "noNetwork": "ሰርቨሩን ማግኘት አልቻልኩም። ኢንተርኔቱን አረጋግጠው ስክሪኑን ነክተው እንደገና ይሞክሩ።",
        "giveUp": "እነዚህን ብሮች መቁጠር አልቻልኩም። ብሮቹን ዘርግተው እንደገና ይጀምሩ።",
        "busy": "አሁንም እየቆጠርኩ ነው፣ እባክዎ ይጠብቁ።",
        "cameraNeeded": "ገንዘብዎን ለመቁጠር ካሜራው ያስፈልጋል። ለመፍቀድ ስክሪኑን ይንኩ።",
        "listening": "እያዳመጥኩ ነው።",
        "tooShort": "እየተናገሩ ስክሪኑን ይያዙ፣ ከዚያ ይልቀቁ።",
        "micNeeded": "በድምፅ ለመጠየቅ ማይክሮፎኑን ይፍቀዱ። አሁንም ነክተው መቁጠር ይችላሉ።",
        "heardFailed": "ይቅርታ፣ አልሰማሁዎትም። እባክዎ እንደገና ይሞክሩ።",
        "greeting": "ሰላም፣ ብር ነኝ። ብሮችዎን ጠረጴዛ ላይ ዘርግተው ያስቀምጡ። የትም ቦታ ነክተው የሚፈልጉትን ይንገሩኝ፣"
        " ለምሳሌ ብሬን ቁጠር።",
        "chooseLanguage": "ለእንግሊዝኛ የላይኛውን ግማሽ፣ ለአማርኛ የታችኛውን ግማሽ ይንኩ።",
        "holdStill": "ሳያንቀሳቅሱ ይያዙ፣ እየቆጠርኩ ነው።",
        "thinking": "አንድ ጊዜ።",
    },
    # You have 350 birr: one 200, one 100 and one 50.
    "total": "በአጠቃላይ {amount} ብር አለዎት፦ {notes}።",
    "note": "{count} ባለ {denom} ብር",
    "comma": "፣ ",
    "and": " እና ",
    "change": "{counted} ብር መልስ ተቀብለዋል። መቀበል የነበረብዎት {expected} ብር ነው።",
    "change_ok": "መልሱ ትክክል ነው።",
    "change_short": "{diff} ብር ጎድሎብዎታል።",
    "change_more": "ከሚገባው {diff} ብር በላይ ተቀብለዋል።",
    "change_prompt": "{paid} ብር ከፍለዋል፤ ዋጋው {price} ብር ነው። መልስዎ {change} ብር መሆን አለበት።"
    " ብሩን ዘርግተው ስልኩን ከላይ ይያዙና ስክሪኑን ይንኩ።",
    "change_prompt_none": "{paid} ብር ከፍለዋል፤ ዋጋው {price} ብር ነው። መልስ የለዎትም።",
    "guide": {
        "merged": "ብሮቹ እንዳይነካኩና እንዳይደራረቡ ዘርግተው ያስቀምጡ፣ ከዚያ ስልኩን ሳያንቀሳቅሱ ይያዙ።",
        "covered": "{position} ያለ አንድ ብር ተሸፍኗል። ሙሉውን እንዳየው ያውጡት፣ ከዚያ ስልኩን ሳያንቀሳቅሱ ይያዙ።",
        "hidden": "{position} ያለው ብር በደንብ አይታይም። ከሌሎቹ ያርቁት፣ ከዚያ ስልኩን ሳያንቀሳቅሱ ይያዙ።",
        "folded": "{position} ያለው ብር ታጥፏል። ዘርግተው ያስቀምጡት፣ ከዚያ ስልኩን ሳያንቀሳቅሱ ይያዙ።",
        "closer": "ስልኩን {position} ወዳለው ብር ያቅርቡ፣ ከዚያ ሳያንቀሳቅሱ ይያዙ።",
        "dark": "በጣም ጨለማ ነው። ብርሃን ወዳለበት ቦታ ይሂዱ፣ ከዚያ ስልኩን ሳያንቀሳቅሱ ይያዙ።",
    },
    # From the user's point of view: far = away from them, near = close to them.
    "positions": {
        "far left": "ራቅ ብሎ በግራ በኩል",
        "far center": "ራቅ ብሎ በመሃል",
        "far right": "ራቅ ብሎ በቀኝ በኩል",
        "middle left": "በግራ በኩል",
        "middle": "በመሃል",
        "middle right": "በቀኝ በኩል",
        "near left": "አጠገብዎ በግራ በኩል",
        "near center": "አጠገብዎ በመሃል",
        "near right": "አጠገብዎ በቀኝ በኩል",
    },
}

OM = {
    "fixed": {
        "RESCAN": "Maallaqa hunda dubbisuu hin dandeenye. Bal'isii kaa'iitii bilbila isaan irra qabadhu.",
        "NO_NOTES": "Maallaqa tokkollee hin argine. Bilbila maallaqa kee irra qabadhuutii irra"
        " deebi'ii yaali.",
        "GIVE_UP": "Dhiifama, maallaqa kana lakkaa'uu hin dandeenye. Nama amantu gargaarsa gaafadhu.",
        "TRY_AGAIN": "Dhiifama, mirkaneessuu hin dandeenye. Irra deebi'ii yaali.",
        "TOO_SLOW": "Dhiifama, baay'ee turte. Irra deebi'ii yaali.",
        "SLOW_RESCAN": "Baay'ee turte. Maallaqa bal'isi, bilbila tasgabbeessiitii irra deebi'ii"
        " lakkaa'i.",
        "STILL_COUNTING": "Ammas lakkaa'aan jira.",
        "BAD_REQUEST": "Dhiifama, suuraa sana fayyadamuu hin dandeenye. Irra deebi'ii kaasi.",
        "NEED_PRICE": "Hammam akka kaffalte fi gatii natti himi, achii jijjiirraa kee lakkaa'i.",
        "VOICE_TODO": "Gaaffiin sagaleen ammaaf qophaa'ee hin jiru. Maallaqa kee lakkaa'uuf"
        " iskiriinii tuqi.",
        "COUNT_PROMPT": "Maallaqa kee bal'isi, bilbila isaan irra qabadhuutii iskiriinii tuqi.",
        "INTENT_UNKNOWN": "Dhiifama, natti hin galle. Maallaqa hammam akka qabdu gaafadhu, yookaan"
        " jijjiirraa mirkaneessuuf waan kaffalte fi gatii natti himi.",
        "PRICE_OVER_PAID": "Gatiin ati jette waan kaffalte caala. Hammam akka kaffalte fi gatii irra"
        " deebi'ii natti himi.",
        "BAD_AUDIO": "Dhiifama, sagalee sana fayyadamuu hin dandeenye. Irra deebi'ii gaafadhu.",
        "NOT_HEARD": "Dhiifama, si hin dhageenye. Irra deebi'ii yaali.",
        "FRAME_OK": "Gaarii dha. Tasgabbaa'ii qabadhu.",
        "FRAME_DARK": "Baay'ee dukkana. Iddoo ifa qabutti deemi.",
        "FRAME_BRIGHT": "Ifni baay'ee calaqqisa. Bilbila xiqqoo jallisi yookaan ifa kallattii irraa fagaadhu.",
        "FRAME_BLURRY": "Suuraan hin mul'atu. Bilbila tasgabbeessii qabadhu.",
        "FRAME_NO_NOTES": "Maallaqa tokkollee hin argine. Bilbila gara maallaqa keetti gadi qabi.",
        "FRAME_FAR": "Bilbila maallaqatti dhiheessi.",
        "FRAME_CUT_LEFT": "Maallaqni tokko tokko bitaan citeera. Bilbila xiqqoo gara bitaatti sochoosi.",
        "FRAME_CUT_RIGHT": "Maallaqni tokko tokko mirgaan citeera. Bilbila xiqqoo gara mirgaatti sochoosi.",
        "FRAME_CUT_TOP": "Maallaqni tokko tokko gubbaan citeera. Bilbila xiqqoo si irraa fageessi.",
        "FRAME_CUT_BOTTOM": "Maallaqni tokko tokko gadiin citeera. Bilbila xiqqoo gara keetti dhiheessi.",
        "ASSIST_SCAN": "Tole. Bilbila maallaqa kee irra qabadhu. Yeroo gaarii ta'u sitti hima.",
        "ASSIST_HELP": "Maallaqa kee lakkaa'uu fi jijjiirraa mirkaneessuu nan danda'a. Iskiriinii"
        " tuqiitii maallaqa koo lakkaa'i jedhi, yookaan waan kaffalte fi gatii natti himi.",
        "ASSIST_REPEAT": "Kunoo irra deebi'ee.",
        "ASSIST_STOP": "Tole. Yeroo na barbaaddu iskiriinii tuqi.",
        "ASSIST_OFF_TOPIC": "Maallaqa kee lakkaa'uu yookaan jijjiirraa mirkaneessuu nan danda'a."
        " Tuqiitii waan barbaaddu natti himi.",
        "ASSIST_CAPTURE": "Amma suuraa kaasa. Osoo hin sochoosin qabadhu.",
        "ASSIST_CLOSED": "Tole, kaameraa cufeera.",
        "LANG_SET_EN": "Okay, I will speak English now.",
        "LANG_SET_AM": "Tole, amma Afaan Amaaraatiin nan dubbadha.",
    },
    "app": {
        "counting": "Lakkaa'aan jira.",
        "stillCounting": "Ammas lakkaa'aan jira.",
        "failed": "Dhiifama, lakkaa'uu hin dandeenye. Irra deebi'uuf tuqi.",
        "noNetwork": "Sarvarii argachuu hin dandeenye. Interneetii mirkaneessiitii irra deebi'uuf"
        " tuqi.",
        "giveUp": "Maallaqa kana lakkaa'uu hin dandeenye. Bal'isiitii irra deebi'ii jalqabi.",
        "busy": "Ammas lakkaa'aan jira, maaloo eegi.",
        "cameraNeeded": "Maallaqa kee lakkaa'uuf kaameraan barbaachisa. Hayyamuuf iskiriinii tuqi.",
        "listening": "Dhaggeeffachaan jira.",
        "tooShort": "Yeroo dubbattu iskiriinii qabadhu, achii gadi lakkisi.",
        "micNeeded": "Sagaleedhaan gaafachuuf maaykiroofoonii hayyami. Ammas tuquun lakkaa'uu"
        " ni dandeessa.",
        "heardFailed": "Dhiifama, si hin dhageenye. Irra deebi'ii yaali.",
        "greeting": "Akkam, ani Birr. Maallaqa kee minjaala irratti diriirsii kaa'i. Bakka kamiyyuu"
        " tuqiitii waan barbaaddu natti himi, fakkeenyaaf maallaqa koo lakkaa'i.",
        "chooseLanguage": "Ingiliffaaf walakkaa gubbaa, Afaan Amaaraaf walakkaa jalaa tuqi.",
        "holdStill": "Tasgabbaa'ii qabadhu, lakkaa'aan jira.",
        "thinking": "Xiqqoo eegi.",
    },
    # Oromo keeps the total only; the note-by-note list waits for a native speaker's wording.
    "total": "Waliigala qarshii {amount} qabda.",
    "note": None,
    "comma": ", ",
    "and": " fi ",
    "change": "Jijjiirraa qarshii {counted} argatte. Qarshii {expected} argachuu qabda.",
    "change_ok": "Jijjiirraan kee sirrii dha.",
    "change_short": "Qarshii {diff} hir'ata.",
    "change_more": "Kan eegamee caalaa qarshii {diff} dabalataa argatte.",
    "change_prompt": "Gatii qarshii {price}f qarshii {paid} kaffalte. Jijjiirraan kee qarshii"
    " {change} ta'uu qaba. Bal'isii bilbila irra qabadhuutii iskiriinii tuqi.",
    "change_prompt_none": "Gatii qarshii {price}f qarshii {paid} kaffalte. Jijjiirraa hin qabdu.",
    "guide": {
        "merged": "Maallaqni wal hin tuqin, wal irra hin taa'in; bal'isii kaa'i, achii bilbila"
        " sochoosuu dhiisi.",
        "covered": "Maallaqni tokko {position} haguugameera. Guutummaatti akkan arguuf baasi,"
        " achii bilbila sochoosuu dhiisi.",
        "hidden": "Maallaqni {position} jiru sirriitti hin mul'atu. Kanneen biroo irraa fageessi,"
        " achii bilbila sochoosuu dhiisi.",
        "folded": "Maallaqni {position} jiru dachaa'eera. Diriirsii kaa'i, achii bilbila sochoosuu"
        " dhiisi.",
        "closer": "Bilbila maallaqa {position} jirutti dhiheessi, achii sochoosuu dhiisi.",
        "dark": "Baay'ee dukkana. Iddoo ifa qabutti deemi, achii bilbila sochoosuu dhiisi.",
    },
    "positions": {
        "far left": "fagoo bitaa irratti",
        "far center": "fagoo gidduu irratti",
        "far right": "fagoo mirga irratti",
        "middle left": "bitaa irratti",
        "middle": "gidduu irratti",
        "middle right": "mirga irratti",
        "near left": "dhiyoo bitaa irratti",
        "near center": "dhiyoo gidduu irratti",
        "near right": "dhiyoo mirga irratti",
    },
}

TEMPLATES = {"am": AM, "om": OM}
