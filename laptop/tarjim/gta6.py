"""Grand Theft Auto VI only: its screen words, its slang and its mission lines.

Everything here is used only when the game is GTA VI (profile id "gta6", or a title that
names GTA VI); no other game sees any of it. It was written from the first evening the user
played (2026-11-19): the session log showed mission lines written as verbal nouns («القيادة
إلى متجر الخمور»), "Chase Arnold" read as a name («تشيس أرنولد»), street slang taken word
for word («سأمسك بك على الوجه»), menu and phone words read as sentences, and the radio's
song titles translated («الجندي الحديدي البكر»).

Order for one line (CachedTranslator.translate):
  1. OCR       reading slips of the game's font ("l'm", "hel'll", "TUN OFF")
  2. KEEP      lines that stay English: radio stations, songs, artists (nothing is drawn)
  3. UI        exact screen words: menus, phone apps, prompts, notices
  4. LINES     whole-line patterns: mission objectives and short calls, Arabic written out
  5. REWRITES  slang into plain English before the engine reads the line
  6. AR_FIXES  Arabic the engine still gets wrong

The phone app reads the same tables from assets/words/gta6.json, which
launcher/build_packs.py writes from this file: change them here only. Patterns use only what
Python and Java both read the same way (no named groups, fixed-width look-behind).
Never put a whole line copied from the game in here: patterns and general idioms only.
"""

from __future__ import annotations

import json
import re

GAME_ID = "gta6"
VERSION = 1  # part of the cache key of GTA VI lines: raise it when these tables change

_TITLES = re.compile(r"grand theft auto\s*(?:vi|6)\b|\bgta\s*(?:vi|6)\b", re.IGNORECASE)


def is_gta6(profile: str, title: str = "") -> bool:
    return profile == GAME_ID or bool(_TITLES.search(title or ""))


# -- where the game puts its text (fractions of the picture, measured on its first evening) ----
# Subtitles and mission lines: centred at the bottom, about 32-68% of the width. The prompts
# beside a person (TALK, TAUNT) are stacked at the bottom right from 83%; the pause menu's
# button bar starts at 76%. The pause menu and its lists are on the left. Phone messages come
# on a white card at the bottom right. Notices ("Map updated") are at the top right.
SUBTITLE_REGION = {"left": 0.16, "top": 0.72, "right": 0.78, "bottom": 0.985}
# Where screen text never looks (the subtitles' own lines): narrower than where subtitles are
# looked for, so the button bar at the bottom right (from 74%) stays whole.
SUBTITLE_KEEP_OUT = {"left": 0.20, "top": 0.78, "right": 0.74, "bottom": 0.985}
# The middle holds prompts that float on a thing ("KNOCK", "BAG") and the equipment view's
# tabs ("WEAPONS", "ITEMS"); the scene is busiest there, so only known screen words are drawn.
# (name, x0, y0, x1, y1, align, cards, dark, items, known_only)
ZONES: tuple[tuple, ...] = (
    # The mission's to-do list and longer lines on the left run to about 45% of the width.
    ("left", 0.0, 0.17, 0.45, 0.95, "left", False, True, True, False),
    ("right", 0.60, 0.035, 1.0, 0.72, "right", False, False, True, False),
    ("prompts", 0.745, 0.72, 1.0, 0.995, "right", False, False, True, False),
    ("phone", 0.68, 0.03, 1.0, 0.995, "right", True, False, False, False),
    ("middle", 0.45, 0.10, 0.60, 0.72, "center", False, False, True, True),
    # the radio wheel's labels (VEHICLE, RADIO, ON DEMAND) sit right-aligned beside its slider
    ("top", 0.0, 0.0, 0.60, 0.17, "right", False, False, True, True),
)


# -- 1. reading slips ----------------------------------------------------------------------
# The game's subtitle font has a capital I that OCR reads as a small l.
OCR: tuple[tuple[str, str], ...] = (
    (r"^l (?=[a-z])", "I "),
    (r"(?<![A-Za-z])l'(m|ll|d|ve)\b", r"I'\1"),
    (r"(?<![A-Za-z])[Il]l'll\b", "I'll"),
    (r"\bhel'll\b", "he'll"),
    (r"\bshel'll\b", "she'll"),
    (r"\bwel'll\b", "we'll"),
    (r"\b(?:TUN|TURN|TUM) (?:OFF|OFf|Off|Of|OF)\b", "TURN OFF"),
    (r"\bMapupdated\b", "Map updated"),
    # stutters: "Ma- Maroon Key", "the- the big one"
    (r"(?i)\b([a-z]{1,3})[-–—]\s+(?=\1)", ""),
)

# -- 2. lines left in English ---------------------------------------------------------------
# The radio wheel: station names, song titles and artists are names, not sentences.
KEEP: tuple[str, ...] = (
    r"^[^a-z]*\b(?:FM|RADIO)\b[^a-z]*$",
    r"\bFT\.\s",
    r"^(?:THE CHAMBER|HONEY FM|FLASH FM|V-ROCK|VICE CITY FM|WORLDWIDE FM|AFROBANK FM|KALEIDOSCOPE FM|"
    r"STOCKYARD FM|GLORIANA BLUES|BACK COUNTRY RADIO|CIRCOLOCO)",
    r"^\$?[\d,.]+$",
    r"^[A-Z][A-Z'. ]*'\d\d\b",  # a car's name with its model year ("JASON'S '70 ...")
)

