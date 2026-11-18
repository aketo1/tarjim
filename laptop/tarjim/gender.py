"""Masculine and feminine "you" in commands, for whole families of verbs at once.

The translation model guesses the gender of the person spoken to: "Javier, cover the left
side" came out as «غطّي» (said to a woman), "Spit it out" as «ابصقيها». The program knows
better (a man's name, a woman's name, or nobody named: masculine by default), so commands
are put in the right form afterwards.

One list of masculine singular commands is the source. A feminine form is the masculine
plus «ي» for most verbs (اذهب/اذهبي، أعطِ/أعطي، غطِّ/غطّي، اختبئ/اختبئي); the hollow and
hamza verbs that do not follow that are listed as pairs (قم/قومي، اهدأ/اهدئي). Object
endings are added to both (ساعدني/ساعديني، خذه/خذيه، قلها/قوليها).

Only words in these lists change, and only where a command can stand: at the start of a
sentence or clause, after «و» or «ف» joined to it, or after a word like «ثم» or «الآن».
"""

from __future__ import annotations

import re

# Masculine singular commands, written as the subtitles show them (no short vowels; shadda kept).
MASC = (
    "اذهب", "ارجع", "قف", "اجلس", "انهض", "تعال", "اركض", "اهرب", "اختبئ", "انبطح", "اخفض", "ارفع",
    "انتظر", "اسمع", "استمع", "انظر", "تفقد", "ابحث", "جد", "اعثر", "خذ", "أعط", "هات", "ضع", "ألق",
    "ارم", "اترك", "دع", "ساعد", "أنقذ", "احم", "غطّ", "راقب", "احرس", "احذر", "انتبه", "تمهل", "تحرك",
    "توقف", "أسرع", "امش", "اركب", "انزل", "اصعد", "ادخل", "اخرج", "افتح", "أغلق", "اقفل", "أطفئ",
    "أشعل", "احمل", "اسحب", "ادفع", "أمسك", "تمسك", "اقبض", "اربط", "فكّ", "اقتل", "أطلق", "صوّب",
    "اضرب", "قاتل", "ادفن", "احفر", "اشرب", "استرح", "اسكت", "اصمت", "اخرس", "تكلم", "أخبر", "اشرح",
    "اسأل", "أجب", "اكتب", "تذكر", "انس", "صدّق", "سامح", "ثق", "جرّب", "حاول", "فكّر", "اختر", "اتبع",
    "اتصل", "ابق", "ابتعد", "اقترب", "تراجع", "ارحل", "اصبر", "استعد", "تجهز", "أحضر", "اجلب", "أرسل",
    "سلّم", "نظّف", "اغسل", "البس", "اخلع", "اشتر", "احتم", "أكمل", "واصل", "استمر", "انطلق", "اهجم",
    "انسحب", "اعبر", "استدر", "التفت", "ابتسم", "اضحك", "ابك", "اصرخ", "اهمس", "اقرأ", "ابصق", "اهدأ",
    "تماسك", "تمالك", "ارتح", "أبق", "ارقص", "عانق", "قبّل", "اغفر", "اهتم", "اعتن", "انصت", "تأكد",
    "تصرّف", "تعلّم", "علّم", "خبّئ", "اسرق", "اقطع", "اصنع", "أصلح", "املأ", "أفرغ", "اصمد", "انج",
    "حافظ", "ناول", "أبعد", "تعامل", "اذكر", "تخيّل", "انقل", "أوقف", "تجاهل", "لاحق", "طارد", "اتجه",
    "استخدم", "أظهر", "اعرض", "اعتمد", "جهّز", "اجمع", "فتّش", "أطعم", "ناد", "امض", "تحقق", "أخرج",
    "أدخل", "اسمح", "اركع", "انحن", "اقفز", "تقدّم", "تأخّر", "ادع", "اعترف", "اعتذر", "استسلم",
    "توقّع", "اختف", "أمّن", "حرّك", "ركّز", "اهدئ", "ارتد", "خلّص", "اعطف", "اصفح", "احتفظ",
    # game commands (terms.py writes some of them for a verbal noun)
    "اسلخ", "اطبخ", "احفظ", "احصل", "شاهد", "غادر", "افحص", "سافر", "تبرع", "توجه", "قابل", "تحدث",
    "دافع", "هاجم", "دمّر", "تناول", "اسبح", "تعقب", "تسلل", "تفاوض", "حدد", "احزم",
)
# Feminine forms that are not "masculine + ي" (hollow verbs, a hamza that changes its seat).
IRREGULAR = {
    "قومي": "قم", "عودي": "عد", "نامي": "نم", "قولي": "قل", "كوني": "كن", "خافي": "خف", "سيري": "سر",
    "بيعي": "بع", "عيشي": "عش", "دوري": "در", "زوري": "زر", "ذوقي": "ذق", "صومي": "صم", "طيري": "طر",
    "ميلي": "مل", "موتي": "مت", "ارتاحي": "ارتح", "اهدئي": "اهدأ", "اقرئي": "اقرأ", "ابدئي": "ابدأ",
    "املئي": "املأ", "نالي": "نل", "أعيدي": "أعد", "أقيمي": "أقم", "أريحي": "أرح", "أجيبي": "أجب",
    "اختاري": "اختر", "استريحي": "استرح", "أطيعي": "أطع", "أضيفي": "أضف",
    "اصطادي": "اصطد", "أزيلي": "أزل",
}
# The model's spellings of a feminine command that should carry «ئ»: اقرأي → اقرئي.
SPELLING = {"اقرأي": "اقرئي", "اهدأي": "اهدئي", "ابدأي": "ابدئي", "املأي": "املئي", "اهدأى": "اهدئي"}

