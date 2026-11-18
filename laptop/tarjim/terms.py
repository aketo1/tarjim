"""Game words that are not names.

A game says "the fence" for a dealer in stolen goods (not «السياج»), "case the bank" for
scouting it (not «نقاضي البنك»), "lose the law" for escaping the police (not «اخسر القانون»),
"hogtie", "parley", "sworn brother", "Kiryu-chan"... The model knows plain English, so these
are put into plain English before it reads the line, and the few Arabic words it still gets
wrong are put right after it.

Every game gets GENERAL; a series (Red Dead, GTA, The Last of Us, Yakuza / Like a Dragon)
gets its own words as well. Names of people, places and gangs are in the game's list
(packs/) instead. The phone app has the same lists in Terms.kt: keep the two alike.
"""

from __future__ import annotations

import re

SERIES_IDS = {
    "rdr": ("rdr1", "rdr2"),
    "gta": ("gta-sa", "gta4", "gta5", "gta6"),
    "tlou": ("tlou1", "tlou2"),
    "yakuza": ("yakuza0", "yakuza-kiwami", "yakuza-kiwami2", "yakuza3", "yakuza4", "yakuza5", "yakuza6",
               "lad7", "lad8", "lad-gaiden", "lad-pirate"),
}
_TITLE_HINTS = (("red dead", "rdr"), ("grand theft auto", "gta"), ("gta", "gta"), ("last of us", "tlou"),
                ("yakuza", "yakuza"), ("like a dragon", "yakuza"))


def series_of(profile: str, title: str = "") -> str:
    """The series of a game profile ("" for none): by the library's id, else by its title."""
    for series, ids in SERIES_IDS.items():
        if profile in ids:
            return series
    text = f"{title} {profile}".lower().replace("-", " ").replace("_", " ")
    return next((series for hint, series in _TITLE_HINTS if hint in text), "")


_I = re.IGNORECASE
_THINGS = r"(?:bank|place|house|store|shop|joint|train|town|camp|ranch|mansion|manor|station|saloon|farm|plantation)"
_CHASERS = r"(?:the law|the cops|the police|the posse|the lawmen|the bounty hunters|the pinkertons|the feds)"
_SENT_START = r"(?:^|(?<=[.!?] )|(?<=[.!?]\" ))"
# "case" is a verb only after these ("in case the house..." is not)
_CASE_VERB = (r"(?:^|(?<=\bto )|(?<=\bwill )|(?<='ll )|(?<=\blet's )|(?<=\bgo )|(?<=\band )|(?<=\bshould )|"
              r"(?<=\bmust )|(?<=\bcan )|(?<=\bcould )|(?<=\bgonna )|(?<=\bwe )|(?<=\byou )|(?<=\bI ))")
_AUX = r"(?:is|are|'s|was|were|will|'ll|has|have|had|might|may|could|would|can|won't|ain't|be|been)"
_LAW_HUNTS = (r"(?:after|coming|here|onto|on to|on our|on your|on his|on their|on my|close|everywhere|outside|"
              r"waiting|chasing|looking for|searching|hunting|find|finds|found|catch|catches|caught|get|gets|got|"
              r"show up|shows up|showed up|turn up|turns up|turned up|arrive|arrives|arrived|all over)")

Rule = tuple[re.Pattern, str]