# -- 3. screen words --------------------------------------------------------------------------
# Matched on the whole item: small letters, single spaces, no end punctuation, no button letter.
UI: dict[str, str] = {
    # pause menu
    "map": "الخريطة", "game": "اللعبة", "store": "المتجر", "help": "المساعدة",
    "photo studio": "استوديو الصور", "settings": "الإعدادات", "online": "أونلاين",
    "brief": "الملخص", "stats": "الإحصاءات", "gallery": "المعرض", "story": "القصة",
    "resume": "متابعة", "quit": "خروج", "quit game": "الخروج من اللعبة", "load game": "تحميل اللعبة",
    "save game": "حفظ اللعبة", "new game": "لعبة جديدة", "replay mission": "إعادة المهمة",
    "skip": "تخطٍّ", "skip mission": "تخطي المهمة", "retry": "إعادة المحاولة", "restart": "إعادة البدء",
    # button prompts
    "select": "اختيار", "back": "رجوع", "exit": "خروج", "close": "إغلاق", "confirm": "تأكيد",
    "cancel": "إلغاء", "accept": "قبول", "decline": "رفض", "continue": "متابعة", "scroll": "تمرير",
    "zoom": "تكبير", "zoom in": "تكبير", "zoom out": "تصغير", "move": "تحريك", "rotate": "تدوير",
    "remove destination": "حذف الوجهة", "set destination": "تحديد الوجهة", "place waypoint": "وضع علامة",
    "remove waypoint": "حذف العلامة", "legend": "دليل الرموز", "filter": "فلتر", "filters": "الفلاتر",
    "options": "خيارات", "tab": "تبويب", "view": "عرض", "view comments": "عرض التعليقات",
    "comments": "التعليقات", "like": "إعجاب", "share": "مشاركة", "post": "نشر", "reply": "رد",
    "send": "إرسال", "call": "اتصال", "hang up": "إنهاء المكالمة", "answer": "رد", "ignore": "تجاهل",
    "open": "فتح", "show text": "إظهار النص", "hide text": "إخفاء النص", "flip": "قلب",
    "selfie": "سيلفي", "take photo": "التقاط صورة", "camera": "الكاميرا", "change": "تغيير",
    "turn off": "إيقاف", "turn on": "تشغيل", "next": "التالي", "previous": "السابق", "page": "صفحة",
    "hold": "اضغط مطولاً", "buy": "شراء", "purchase": "شراء", "sell": "بيع", "try on": "تجربة",
    "equip": "ارتداء", "remove": "إزالة", "change outfit": "تغيير الملابس", "browse": "تصفح",
    "restore all": "استعادة الكل", "restore default": "استعادة الافتراضي",
    "restore defaults": "استعادة الافتراضي",
    # interaction prompts beside a person or a thing (some float on the thing itself)
    "talk": "تحدّث", "taunt": "استفزاز", "question": "اسأل", "greet": "تحية", "insult": "إهانة",
    "enter": "دخول", "leave": "مغادرة", "sit": "اجلس", "pick up": "التقاط", "search": "تفتيش",
    "steal": "سرقة", "rob": "سرقة", "hold up": "تهديد", "pay": "دفع", "tip": "بقشيش",
    "knock": "اطرق", "bag": "حقيبة", "scold": "وبّخ", "pet": "داعب", "study": "تفحّص", "feed": "أطعم",
    "play": "العب", "walk": "تمشَّ", "inspect": "افحص", "examine": "افحص", "use": "استخدم",
    "loot": "خذ الغنيمة", "lockpick": "افتح القفل", "lock pick": "افتح القفل", "pick lock": "افتح القفل",
    "open door": "افتح الباب", "close door": "أغلق الباب", "get in": "اركب", "get out": "انزل",
    "enter vehicle": "اركب المركبة", "exit vehicle": "انزل من المركبة", "hijack": "استولِ على المركبة",
    "drive": "قيادة", "sleep": "نوم", "shower": "استحمام", "eat": "كُل", "drink": "اشرب",
    "smoke": "دخّن", "dance": "ارقص", "hug": "عانق", "kiss": "قبّل", "flirt": "غازل", "apologize": "اعتذر",
    "threaten": "هدّد", "calm down": "اهدأ", "surrender": "استسلم", "hands up": "ارفع يديك",
    "interact": "تفاعل", "help up": "ساعده على النهوض", "revive": "أنعش", "give": "أعطِ", "take": "خذ",
    "put on": "ارتداء", "take off": "خلع", "wear style": "طريقة الارتداء", "remove all": "إزالة الكل",
    "put back": "أعِده", "put away": "أبعِده", "read": "اقرأ", "turn page": "اقلب الصفحة", "close up": "تقريب",
    # the map
    "recenter": "توسيط", "re-center": "توسيط", "add marker": "إضافة علامة", "remove marker": "إزالة العلامة",
    "markers": "العلامات", "2d view": "عرض ثنائي الأبعاد", "3d view": "عرض ثلاثي الأبعاد", "close menu": "إغلاق القائمة",
    "adjust": "ضبط", "unknown": "غير معروف", "waypoint": "علامة الطريق", "fast travel": "انتقال سريع",
    # the mission menu and the story
    "retry checkpoint": "أعد المحاولة من نقطة الحفظ", "restart mission": "إعادة بدء المهمة",
    "quit mission": "إنهاء المهمة", "replay": "إعادة اللعب", "chapter": "الفصل", "optional": "اختياري",
    "jason only": "جيسون فقط", "lucia only": "لوسيا فقط",
    # skills and loadout
    "skills": "المهارات", "perks": "الميزات", "loadout": "العتاد", "xp from kills": "نقاط خبرة من القتل",
    "leg day": "يوم تمارين الساقين", "wild card": "الورقة الرابحة", "built different": "صُنع مختلفاً",
    "automatic shotgun": "بندقية خرطوش آلية", "auto shotgun": "بندقية خرطوش آلية",
    "health regeneration": "استعادة الصحة", "maximum health": "الصحة القصوى", "maximum stamina": "التحمل الأقصى",
    "movement speed": "سرعة الحركة", "weapon damage": "ضرر السلاح", "critical damage": "الضرر الحرج",
    "survival": "البقاء", "mobility": "التنقل", "combat": "القتال", "economy": "الاقتصاد",
    # shops and things to use
    "stylist": "مصفف الشعر", "barber": "الحلاق", "hairstyle": "تسريحة الشعر", "facial hair": "شعر الوجه",
    "facial hair color": "لون شعر الوجه", "staff member": "الموظف", "put down": "ضعه", "give beer": "أعطِ البيرة",
    "coffee table": "طاولة القهوة", "let's move": "لنتحرك", "it's fine": "لا بأس", "flowers": "الزهور",
    "saved outfits": "الأطقم المحفوظة", "workout wear": "ملابس رياضية", "not wearing": "غير مرتدى",
    "not applied": "غير مطبّق", "applied": "مطبّق", "wear": "ارتداء", "add to trunk": "أضف إلى صندوق السيارة",
    "trunk": "صندوق السيارة", "hairstyles": "تسريحات الشعر",
    # dialogue choices offered beside a person
    "what": "ماذا", "what now?": "ماذا الآن؟", "what now": "ماذا الآن", "hey": "مرحباً", "sure": "بالتأكيد",
    "maybe later": "ربما لاحقاً", "later": "لاحقاً", "yes": "نعم", "no": "لا", "okay": "حسناً", "ok": "حسناً",
    "thanks": "شكراً", "thank you": "شكراً لك", "sorry": "آسف", "never mind": "لا يهم", "why": "لماذا",
    "how much": "بكم", "get it yourself?": "أحضره بنفسك؟", "get it yourself": "أحضره بنفسك",
    "agree": "موافقة", "refuse": "رفض", "ask": "اسأل", "compliment": "مجاملة", "joke": "مزحة",
    "view livestream": "مشاهدة البث المباشر", "livestream": "البث المباشر", "live": "مباشر",
    "skip cutscene": "تخطي المشهد", "hold to skip": "اضغط مطولاً للتخطي",
    # radio and car
    "vehicle": "المركبة", "radio": "الراديو", "on demand": "حسب الطلب", "access": "الوصول",
    "registered": "مسجّلة", "unregistered": "غير مسجّلة", "stolen": "مسروقة",
    # notices
    "map updated": "تم تحديث الخريطة", "new message": "رسالة جديدة", "new messages": "رسائل جديدة",
    "new contact": "جهة اتصال جديدة", "mission passed": "نجحت المهمة", "mission failed": "فشلت المهمة",
    "wasted": "مُتّ", "busted": "قُبض عليك", "saving": "جارٍ الحفظ", "autosaving": "حفظ تلقائي",
    # the phone and its apps
    "phone": "الهاتف", "messages": "الرسائل", "message": "رسالة", "contacts": "جهات الاتصال",
    "contact": "جهة اتصال", "calls": "المكالمات", "recent": "الأخيرة", "favorites": "المفضلة",
    "photos": "الصور", "email": "البريد", "browser": "المتصفح", "internet": "الإنترنت",
    "music": "الموسيقى", "calendar": "التقويم", "notes": "الملاحظات", "jobs": "الأعمال",
    "reminders": "التذكيرات", "reminder": "تذكير", "notifications": "الإشعارات",
    "notification": "إشعار", "health": "الصحة", "fitness": "اللياقة",
    "body & nutrition": "الجسم والتغذية", "body and nutrition": "الجسم والتغذية",
    "nutrition": "التغذية", "workout": "التمرين", "cardio workout": "تمرين الكارديو",
    "strength workout": "تمرين القوة", "cardio": "كارديو", "strength": "القوة", "stamina": "التحمل",
    "level": "المستوى", "goal": "الهدف", "goals": "الأهداف", "progress": "التقدم",
    "social": "التواصل", "profile": "الملف الشخصي", "followers": "المتابعون",
    "following": "المتابَعون", "trending": "الرائج", "wallet": "المحفظة", "bank": "البنك",
    "balance": "الرصيد", "cash": "نقداً", "money": "المال", "unread": "غير مقروءة",
    "today": "اليوم", "yesterday": "أمس", "now": "الآن",
    # wardrobe and shops
    "wardrobe": "خزانة الملابس", "outfits": "الأطقم", "outfit": "طقم", "tops": "القطع العلوية",
    "bottoms": "القطع السفلية", "footwear": "الأحذية", "shoes": "الأحذية", "accessories": "الإكسسوارات",
    "hats": "القبعات", "glasses": "النظارات", "jackets": "الجاكيتات", "shirts": "القمصان",
    "pants": "البناطيل", "shorts": "الشورتات", "jewelry": "المجوهرات", "watches": "الساعات",
    "bags": "الحقائب", "masks": "الأقنعة", "hair": "الشعر", "tattoos": "الوشوم",
    "protein shake": "مخفوق بروتين", "water": "ماء", "beer": "بيرة", "soda": "مشروب غازي",
    "food": "طعام", "drinks": "مشروبات", "snacks": "وجبات خفيفة", "weapons": "الأسلحة",
    "ammo": "الذخيرة", "armor": "الدرع", "health kit": "حقيبة إسعاف",
    # the equipment view and inventory
    "items": "الأغراض", "item": "غرض", "inventory": "المخزون", "equipment": "العدّة",
    "face wrap": "لثام", "gloves": "القفازات", "backpack": "حقيبة الظهر", "melee": "القتال القريب",
    "pistols": "المسدسات", "rifles": "البنادق", "shotguns": "بنادق الصيد", "throwables": "المقذوفات",
    "unequip": "نزع", "equipped": "مُستخدَم", "owned": "مملوك", "locked": "مقفل", "new": "جديد",
    # the phone's apps (press reports; Rockstar has not listed them all)
    "snapmatic": "سناب ماتيك", "waink": "وينك", "rydeme": "رايد مي", "ryde me": "رايد مي",
    "buckme": "باك مي", "scooter bros": "سكوتر بروز", "camera roll": "ألبوم الكاميرا",
    "map app": "تطبيق الخريطة", "texts": "الرسائل", "inbox": "البريد الوارد", "chats": "المحادثات",
    "voicemail": "البريد الصوتي", "missed call": "مكالمة فائتة", "missed calls": "مكالمات فائتة",
    "calling": "جارٍ الاتصال", "incoming call": "مكالمة واردة", "typing": "يكتب",
    # objectives and mission states
    "objective": "الهدف", "objectives": "الأهداف", "recent dialogue": "الحوار الأخير",
    "mission objectives": "أهداف المهمة", "new objective": "هدف جديد", "checkpoint": "نقطة حفظ",
    "help text": "نصوص المساعدة", "tips": "نصائح",
    # settings
    "display": "العرض", "graphics": "الرسوميات", "audio": "الصوت", "controls": "التحكم",
    "controller": "يد التحكم", "camera settings": "إعدادات الكاميرا", "accessibility": "إمكانية الوصول",
    "subtitles": "الترجمة النصية", "language": "اللغة", "brightness": "السطوع", "contrast": "التباين",
    "hdr": "HDR", "blur strength": "شدة التمويه", "motion blur": "تمويه الحركة",
    "gore intensity": "شدة مشاهد الدم", "mission only": "في المهمات فقط", "always": "دائماً",
    "never": "أبداً", "on": "تشغيل", "off": "إيقاف", "low": "منخفض", "medium": "متوسط", "high": "مرتفع",
    "default": "افتراضي", "volume": "مستوى الصوت", "music volume": "صوت الموسيقى",
    "dialogue volume": "صوت الحوار", "radio volume": "صوت الراديو", "vibration": "الاهتزاز",
    "invert look": "عكس اتجاه النظر", "sensitivity": "الحساسية", "aim assist": "مساعدة التصويب",
    "hud": "واجهة اللعب", "minimap": "الخريطة المصغّرة", "text size": "حجم النص",
    "subtitle size": "حجم الترجمة", "subtitle background": "خلفية الترجمة",
    "this is a subtitle.": "هذا نص ترجمة.", "this is a subtitle": "هذا نص ترجمة",
    "flash reduction": "تقليل الوميض", "brightness reduction": "تقليل السطوع",
}