# "Don't …" said to one person: «لا تفعلي» to a woman, «لا تفعل» to a man. Sound verbs only:
# with a weak last letter «لا تمشي» could also be "she does not walk".
PROHIBIT = (
    "تقلق", "تتحرك", "تذهب", "تفعل", "تصدر", "تكذب", "تلمس", "تطلق", "تقتل", "تنظر", "تلتفت", "تتكلم",
    "تتحدث", "تصرخ", "تهرب", "تترك", "تفكر", "تستسلم", "تيأس", "تغضب", "تخبر", "تخرج", "تدخل", "تقترب",
    "تبتعد", "تتأخر", "تتدخل", "تتصرف", "تفتح", "تغلق", "تلعب", "تضحك", "تحزن", "تتوقف", "تجرؤ", "تنزل",
    "تصعد", "تركض", "تعبث", "تثق", "تسمح", "تحكم", "تنتظر", "تقاطع", "تحرّك", "تسرق", "تشرب", "تقلقي",
)
PROHIBIT_IRREGULAR = {"تخافي": "تخف", "تقولي": "تقل", "تكوني": "تكن", "تلومي": "تلم", "تموتي": "تمت",
                      "تنامي": "تنم", "تعودي": "تعد", "تقومي": "تقم", "تبيعي": "تبع"}
SUFFIXES = ("", "ني", "ه", "ها", "هم", "هن", "نا")
# Commands that are other common words too («عد» to count, «جدي» my grandfather, «دوري» my
# turn): left alone when they stand bare; with an object ending («قوليها») they are safe.
_AMBIGUOUS = {"عد", "قل", "جد", "مت", "در", "مل", "طر", "كن", "دع", "ثق", "خف", "سر", "بع", "عش", "صم",
              "زر", "ذق", "شاهد", "تحدث", "تبرع", "حدد"}  # a witness; "it happens"; a donation