# Every game: western and crime-game words, and game words the model reads as other words.
GENERAL: tuple[Rule, ...] = (
    (re.compile(r"\bhog-?ties? (him|her|them|it|me|us)\b", _I), r"tie \1 up"),
    (re.compile(r"\bhog-?ties? (the|that|this|a|an) (\w+)\b", _I), r"tie up \1 \2"),
    (re.compile(r"\bhog-?tied\b", _I), "tied up"),
    (re.compile(r"\bhog-?tying\b", _I), "tying up"),
    (re.compile(r"\bhog-?ties?\b", _I), "tie up"),
    (re.compile(r"\blasso(?:es)? (him|her|them|it)\b", _I), r"catch \1 with your rope"),
    (re.compile(r"\blasso(?:es)? (the|that|this|a|an) (\w+)\b", _I), r"catch \1 \2 with your rope"),
    (re.compile(r"\blassoed\b", _I), "caught with a rope"),
    (re.compile(r"\b(your|my|a|the|his|her) lasso\b", _I), r"\1 rope"),
    (re.compile(r"\bparleyed\b", _I), "negotiated"),
    (re.compile(r"\bparleying\b", _I), "negotiating"),
    (re.compile(r"\b(a|the) parley\b", _I), r"\1 negotiation"),
    (re.compile(r"\bparleys?\b", _I), "negotiate"),
    (re.compile(rf"{_CASE_VERB}case (the|this|that|a) ({_THINGS})\b", _I), r"scout \1 \2"),
    (re.compile(rf"\bcased (the|this|that|a) ({_THINGS})\b", _I), r"scouted \1 \2"),
    (re.compile(rf"\bcasing (the|this|that|a) ({_THINGS})\b", _I), r"scouting \1 \2"),
    (re.compile(rf"\b(?:lose|shake off|shake) ({_CHASERS})", _I), r"escape from \1"),
    (re.compile(rf"\b(?:lost|shook off|shook) ({_CHASERS})", _I), r"escaped from \1"),
    (re.compile(rf"\b(?:losing|shaking off|shaking) ({_CHASERS})", _I), r"escaping from \1"),
    (re.compile(r"\b(?:shake|shook) (them|him|her|'em) off\b", _I), r"escape from \1"),
    (re.compile(r"(?:^|(?<=[.!?,;] )|(?<=[.!?]\" ))(?:lose|shake) (them|him|her|'em)(?![\w'])", _I), r"escape from \1"),
    (re.compile(r"\b(from|run from|running from|hide from|hiding from|on the run from|wanted by) the law\b", _I),
     r"\1 the police"),
    (re.compile(rf"\bthe law\b(?=\s+(?:{_AUX}\s+)?(?:gonna\s+|going to\s+|be\s+)?{_LAW_HUNTS}\b)", _I), "the police"),
    (re.compile(r"\b(we|you|I)(?:'ve| have)? got (?:some )?company\b", _I), r"\1 have visitors"),
    (re.compile(r"\b(we|you|I) have (?:some )?company\b", _I), r"\1 have visitors"),
    (re.compile(r"\b(?:lay|lie) low\b", _I), "stay out of sight"),
    (re.compile(r"\b(?:laying|lying) low\b", _I), "staying out of sight"),
    (re.compile(r"\bsaddle up\b", _I), "get on your horse"),
    (re.compile(r"\bgaining on (us|you|me|him|her|them)\b", _I), r"getting closer to \1"),
    (re.compile(r"(?:(?<=\bwe )|(?<=\blet's )|(?<='ll )|(?<=\bto )|(?<=\bgonna ))hit (the|a|that) "
                r"(train|bank|stagecoach|coach|store|shop|jewelry store|armored car|convoy)\b", _I), r"rob \1 \2"),
    (re.compile(r"\bsafe ?houses\b", _I), "hideouts"),
    (re.compile(r"\bsafe ?house\b", _I), "hideout"),
    (re.compile(r"\b(?:you've got|you have|you got|you're at|you are at) an? (\w+)[- ]star wanted level\b", _I),
     r"the police are chasing you with \1 stars"),
    (re.compile(r"\bwanted level\b", _I), "pursuit level"),
    (re.compile(r"\bchop shop\b", _I), "stolen car workshop"),
    (re.compile(r"\bloot (the|those|these|his|her|their|all the|every) "
                r"(bodies|body|corpses|corpse|dead|house|wagon|camp|place|safe|chest|wreck)\b", _I),
     r"search \1 \2 for valuables"),
    (re.compile(r"\bfast[- ]travel(?:led|ed)? to\b", _I), "travel quickly to"),
    (re.compile(r"\b(?:your|the) horse's bonding(?: level)? (?:went up|has gone up|increased|has increased|rose|"
                r"has risen|improved|has improved)\b", _I), "your bond with your horse grew stronger"),
    (re.compile(r"\b(?:your|the) horse's bonding(?: level)?\b", _I), "your bond with your horse"),
    (re.compile(r"\bbonding level\b", _I), "bond"),
    (re.compile(rf"{_SENT_START}(?:go )?fish(?:ing)? (in|at|near|from|off) (?!.*\b(?:are|is|were|was|swim|swims|live|lives)\b)",
                _I), r"catch fish \1 "),
    (re.compile(r"\bchores\b", _I), "tasks"),
    (re.compile(r"\bheld up (the|a|that) (stagecoach|coach|train|bank|store|shop|wagon|stage)\b", _I), r"robbed \1 \2"),
    (re.compile(r"\bhold(?:ing)? up (the|a|that) (stagecoach|coach|train|bank|store|shop|wagon|stage)\b", _I), r"rob \1 \2"),
    (re.compile(r"\b(run|runs|ran|running) off\b(?! (?:the|a) (?:road|bridge|cliff|edge|track))", _I), r"\1 away"),
    (re.compile(r"\b(the|a|that|your) gunsmith\b", _I), r"\1 gun shop"),
)