_O = r"([^,.!?;:\"]+?)"  # one object of a mission line: no comma, no sentence mark

# -- 4. whole lines -------------------------------------------------------------------------
# A pattern over the whole line (after reading slips are fixed). {1}, {2} are the groups,
# translated on their own (names come from the game's list); {=1} copies a group as it is. Mission objectives have no full
# stop; a line that ends in "!" or "?" is speech and is left to the engine.
LINES: tuple[tuple[str, str], ...] = (
    # mission objectives (the to-do list on the left writes them in Title Case: "Pick Up Groceries")
    (r"(?i)^Buy (\w+) an? " + _O + r"$", "اشترِ {2} ل{1}"),
    (r"(?i)^Pick up " + _O + r"$", "اجلب {1}"),
    (r"(?i)^Drop off " + _O + r"$", "أوصل {1}"),
    (r"(?i)^Get (?!in\b|into\b|out\b|to\b|back\b|away\b|rid\b|ready\b|down\b|up\b)" + _O + r"$", "أحضر {1}"),
    (r"(?i)^Retry (?:from )?(?:the )?checkpoint$", "أعد المحاولة من نقطة الحفظ"),
    (r"^(?:Drive|Head|Go|Get|Travel|Ride|Make your way|Take the car|Run) (?:back )?to " + _O + r"$", "توجّه إلى {1}"),
    (r"^Return to " + _O + r"$", "عُد إلى {1}"),
    (r"^Find " + _O + r"$", "ابحث عن {1}"),
    (r"^Search (?:for )?" + _O + r"$", "ابحث عن {1}"),
    (r"^Chase " + _O + r"$", "طارد {1}"),
    (r"^Follow " + _O + r"$", "اتبع {1}"),
    (r"^Catch up (?:to|with) " + _O + r"$", "الحق {1}"),
    (r"^Get in(?:to)? " + _O + r"$", "اركب {1}"),
    (r"^Get out of " + _O + r"$", "انزل من {1}"),
    (r"^Choose what to do with " + _O + r"$", "قرّر مصير {1}"),
    (r"^Decide (?:what to do with|the fate of) " + _O + r"$", "قرّر مصير {1}"),
    (r"^(?:Lose|Evade|Escape) the (?:cops|police|law)$", "اهرب من الشرطة"),
    (r"^(?:Lose|Evade|Escape) " + _O + r"$", "اهرب من {1}"),
    (r"^Kill " + _O + r"$", "اقتل {1}"),
    (r"^Take out " + _O + r"$", "اقضِ على {1}"),
    (r"^Meet " + _O + r"$", "قابل {1}"),
    (r"^(?:Talk|Speak) to " + _O + r"$", "تحدّث مع {1}"),
    (r"^Call " + _O + r"$", "اتصل ب{1}"),
    (r"^Text " + _O + r"$", "راسل {1}"),
    (r"^Wait for " + _O + r"$", "انتظر {1}"),
    (r"^Take " + _O + r" to " + _O + r"$", "خذ {1} إلى {2}"),
    (r"^Bring " + _O + r" to " + _O + r"$", "أحضر {1} إلى {2}"),
    (r"^Deliver " + _O + r" to " + _O + r"$", "سلّم {1} إلى {2}"),
    (r"^Enter " + _O + r"$", "ادخل {1}"),
    (r"^Leave " + _O + r"$", "غادر {1}"),
    (r"^Park " + _O + r"$", "اركن {1}"),
    (r"^Cross " + _O + r"$", "اعبر {1}"),
    (r"^Stay (?:close to|near|with) " + _O + r"$", "ابق قريباً من {1}"),
    (r"^Protect " + _O + r"$", "احمِ {1}"),
    (r"^Steal " + _O + r"$", "اسرق {1}"),
    (r"^Rob " + _O + r"$", "اسرق {1}"),
    (r"^Buy " + _O + r"$", "اشترِ {1}"),
    (r"^Collect " + _O + r"$", "اجمع {1}"),
    (r"^Destroy " + _O + r"$", "دمّر {1}"),
    (r"^Hide " + _O + r"$", "أخفِ {1}"),
    (r"^Finish " + _O + r"$", "أنهِ {1}"),
    (r"^Complete " + _O + r"$", "أكمل {1}"),
    (r"^Answer the phone$", "ردّ على الهاتف"),
    (r"^Answer " + _O + r"$", "ردّ على {1}"),
    # short calls the engine takes word for word
    (r"^Classic ([A-Z][\w'\-]+)[.!]?$", "هذا {1} كعادته."),
    (r"^Smart ?ass[.!]?$", "يا لك من متذاكٍ."),
    (r"^Wise ?guy[.!]?$", "يا لك من متذاكٍ."),
    (r"^Get fucked[.!]?$", "اذهب إلى الجحيم."),
    (r"^Do what now\?$", "ماذا تقصد؟"),
    (r"^(?:Ah|Oh|Ha),? there he is([.!]?)$", "ها هو ذا{=1}"),
    (r"^(?:Ah|Oh|Ha),? there she is([.!]?)$", "ها هي ذي{=1}"),
    (r"^(?:Oh|Ah|Aw),? shit([.!]*)$", "تباً{=1}"),
    (r"^Shit([.!]*)$", "تباً{=1}"),
    (r"^Holy shit([.!]*)$", "يا إلهي{=1}"),
    (r"^Make amends([.!]?)$", "أصلح الأمور{=1}"),
    (r"^Sure did([.!]?)$", "بالتأكيد{=1}"),
    (r"^(?:So, )?what's it (?:gonna|going to) be\?$", "إذاً، ما قرارك؟"),
    (r"^C'mon([.!]*)$", "هيا{=1}"),
    (r"^Come on([.!]*)$", "هيا{=1}"),
    (r"^So([.…]+)$", "إذاً{=1}"),
    (r"^Hey([.!]?)$", "مهلاً{=1}"),
    (r"^(?:Oh, )?man([.!]*)$", "يا رجل{=1}"),
)