# You (a woman) in the present tense, for the verbs games use most: تذهبين → تذهب.
PRESENT_FEM = {
    "تفعلين": "تفعل", "تذهبين": "تذهب", "تريدين": "تريد", "تعرفين": "تعرف", "تقولين": "تقول",
    "تحتاجين": "تحتاج", "تستطيعين": "تستطيع", "تنتظرين": "تنتظر", "تفكرين": "تفكر", "تمزحين": "تمزح",
    "تكذبين": "تكذب", "تحاولين": "تحاول", "تبحثين": "تبحث", "تتحدثين": "تتحدث", "تتكلمين": "تتكلم",
    "تبقين": "تبقى", "تنسين": "تنسى", "ترين": "ترى", "تأتين": "تأتي", "تبدين": "تبدو", "تظنين": "تظن",
    "تحبين": "تحب", "تشعرين": "تشعر", "تفهمين": "تفهم", "تسمعين": "تسمع", "تعملين": "تعمل",
    "تندمين": "تندم", "تخافين": "تخاف", "تثقين": "تثق", "تنامين": "تنام", "تعودين": "تعود",
}

_LOOSE = str.maketrans({"أ": "ا", "إ": "ا", "ّ": None})  # the model often leaves these out


def _feminine(masc: str) -> str:
    for fem, m in IRREGULAR.items():
        if m == masc:
            return fem
    return masc + "ي"


def _build() -> tuple[dict[str, str], dict[str, str]]:
    to_masc: dict[str, str] = {}
    to_fem: dict[str, str] = {}
    bases = {masc: _feminine(masc) for masc in MASC}
    for fem, masc in IRREGULAR.items():
        bases.setdefault(masc, fem)
    for masc, fem in bases.items():
        for suf in SUFFIXES:
            if not suf and masc in _AMBIGUOUS:
                continue
            for f_key in (fem + suf, (fem + suf).translate(_LOOSE)):
                to_masc.setdefault(f_key, masc + suf)
            for m_key in (masc + suf, (masc + suf).translate(_LOOSE)):
                to_fem.setdefault(m_key, fem + suf)
    return to_masc, to_fem


TO_MASC, TO_FEM = _build()


def _build_prohibit() -> tuple[dict[str, str], dict[str, str]]:
    bases = {m: m + "ي" for m in PROHIBIT if not m.endswith("ي")}
    bases.update({m: f for f, m in PROHIBIT_IRREGULAR.items()})
    to_masc: dict[str, str] = {}
    for m, f in bases.items():
        for suf in SUFFIXES:  # «لا تتركيني» / «لا تتركني»
            to_masc[f + suf] = m + suf
    return to_masc, {m: f for f, m in to_masc.items()}


PROHIBIT_MASC, PROHIBIT_FEM = _build_prohibit()
_NOT = {"لا", "ولا", "فلا"}

_AR = "ء-ٍّ"  # letters, tanween and shadda: a word
_HARAKAT = re.compile("[َُِْٰ]")  # short vowels: the subtitles drop them anyway
_TOKEN = re.compile(rf"[{_AR}]+|[^{_AR}]+")
_STOP = re.compile(r"[.!؟?،,:؛«\"]\s*$")
# Words after which a command can stand, as at the start of a sentence: «ثم اذهبي».
LEADS = {"ثم", "الآن", "فقط", "هيا", "رجاء", "رجاءً", "أرجوك", "حسناً", "حسنا", "إذن", "بسرعة", "أولاً", "أولا",
         "والآن", "فوراً", "فورا"}
# Commands that stand bare only in these company: «قل لي» is "tell me", «عد إلى» is "go back to".
CONTEXT = (
    ("قل", "قولي", re.compile(r"^\s*(?:لي|له|لها|لهم|لنا|الحقيقة|شيئاً|شيئا|ذلك|هذا|ما)(?![ء-ي])")),
    ("عد", "عودي", re.compile(r"^\s*(?:إلى|الى|هنا|للمخيم|للبيت|للمنزل|أدراجك|حالاً|حالا|فوراً|فورا)(?![ء-ي])")),
    ("كن", "كوني", re.compile(r"^\s*(?:حذر|حذرة|حذراً|حذرا|هادئ|هادئة|هادئاً|هادئا|مستعد|مستعدة|مستعداً|مستعدا)(?![ء-ي])")),
)