# A rule of a series, with an optional condition the whole line must meet.
SeriesRule = tuple[re.Pattern, str, "re.Pattern | None"]
_SELLING = re.compile(r"\b(?:sell|sold|selling|stolen|loot|valuables|trinkets|jewel|jewelry|take it|price|pay|buys|"
                      r"fenced|goods)\b", _I)
_LAW_KEEP_BEFORE = ("against", "above", "break", "breaking", "broke", "broken", "obey", "obeying", "within", "by",
                    "under", "follow", "following", "respect", "it's", "is", "that's", "was", "uphold", "upholding",
                    "enforce", "I'm", "am", "letter of", "according to", "eyes of")
_LAW_KEEP = "".join(f"(?<!\\b{w} )" for w in _LAW_KEEP_BEFORE)

SERIES: dict[str, tuple[SeriesRule, ...]] = {
    "rdr": (
        # in a western "the law" is the lawmen, except "against the law", "it's the law", ...
        (re.compile(rf"{_LAW_KEEP}\bthe law\b(?!\s+(?:of|says|said|is clear|and order|is the law))", _I), "the police", None),
        (re.compile(r"\b(the|a|that|this|another|their|his|her|your) posse\b", _I), r"\1 pursuers", None),
        (re.compile(r"\b(your|my|his|her|the|a|that) repeater\b", _I), r"\1 rifle", None),
        (re.compile(r"\b(the|a|that|your) trapper\b", _I), r"\1 fur trader", None),
        (re.compile(r"\b(a|the|any|your|that) fence\b", _I), r"\1 stolen goods dealer", _SELLING),
        (re.compile(r"\bfence (it|them|this|that|these|those)\b(?! off| in)", _I), r"sell \1 as stolen goods", None),
    ),
    "yakuza": (
        # "-san" stays: without it the model takes a name like "Majima" for a woman's
        (re.compile(r"\b([A-Z][a-z]+)-(?:chan|kun|sama|senpai|sensei|dono|han|bo)\b"), r"\1", None),
        (re.compile(r"\b(?:nii-?san|nii-?chan|onii-?san|aniki)\b", _I), "big brother", None),
        (re.compile(r"\b(?:nee-?san|onee-?san|ane-?san)\b", _I), "big sister", None),
        (re.compile(r"\b(?:oyaji|oyassan)\b", _I), "old man", None),
        (re.compile(r"\boyabun\b", _I), "boss", None),
        (re.compile(r"\bkyodai\b", _I), "brother", None),
        (re.compile(r"\bpatriarch of\b", _I), "head of", None),
        (re.compile(r"\bpatriarch\b", _I), "family head", None),
        (re.compile(r"\bsworn brothers\b", _I), "brothers by oath", None),
        (re.compile(r"\bsworn brother\b", _I), "brother by oath", None),
    ),
}

# Arabic the model still gets wrong: (English that must be in the line or None, wrong, right).
AR_FIXES: dict[str, tuple[tuple["re.Pattern | None", str, str], ...]] = {
    "": (
        (None, "بطاقات التموينية", "بطاقات التموين"),
    ),
    "tlou": (
        (re.compile(r"\bspores?\b", _I), "الجراثيم", "الأبواغ"),
        (re.compile(r"\bspores?\b", _I), "جراثيم", "أبواغ"),
    ),
}
_ANY = re.compile("|".join(f"(?:{rx.pattern})" for rx, _ in GENERAL), _I)


def rewrite(english: str, series: str = "") -> str:
    """The line in plain English for the model: game words, then the series' words."""
    if _ANY.search(english):
        for rx, repl in GENERAL:
            english = rx.sub(repl, english)
    for rx, repl, cond in SERIES.get(series, ()):
        if cond is None or cond.search(english):
            english = rx.sub(repl, english)
    return english