# -- 5. slang into plain English ------------------------------------------------------------
REWRITES: tuple[tuple[str, str], ...] = (
    (r"(?i)\bcatch you on the flip(?: ?side)?\b", "see you later"),
    (r"(?i)\bcatch you later\b", "see you later"),
    (r"(?i)\b(he|she)(?:'s| has) got another (?:thing|think) coming\b", r"\1 is very wrong"),
    (r"(?i)\b(they|you)(?:'ve| have) got another (?:thing|think) coming\b", r"\1 are very wrong"),
    (r"(?i)\bthe error of (his|her|their|your|my) ways\b", r"\1 mistake"),
    (r"(?i)\bpull(?:s)? the plug on (me|us|him|her|them|you)\b", r"abandon \1"),
    (r"(?i)\bpulled the plug on (me|us|him|her|them|you)\b", r"abandoned \1"),
    (r"(?i)\bpull up (?:in )?(?:out )?(?:in )?front of\b", "stop in front of"),
    (r"(?i)\bpull up (?:at|by|outside)\b", "stop at"),
    (r"(?i)\bwhy (?:did )?(this|that) (guy|girl|dude|man) ghost (you|me|him|her)\b", r"why did \1 \2 disappear on \3"),
    (r"(?i)\bghost(?:ing)? (me|you|him|her|us|them)\b", r"disappearing on \1"),
    (r"(?i)\bghosted (me|you|him|her|us|them)\b", r"disappeared on \1"),
    (r"(?i)\b(?:still )?got ghosted(?: though)?\b", "he still ignored you"),
    (r"(?i)\bhook(?:ing)? up with\b", "dating"),
    (r"(?i)\bpoof\b", "suddenly"),
    (r"(?i)\baerostat thing\b", "radar balloon"),
    (r"(?i)\baerostat\b", "radar balloon"),
    (r"(?i)\b(a|the|that|this|some) chick\b", r"\1 girl"),
    (r"(?i)\bchicks\b", "girls"),
    (r"(?i)\byou see right there\?", "do you see it over there?"),
    (r"(?i)\bokay(?=[-–—])", "alright"),
    (r"(?i)\bgot (your|a|my|his) (gun|piece|pistol|weapon) on (you|me|him)\b", r"have \1 \2 with \3"),
    (r"(?i)\b(?:one or two|a couple of) guys about (him|her|them)\b", r"one or two men with \1"),
    (r"(?i)\bguys about (him|her|them)\b", r"men with \1"),
    (r"(?i)\bcall (that|this) (asshole|idiot|bastard|prick|guy|dude)\b", r"phone \1 \2"),
    (r"(?i)\bcabin boys\b", "little helpers"),
    (r"(?i)\bthe (?:fuckin'? |fucking )?nerve or the balls\b", "the courage"),
    (r"(?i)\bwork (?:something|it|this|things) out like men\b", "reach an agreement like men"),
    (r"(?i)\bwork (?:something|it|this|things) out\b", "reach an agreement"),
    (r"(?i)\bmove (?:a |an |even an? )?(?:fuckin'? |fucking )?eight-?ball\b", "sell even a small amount of drugs"),
    (r"(?i)\bget your foot on the gas\b", "press the gas pedal"),
    (r"(?i)\bput your foot down\b", "press the gas pedal"),
    (r"(?i)\b(he|she|they) cut (left|right)\b", r"\1 turned \2"),
    (r"(?i)\bstay on (his|her|their) (?:ass|tail)\b", r"stay right behind \1"),
    (r"(?i)^stay on (him|her|them)\b", r"stay behind \1"),
    (r"(?i)(?<=[.!?] )stay on (him|her|them)\b", r"stay behind \1"),
    (r"(?i)\byou guys holding on\?", "are you guys okay back there?"),
    (r"(?i)\bdoesn't connect\b", "is cut off"),
    (r"(?i)\b(?:the |a )?bullet'?s? (?:right )?here with your name on it\b", "I have a bullet right here just for you"),
    (r"(?i)\bwith your name on it\b", "just for you"),
    (r"(?i)\bmake amends\b", "fix things"),
    (r"(?i)\bblackball(?:ing)? (me|us|him|her|them|you)\b", r"ban \1 from the business"),
    (r"(?i)\bblackballed (me|us|him|her|them|you)\b", r"banned \1 from the business"),
    (r"(?i)\b(?:it'll|it will|that'll|that will) be a cold day in (?:fucking |fuckin' )?hell\b", "that will never happen"),
    (r"(?i)\bleech\b", "parasite"),
    (r"(?i)\bshit stain(?: on a carpet)?\b", "piece of trash"),
    (r"(?i)\bchild lock\b", "child safety lock"),
    (r"(?i)\bget fucked\b", "go to hell"),
    (r"(?i)\b(?:in on|involved in) this shit\b", "involved in this"),
    (r"(?i)\bthis shit\b", "this mess"),
    (r"(?i)\b(?:oh|ah|aw), shit\b", "oh, damn"),
    (r"(?i)^shit\b", "damn"),
    (r"(?i)(?<=[.!?] )shit\b", "damn"),
    (r"(?i)\bholy shit\b", "oh my God"),
    (r"(?i)\byou (?:little |fuckin'? |fucking )?fuck(?=[!.?,]|$)", "you bastard"),
    (r"(?i)\bI'm out(?=[,.!])", "I quit"),
    (r"(?i)\b([A-Z][a-z]+)'s done, we're all done\b", r"\1 is finished, we are all finished"),
    (r"(?i)\byou're done, man, you're over\b", "you're finished, man, it's over for you"),
    (r"(?i)\byou're over(?=[.!])", "it's over for you"),
    (r"(?i)\b([A-Z][\w']+) and I ran together back in the day\b", r"I worked with \1 in the old days"),
    (r"(?i)\bran together back in the day\b", "worked together in the old days"),
    (r"(?i)\bback in the day\b", "in the old days"),
    (r"(?i)\bgot out while the getting was good\b", "quit at the right time"),
    (r"(?i)\bain't that something\b", "isn't that great"),
    (r"(?i)\bI could do with a hand\b", "I need some help"),
    (r"(?i)\bcould do with\b", "could use"),
    (r"(?i)\b(he's|she's|it's|we're|you're) in the clear\b", r"\1 fine"),
    (r"(?i)\bthem was the days\b", "those were good days"),
    (r"(?i)^it would be, if\b", "it would be great, if"),
    (r"(?i)\bwe was\b", "we were"),
    (r"(?i)^you take care of that thing\?", "did you take care of that matter?"),
    (r"(?i)\blovebug\b", "my love"),
    (r"(?i)^thinking we\b", "I think we should"),
    (r"\b([Ss]end|[Ss]ending) (?:the )?([A-Z][\w']+) a message\b", r"\1 a message to the \2"),
    (r"(?i)\bhit (?:em|'em|them) back\b", "attack them"),
    (r"(?i)\bover by the\b", "near the"),
    (r"(?i)\bshow (?:em|'em|them) who's (?:king|boss)\b", "show them who is in charge"),
    (r"(?i)\bgo get (?:em|'em|them)\b", "go after them"),
    (r"(?i)\bwe're all going the same way\b", "we're all going in the same direction"),
    (r"(?i)\bsmart ?ass\b", "know-it-all"),
    (r"(?i)\bturf war\b", "gang war"),
    # clothes (the wardrobe and the shops)
    (r"(?i)\btank tops?\b", "sleeveless shirt"),
    (r"(?i)\btank(?= & | and )", "sleeveless shirt"),
    (r"(?i)\bboard shorts\b", "swim shorts"),
    (r"(?i)\bcutoffs\b", "cut-off shorts"),
    (r"(?i)\bworkwear\b", "work clothes"),
    (r"(?i)\badd to trunk\b", "put in the car trunk"),
    # fitness and fishing (the phone's fitness app, the fishing magazine)
    (r"(?i)\bworkouts\b", "exercises"),
    (r"(?i)\bworkout\b", "exercise"),
    (r"(?i)\b(your|the|a|my|his|her) rod\b", r"\1 fishing rod"),
    (r"(?i)\bbaiting\b", "putting bait on"),
    (r"(?i)\bdon'?t sweat the\b", "do not worry about the"),
    (r"(?i)\btop tips\b", "best tips"),
    (r"(?i)\bfishing hotspots\b", "best fishing spots"),
    (r"(?i)\bhotspots\b", "best spots"),
    (r"(?i)\bfor a decent catch\b", "for a good catch"),
    (r"(?i)\btop spots\b", "best places"),
    (r"(?i)\btop spot\b", "best place"),
    (r"(?i)(?<=\s)em\b(?=[\s.,!?])", "them"),
)