def _look(table: dict[str, str], tok: str) -> str | None:
    """A command in the table, also when the model wrote its first alef with a hamza below
    («إدفعي»): a command never starts with «إ», while «أ» can be "I" («أذهب», I go)."""
    return table.get(tok) or (table.get("ا" + tok[1:]) if tok[:1] == "إ" else None)


def _swap(text: str, table: dict[str, str], ctx: dict[str, tuple[str, re.Pattern]],
          prohibit: dict[str, str] | None = None) -> str:
    tokens = _TOKEN.findall(text)
    out: list[str] = []
    at_cmd = True  # the start of the line is where a command stands
    after_not = False
    for i, tok in enumerate(tokens):
        if not ("ء" <= tok[0] <= "ي"):
            out.append(tok)
            if _STOP.search(tok):
                at_cmd = True
            elif tok.strip():
                at_cmd = False
            continue
        new = None
        if after_not and prohibit:
            new = prohibit.get(tok)
            if new:
                out.append(new)
                at_cmd, after_not = False, False
                continue
        joined = tok[0] in "وف" and len(tok) > 3 and _look(table, tok[1:])
        if at_cmd:
            new = _look(table, tok) or (tok[0] + joined if joined else None)
            if new is None and tok in ctx:
                after = "".join(tokens[i + 1:i + 3])
                other, rx = ctx[tok]
                if rx.search(after):
                    new = other
        elif joined:  # «و/ف» joined to a command continues a list of commands: «ابقي هنا وراقبي»
            new = tok[0] + joined
        out.append(new or tok)
        at_cmd = tok in LEADS
        after_not = tok in _NOT
    return "".join(out)


_CTX_FEM = {m: (f, rx) for m, f, rx in CONTEXT}
_CTX_MASC = {f: (m, rx) for m, f, rx in CONTEXT}
_PRESENT = re.compile(rf"(?<![{_AR}])(" + "|".join(sorted(PRESENT_FEM, key=len, reverse=True)) + rf")(?![{_AR}])")


# Commands that are commands wherever they stand, even when the model drops the comma before
# them («لا تقلق بشأني اعتني بنفسك»).
ANYWHERE = {"اعتني بنفسك": "اعتن بنفسك", "اهتمي بنفسك": "اهتم بنفسك", "انتبهي لنفسك": "انتبه لنفسك",
            "حافظي على نفسك": "حافظ على نفسك"}


def masculinize(arabic: str) -> str:
    """Commands and "you" verbs said to a woman, turned to a man (or to nobody in particular)."""
    if "ي" not in arabic:
        return arabic
    for wrong, right in SPELLING.items():
        if wrong in arabic:
            arabic = arabic.replace(wrong, right)
    for fem, masc in ANYWHERE.items():
        if fem in arabic:
            arabic = arabic.replace(fem, masc)
    arabic = _swap(_HARAKAT.sub("", arabic), TO_MASC, _CTX_MASC, PROHIBIT_MASC)
    return _PRESENT.sub(lambda m: PRESENT_FEM[m.group(1)], arabic) if "ين" in arabic else arabic


def feminize(arabic: str) -> str:
    """Commands said to a man, turned to a woman (when a woman is the one spoken to)."""
    arabic = _swap(_HARAKAT.sub("", arabic), TO_FEM, _CTX_FEM, PROHIBIT_FEM)
    for wrong, right in SPELLING.items():
        if wrong in arabic:
            arabic = arabic.replace(wrong, right)
    for fem, masc in ANYWHERE.items():
        if masc in arabic and fem not in arabic:
            arabic = arabic.replace(masc, fem)
    return arabic