def fix_arabic(arabic: str, english: str, series: str = "") -> str:
    for group in ("", series) if series else ("",):
        for rx, wrong, right in AR_FIXES.get(group, ()):
            if wrong in arabic and (rx is None or rx.search(english)):
                arabic = arabic.replace(wrong, right)
    return arabic


# -- commands written as verbal nouns -------------------------------------------------
#
# The model often writes a command as a verbal noun: "Buy some tonic" → «شراء بعض منشط»,
# "Pay the protection money" → «دفع أموال الحماية», "Negotiate with them first" → «التفاوض معهم».
# When the English line (or the part after "Name,") opens with one of these verbs and the
# Arabic with its verbal noun, the command is written instead: «اشتر»، «ادفع»، «تفاوض». Its
# gender is put right afterwards with the rest of the line (gender.py).

VERB_NOUNS: dict[str, dict[str, str]] = {
    "buy": {"شراء": "اشتر"},
    "sell": {"بيع": "بع"},
    "pay": {"دفع": "ادفع"},
    "hunt": {"صيد": "اصطد"},
    "catch": {"صيد": "اصطد", "القبض": "اقبض", "الإمساك": "أمسك", "إمساك": "أمسك"},
    "remove": {"إزالة": "أزل"},
    "negotiate": {"التفاوض": "تفاوض"},
    "escape": {"الهروب": "اهرب", "الهرب": "اهرب", "هروب": "اهرب", "هرب": "اهرب"},
    "run": {"الركض": "اركض", "الهروب": "اهرب"},
    "cook": {"طبخ": "اطبخ", "طهي": "اطبخ"},
    "craft": {"صنع": "اصنع", "صناعة": "اصنع"},
    "make": {"صنع": "اصنع"},
    "rob": {"سرقة": "اسرق"},
    "steal": {"سرقة": "اسرق"},
    "search": {"البحث": "ابحث", "بحث": "ابحث", "تفتيش": "فتّش"},
    "look": {"البحث": "ابحث", "النظر": "انظر"},
    "ride": {"ركوب": "اركب"},
    "feed": {"إطعام": "أطعم"},
    "clean": {"تنظيف": "نظّف"},
    "brush": {"تنظيف": "نظّف"},
    "save": {"حفظ": "احفظ", "إنقاذ": "أنقذ"},
    "rescue": {"إنقاذ": "أنقذ"},
    "collect": {"جمع": "اجمع"},
    "gather": {"جمع": "اجمع"},
    "carry": {"حمل": "احمل"},
    "kill": {"قتل": "اقتل"},
    "drink": {"شرب": "اشرب"},
    "follow": {"اتباع": "اتبع"},
    "stay": {"البقاء": "ابق", "الابتعاد": "ابتعد"},
    "keep": {"الابتعاد": "ابتعد", "الحفاظ": "حافظ"},
    "go": {"الذهاب": "اذهب"},
    "get": {"الحصول": "احصل"},
    "watch": {"مشاهدة": "شاهد", "مراقبة": "راقب"},
    "bring": {"إحضار": "أحضر", "جلب": "اجلب"},
    "fetch": {"إحضار": "أحضر", "جلب": "اجلب"},
    "use": {"استخدام": "استخدم"},
    "return": {"إعادة": "أعد", "العودة": "عد"},
    "deliver": {"تسليم": "سلّم"},
    "hand": {"تسليم": "سلّم"},
    "drive": {"قيادة": "قد"},
    "draw": {"سحب": "اسحب"},
    "pull": {"سحب": "اسحب"},
    "take": {"أخذ": "خذ", "اتخاذ": "خذ"},
    "grab": {"أخذ": "خذ", "الإمساك": "أمسك"},
    "put": {"وضع": "ضع"},
    "place": {"وضع": "ضع"},
    "leave": {"ترك": "اترك", "مغادرة": "غادر"},
    "shoot": {"إطلاق": "أطلق"},
    "fire": {"إطلاق": "أطلق"},
    "find": {"العثور": "اعثر", "إيجاد": "جد"},
    "locate": {"تحديد": "حدد"},
    "wait": {"الانتظار": "انتظر", "انتظار": "انتظر"},
    "check": {"التحقق": "تحقق", "فحص": "افحص"},
    "hide": {"الاختباء": "اختبئ", "إخفاء": "أخف"},
    "approach": {"الاقتراب": "اقترب"},
    "listen": {"الاستماع": "استمع"},
    "stop": {"التوقف": "توقف", "إيقاف": "أوقف"},
    "tie": {"ربط": "اربط"},
    "travel": {"السفر": "سافر"},
    "open": {"فتح": "افتح"},
    "close": {"إغلاق": "أغلق"},
    "help": {"مساعدة": "ساعد", "المساعدة": "ساعد"},
    "skin": {"سلخ": "اسلخ"},
    "donate": {"التبرع": "تبرع"},
    "head": {"التوجه": "توجه"},
    "meet": {"مقابلة": "قابل", "لقاء": "قابل"},
    "talk": {"التحدث": "تحدث"},
    "speak": {"التحدث": "تحدث"},
    "defend": {"الدفاع": "دافع"},
    "protect": {"حماية": "احم"},
    "attack": {"مهاجمة": "هاجم", "الهجوم": "هاجم"},
    "destroy": {"تدمير": "دمّر"},
    "eat": {"تناول": "تناول"},
    "give": {"إعطاء": "أعط"},
    "tell": {"إخبار": "أخبر"},
    "send": {"إرسال": "أرسل"},
    "call": {"الاتصال": "اتصل"},
    "throw": {"رمي": "ارم"},
    "jump": {"القفز": "اقفز"},
    "swim": {"السباحة": "اسبح"},
    "track": {"تعقب": "تعقب", "تتبع": "تتبع"},
    "sneak": {"التسلل": "تسلل"},
    "climb": {"تسلق": "تسلق"},
}
# The word after the first one shows it is a noun, not a command: "Escape is impossible".
_NOT_A_COMMAND_NEXT = {"is", "was", "are", "were", "will", "would", "can", "could", "should", "has", "have", "had",
                       "isn't", "wasn't", "won't", "might", "must", "may", "did", "does", "do", "makes", "made",
                       "seems", "looks", "needs", "takes", "sounds", "feels", "costs", "of", "'s", "and", "or"}