# -- 6. Arabic the engine still gets wrong ----------------------------------------------------
# (English that must be in the line, or "" for any line; wrong Arabic; right Arabic)
AR_FIXES: tuple[tuple[str, str, str], ...] = (
    (r"(?i)\bshit\b", "القرف", "الفوضى"),
    (r"(?i)\bchild safety lock\b", "قفل سلامة الطفل", "قفل أمان الأطفال"),
    (r"(?i)\bradar balloon\b", "تلك المنطاد هي", "ذلك المنطاد هو"),
    (r"(?i)\bI need some help\b", "يمكنني الإستفادة من بعض المساعدة", "أحتاج بعض المساعدة"),
    # a fishing rod is «صنارة», never the other word
    (r"(?i)\brods?\b", "قضيب الصيد الخاص بك", "صنارتك"),
    (r"(?i)\brods?\b", "قضيب الصيد", "صنارة الصيد"),
    (r"(?i)\brods?\b", "قضيبك", "صنارتك"),
    (r"(?i)\brods?\b", "قضيب", "صنارة"),
)


# Arabic patterns: (English that must be in the line, or ""; wrong Arabic as a pattern; right).
# The engine writes «أتريدينه» and «ابقي» to a man; GTA VI talks to Jason far more than to
# Lucia, so they are made masculine unless the line names a woman.
_NOT_TO_A_WOMAN = r"^(?!.*\b(?:Lucia|she|her|girl|lady|ma'am|miss|baby|sweetie|hon|honey|mama|chica|mami)\b)"
_TO_A_MAN = r"(?i)(?:^|,\s*)man\b|\bman,"  # "man" said to someone: «يا رجل», not «رجل،»
AR_PATTERNS: tuple[tuple[str, str, str], ...] = (
    ("", r"لم ([نيتأ])نتهي(?![ء-ي])", r"لم \1نته"),
    ("", r"لم ([نيتأ])نسى(?![ء-ي])", r"لم \1نس"),
    (_TO_A_MAN, r"(?:^|(?<=[،.!؟] ))(?:أوه، )?رجل،", "يا رجل،"),
    (_TO_A_MAN, r"، رجل(?=[.!؟]|$)", " يا رجل"),
    (_NOT_TO_A_WOMAN, r"(?<![ء-ي])ابقي(?![ء-ي])", "ابق"),
    (_NOT_TO_A_WOMAN, r"(?<![ء-ي])(أ|هل )تريدين(ه|ها|هم|ني)?(?![ء-ي])", r"\1تريد\2"),
    (_NOT_TO_A_WOMAN, r"(?<![ء-ي])تمسكين(ها|ه)(?![ء-ي])", r"تمسك\1"),
    (_NOT_TO_A_WOMAN, r"(?<![ء-ي])تتسكعين(?![ء-ي])", "تتسكع"),
    (r"(?i)^cross\b", r"^عبور(?![ء-ي])", "اعبر"),
)


# -- the code --------------------------------------------------------------------------------

_OCR = tuple((re.compile(rx), repl) for rx, repl in OCR)
_KEEP = tuple(re.compile(rx) for rx in KEEP)
_LINES = tuple((re.compile(rx), ar) for rx, ar in LINES)
_REWRITES = tuple((re.compile(rx), repl) for rx, repl in REWRITES)
_AR_FIXES = tuple((re.compile(rx) if rx else None, wrong, right) for rx, wrong, right in AR_FIXES)
_AR_PATTERNS = tuple((re.compile(en) if en else None, re.compile(ar), right) for en, ar, right in AR_PATTERNS)
_BUTTON_TAIL = re.compile(r"(?:\s+(?:[A-Za-z]|[^\w\s]{1,2}|R1|L1|R2|L2|R3|L3))+$")
_END = re.compile(r"[\s.!?:;,…]+$")


def screen_text_on(profile: str, prof: dict) -> bool:
    """Menus, phone and prompts are translated for GTA VI when its profile turns it on (off by
    default until it has been seen to work on the TV)."""
    return is_gta6(profile, str(prof.get("title") or "")) and prof.get("screen_text", False) is True


def subtitle_region(region: dict) -> dict:
    """With screen text on, subtitles are looked for only where the game puts them: the user's
    region cut down to it (a region drawn over the whole screen would take in the menus)."""
    out = {
        "left": max(region["left"], SUBTITLE_REGION["left"]), "top": max(region["top"], SUBTITLE_REGION["top"]),
        "right": min(region["right"], SUBTITLE_REGION["right"]),
        "bottom": min(region["bottom"], SUBTITLE_REGION["bottom"]),
    }
    if out["right"] - out["left"] < 0.1 or out["bottom"] - out["top"] < 0.08:
        return dict(SUBTITLE_REGION)
    return out