_EN_VOCATIVE = re.compile(r"^(?:[A-Z][\w'.\-]*\s+){0,2}[A-Z][\w'.\-]*,\s+")
_AR_WORD = re.compile(r"[ء-يّ]+")
_SUFFIX = ("", "ه", "ها", "هم", "هما", "ني", "نا")


def _command(token: str, nouns: dict[str, str]) -> str | None:
    for noun, cmd in nouns.items():
        if token.startswith(noun) and token[len(noun):] in _SUFFIX:
            return cmd + token[len(noun):]
    return None


def commands_not_nouns(arabic: str, english: str) -> str:
    """The first command of the line, and those joined to it by «و», as commands."""
    en = english.lstrip(" \"'-–—")
    start = 0
    vm = _EN_VOCATIVE.match(en)
    if vm:
        en = en[vm.end():]
        comma = arabic.find("،")
        if comma < 0:
            comma = arabic.find(",")
        if comma < 0 or comma > 40:
            return arabic
        start = comma + 1
    words = en.split()
    if len(words) < 2:
        return arabic
    verb, nxt = words[0].lower().strip(",.!?"), words[1].lower().strip(",.!?")
    nouns = VERB_NOUNS.get(verb)
    if not nouns or nxt in _NOT_A_COMMAND_NEXT:
        return arabic
    m = _AR_WORD.search(arabic, start)
    if not m or arabic[start:m.start()].strip(" «\"'"):
        return arabic
    cmd = _command(m.group(0), nouns)
    if cmd is None:
        return arabic
    out = arabic[:m.start()] + cmd + arabic[m.end():]
    # «... واتخاذ اللحوم» for "... and take the meat": the next commands of the sentence
    end = len(out)
    for stop in ".!؟?":
        k = out.find(stop, m.start())
        if 0 <= k < end:
            end = k
    pos = m.start() + len(cmd)
    for v in re.findall(r"\band (?:then )?([a-z]+)\b", en.lower()):
        later = VERB_NOUNS.get(v)
        if not later:
            continue
        for w in _AR_WORD.finditer(out, pos, end):
            tok = w.group(0)
            if tok.startswith("و") and (c := _command(tok[1:], later)):
                out = out[:w.start()] + "و" + c + out[w.end():]
                pos = w.start() + 1 + len(c)
                end += len(c) + 1 - len(tok)
                break
    return out