def not_speech(text: str) -> bool:
    """A line the subtitles leave alone: capitals only over two words or more (a menu, a button
    bar), or a line that stays English (the radio)."""
    if keep_english(text):
        return True
    words = text.split()
    has_lower = any(c.islower() for c in text)
    return not has_lower and len(words) >= 2 and not text.rstrip().endswith(("!", "?", ".", "..."))


def fix_reading(text: str) -> str:
    for rx, repl in _OCR:
        text = rx.sub(repl, text)
    return text


def keep_english(text: str) -> bool:
    """A line that stays as it is (radio stations, songs): nothing is drawn over it."""
    return any(rx.search(text) for rx in _KEEP)


def ui_key(text: str) -> str:
    """How a screen word is looked up: small letters, one space, no button letter, no end mark."""
    t = re.sub(r"\s+", " ", text).strip()
    t = _BUTTON_TAIL.sub("", t)
    return _END.sub("", t).lower()


def ui_word(text: str) -> str | None:
    """The Arabic of a screen word (menu item, prompt, phone app, notice), or None."""
    t = re.sub(r"\s+", " ", text).strip().lower()
    hit = UI.get(t)
    if hit is None:
        hit = UI.get(ui_key(text))
    return hit


def whole_line(text: str):
    """(Arabic template, groups) for a line one of LINES covers, else None."""
    for rx, ar in _LINES:
        m = rx.match(text)
        if m:
            return ar, list(m.groups())
    return None


def rewrite(english: str) -> str:
    for rx, repl in _REWRITES:
        english = rx.sub(repl, english)
    return english


def fix_arabic(arabic: str, english: str) -> str:
    for rx, wrong, right in _AR_FIXES:
        if wrong in arabic and (rx is None or rx.search(english)):
            arabic = arabic.replace(wrong, right)
    for en_rx, rx, right in _AR_PATTERNS:
        if (en_rx is None or en_rx.search(english)) and rx.search(arabic):
            arabic = rx.sub(right, arabic)
    return arabic


def tables_json() -> str:
    """Everything above as JSON, for the phone app (launcher/build_packs.py writes it)."""
    return json.dumps({
        "game": GAME_ID, "version": VERSION, "ocr": OCR, "keep": KEEP, "ui": UI, "lines": LINES,
        "rewrites": REWRITES, "ar_fixes": AR_FIXES, "ar_patterns": AR_PATTERNS,
    }, ensure_ascii=False, indent=1)
