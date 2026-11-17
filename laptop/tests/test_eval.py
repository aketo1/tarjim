"""Fixed 100-line game-style subtitle evaluation set (orders, threats, jokes, questions,
glossary names, women's names, numbers, slang, idioms, phrasal verbs)."""

import json
import time

import numpy as np
import pytest

from tarjim import paths
from tarjim.translate import Cache, CachedTranslator, OpusTranslator

# 100 original short game-style English subtitle lines (never copied from real games).
# Each entry: (category, english, ideal_arabic, accept_groups, literal_or_broken_substrings)
EVAL_SET: tuple[tuple[str, str, str, tuple[tuple[str, ...], ...], tuple[str, ...]], ...] = (
    # 1. Orders (10)
    ("orders", "Keep your head down and follow me!",
     "أبقِ رأسك منخفضاً واتبعني!",
     (("رأسك", "منخفض"), ("اتبعني", "واتبعني")),
     ("ابقي", "أبقي", "واتبعيني", "اتبعيني")),
    ("orders", "Drop your weapons and step into the light.",
     "ألقوا أسلحتكم وادخلوا إلى الضوء.",
     (("أسلحتكم", "سلاحك"), ("الضوء", "النور")),
     ("قطرة", "أسقطوا أسلحتكم وخطوة")),
    ("orders", "Hold your fire until they cross the river.",
     "أوقفوا إطلاق النار حتى يعبروا النهر.",
     (("النار",), ("يعبروا", "يقطعوا"), ("النهر",)),
     ("امسك نارك", "أمسكوا ناركم")),
    ("orders", "Get behind those rocks before they spot us!",
     "قف خلف تلك الصخور قبل أن يكتشفونا!",
     (("خلف", "وراء"), ("الصخور",), ("يكتشفونا", "يرونا", "يلمحونا", "يكشفونا")),
     ("نقطة لنا", "يبقعونا")),
    ("orders", "Saddle the horses and pack the wagon.",
     "أسرج الخيول وجهّز العربة.",
     (("أسرج", "جهز", "جهّز"), ("الخيول", "الأحصنة"), ("العربة",)),
     ("سرج الخيول وحزم",)),
    ("orders", "Tie him up and throw him in the back.",
     "اربطه وألقِ به في الخلف.",
     (("اربطه", "قيّده", "قيده"), ("الخلف",)),
     ("اربطه لأعلى", "ربطة عنق")),
    ("orders", "Lock the gate and don't let anyone through.",
     "أغلق البوابة ولا تدع أي شخص يمر.",
     (("أغلق", "اقفل"), ("البوابة",), ("يمر", "بالمرور", "يدخل")),
     ("قفل البوابة و", "خلال.")),
    ("orders", "Take the high ground and cover the road.",
     "تحرك إلى الأرض المرتفعة وقم بتغطية الطريق.",
     (("المرتفع", "المرتفعة", "المرتفعات"), ("الطريق",)),
     ("الأرض العالية",)),
    ("orders", "Spread out and search every cabin!",
     "انتشروا وفتشوا كل كوخ!",
     (("انتشروا",), ("فتشوا", "ابحثوا"), ("كوخ",)),
     ("كابينة", "مقصورة")),
    ("orders", "Stay close to the lantern and watch your step.",
     "ابقَ قريباً من الفانوس وانتبه لخطواتك.",
     (("قريباً", "بالقرب"), ("الفانوس", "المصباح"), ("خطواتك",)),
     ("ابقي قريبة", "شاهد خطوتك")),

    # 2. Threats (10)
    ("threats", "You'd better watch your mouth, boy.",
     "من الأفضل أن تحفظ لسانك يا فتى.",
     (("تحفظ لسانك", "تنتبه لكلامك", "تراقب كلامك"), ("فتى", "ولد")),
     ("تراقب فمك", "راقب فمك", "تشاهد فمك")),
    ("threats", "You'd better tell the truth, or you'll regret it.",
     "من الأفضل أن تقول الحقيقة وإلا ستندم.",
     (("تقول",), ("الحقيقة",), ("ستندم", "تندم")),
     ("تقولي", "ستندمين", "تندمين")),
    ("threats", "Take one more step and I'll put a bullet in you.",
     "تحرك خطوة أخرى وسأطلق النار عليك.",
     (("خطوة",), ("أطلق النار عليك", "سأطلق النار عليك", "رصاصة في رأسك")),
     ("سأضع رصاصة فيك", "أضع رصاصة فيك")),
    ("threats", "Don't push your luck with me, stranger.",
     "لا تختبر صبري معي يا غريب.",
     (("تختبر صبري", "تتماد"), ("يا غريب",)),
     ("تدفع حظك", "، غريب.")),
    ("threats", "If you cross me again, there won't be a next time.",
     "إذا خنتني مرة أخرى، لن تكون هناك مرة قادمة.",
     (("خنتني", "غدرت"), ("مرة قادمة", "المرة القادمة")),
     ("تجاوزتني", "عبرتني", "عبرتِني")),
    ("threats", "Keep your hands where I can see them, or else.",
     "أبقِ يديك حيث يمكنني رؤيتهما، وإلا ستندم.",
     (("يديك",), ("رؤيتهما", "رؤيتها", "أراهما", "رؤيتهم"), ("ستندم",)),
     ("، وإلا.", "أبقي يديك", "ابقي يديك", "ستندمين")),
    ("threats", "You had better stay out of our way if you value your life.",
     "من الأفضل أن تبتعد عن طريقنا إذا كنت تقدر حياتك.",
     (("تبتعد",), ("طريقنا",), ("حياتك",)),
     ("تبقى خارج طريقنا",)),
    ("threats", "Touch that gold and it'll be the last thing you ever do.",
     "المس هذا الذهب وسيكون آخر شيء تفعله.",
     (("المس",), ("الذهب",), ("آخر شيء تفعله", "آخر ما تفعله")),
     ("المس تلك الذهب",)),
    ("threats", "Say another word and I'll throw you off this train.",
     "قل كلمة أخرى وسألقي بك من هذا القطار.",
     (("كلمة أخرى",), ("القطار",)),
     ("قولي كلمة",)),
    ("threats", "Mind your tongue when you speak to me.",
     "احفظ لسانك عندما تتحدث معي.",
     (("احفظ لسانك", "انتبه لكلامك", "تحدث باحترام"), ("تتحدث", "تتكلم")),
     ("عقل لسانك", "انتبه إلى لسانك", "تتحدثين")),

    # 3. Jokes & Forms of address (9)
    ("jokes", "Hosea, you old fox, you knew all along!",
     "هوزيا، أيها الثعلب الماكر، كنت تعرف منذ البداية!",
     (("هوزيا",), ("أيها الثعلب",), ("الماكر", "العجوز"), ("كنت تعرف", "تعرف")),
     ("أنت الثعلب", "الثعلب القديم", "هوسيا", "هوشع")),
    ("jokes", "You lucky bastard, I thought you were dead!",
     "أيها الوغد المحظوظ، ظننتك ميتاً!",
     (("أيها الوغد المحظوظ",), ("ظننتك", "اعتقدت أنك", "ظننت أنك"), ("ميت", "مت")),
     ("أنت الوغد المحظوظ",)),
    ("jokes", "Arthur, you stubborn mule, listen to me for once.",
     "آرثر، أيها البغل العنيد، استمع إليّ لمرة واحدة.",
     (("آرثر",), ("أيها البغل العنيد",), ("استمع", "اسمع")),
     ("أنت البغل", "البغل القديم", "أرثر")),
    ("jokes", "Look at you, dressed up like a city banker.",
     "انظر إلى نفسك، متأنق كمصرفي من المدينة.",
     (("انظر",), ("مصرفي",), ("المدينة",)),
     ("أنظر", "انظري")),
    ("jokes", "Relax, I'm just pulling your leg.",
     "اهدأ، أنا أمزح معك فحسب.",
     (("اهدأ", "استرخ"), ("أمزح", "تمازح")),
     ("اهدئي", "اهدأي", "إهدأ", "أسحب ساقك", "أجر ساقك", "أشد رجلك")),
    ("jokes", "You old devil, you haven't changed a bit.",
     "أيها الشيطان العجوز، لم تتغير على الإطلاق.",
     (("أيها الشيطان",), ("العجوز", "الماكر"), ("على الإطلاق", "أبداً", "إطلاقاً")),
     ("أنت الشيطان", "الشيطان القديم", "لم تتغير قليلاً")),
    ("jokes", "If brains were gunpowder, you wouldn't have enough to sneeze.",
     "لو كانت العقول باروداً، لما كان لديك ما يكفي للعطس.",
     (("الأدمغة", "العقول", "العقل"), ("بارود",), ("ما يكفي",), ("للعطس", "لتعطس")),
     ("تملكين", "لديكِ")),
    ("jokes", "Well, look what the cat dragged in.",
     "حسناً، انظروا من ظهر للتو.",
     (("انظروا", "انظر"), ("من ظهر", "من جاء", "من أتى")),
     ("القطة", "القط", "أنظروا")),
    ("jokes", "You crazy son of a gun, you actually pulled it off!",
     "أيها الشيطان المجنون، لقد نجحت فعلاً في القيام بذلك!",
     (("المجنون",), ("نجحت", "فعلتها")),
     ("ابن المسدس", "ابن البندقية", "إبن البندقية", "سحبته", "سحبتها")),

    # 4. Questions (9)
    ("questions", "What the hell happened back there?",
     "ماذا حدث هناك بحق الجحيم؟",
     (("ماذا", "ما الذي"), ("حدث", "حصل"), ("هناك",)),
     ("ما الجحيم",)),
    ("questions", "How far is it to the nearest town?",
     "كم تبعد أقرب مدينة؟",
     (("كم",), ("أقرب",), ("مدينة", "بلدة")),
     ("كيف بعيد",)),
    ("questions", "Who told you where to find our camp?",
     "من أخبرك أين تجد مخيمنا؟",
     (("من أخبرك",), ("مخيمنا", "معسكرنا")),
     ("تجدين",)),
    ("questions", "Why are we still waiting around in this mud?",
     "لماذا ما زلنا ننتظر في هذا الوحل؟",
     (("لماذا", "لمَ"), ("ننتظر",), ("الوحل", "الطين")),
     ("حولها", "حول في")),
    ("questions", "Did anyone follow you from the station?",
     "هل تبعك أحد من المحطة؟",
     (("هل",), ("تبعك", "لحق بك"), ("المحطة",)),
     ("تبعكِ",)),
    ("questions", "Where did you hide the rest of the money?",
     "أين أخفيت بقية المال؟",
     (("أين",), ("أخفيت", "خبأت"), ("المال", "الأموال")),
     ("أخفيتِ",)),
    ("questions", "Are you out of your mind?",
     "هل فقدت عقلك؟",
     (("فقدت عقلك", "جننت"),),
     ("خارج عقلك", "فقدتِ عقلك")),
    ("questions", "How long do you think we can keep running?",
     "إلى متى تعتقد أننا نستطيع الاستمرار في الهرب؟",
     (("إلى متى", "كم من الوقت"), ("تعتقد", "تظن"), ("الهرب", "الركض", "الجري")),
     ("تعتقدين", "الإستمرار")),
    ("questions", "What are we supposed to do now?",
     "ماذا يفترض بنا أن نفعل الآن؟",
     (("ماذا", "ما الذي"), ("يفترض", "علينا"), ("نفعل", "فعله"), ("الآن",)),
     ()),

    # 5. Glossary names (10)
    ("names", "Dutch and Hosea are waiting for us in Blackwater.",
     "داتش وهوزيا ينتظروننا في بلاكووتر.",
     (("داتش",), ("هوزيا",), ("بلاكووتر",)),
     ("هولند", "المياه السوداء", "إدوارد", "هارولد")),
    ("names", "Did Bill leave the supplies at Wallace Station?",
     "هل ترك بيل المؤن في محطة والاس؟",
     (("بيل",), ("محطة والاس",)),
     ("فاتورة", "إدوارد", "هارولد")),
    ("names", "The Pinkertons have surrounded Braithwaite Manor!",
     "البينكرتون حاصروا قصر بريثويت!",
     (("البينكرتون",), ("حاصروا", "حاصر البينكرتون"), ("قصر بريثويت",)),
     ("البينكرتون حاصر ", "إدوارد", "هارولد")),
    ("names", "Tell John Marston to meet me near Strawberry.",
     "أخبر جون مارستن أن يقابلني بالقرب من ستروبيري.",
     (("جون مارستن",), ("يقابلني", "يلتقي بي"), ("ستروبيري",)),
     ("الفراولة", "فراولة", "مارستون", "إدوارد", "هارولد")),
    ("names", "A gang of O'Driscolls ambushed the wagon near Big Valley.",
     "عصابة من الأودريسكول نصبت كميناً للعربة بالقرب من بيغ فالي.",
     (("الأودريسكول",), ("كمين",), ("بيغ فالي",)),
     ("الوادي الكبير", "إدوارد", "هارولد")),
    ("names", "Have you seen Uncle or Reverend Swanson this morning?",
     "هل رأيت العم أو القس سوانسون هذا الصباح؟",
     (("العم",), ("القس سوانسون",), ("الصباح",)),
     ("عمي", "خالي", "إدوارد", "هارولد")),
    ("names", "Agent Milton offered a reward for Dutch van der Linde.",
     "عرض العميل ميلتون مكافأة لداتش فان دير ليند.",
     (("العميل ميلتون",), ("مكافأة",), ("داتش فان دير ليند",)),
     ("هولند", "إدوارد", "هارولد")),
    ("names", "We're riding to Saint Denis before nightfall.",
     "نحن نتجه إلى سانت دينيس قبل حلول الظلام.",
     (("متجهون", "نتجه", "سنتجه", "ذاهبون", "نسير"), ("سانت دينيس",), ("الظلام", "المساء", "الليل")),
     ("نركب إلى", "القديس دينيس", "سان دينيس")),
    ("names", "Give the letter to Charles Smith when you reach Colter.",
     "أعط الرسالة إلى تشارلز سميث عندما تصل إلى كولتر.",
     (("أعط", "سلّم"), ("تشارلز سميث",), ("كولتر",)),
     ("اعط ", "إدوارد", "هارولد")),
    ("names", "The Skinner Brothers burned down the old mill.",
     "الإخوة سكينر أحرقوا الطاحونة القديمة.",
     (("الإخوة سكينر",), ("أحرقوا", "أحرق الإخوة"), ("الطاحونة",)),
     ("الإخوة سكينر أحرق ", "المصنع", "إدوارد")),

    # 6. Women's names (10)
    ("women", "Sadie, stay here and watch the horses.",
     "سايدي، ابقي هنا وراقبي الخيول.",
     (("سايدي",), ("ابقي",), ("راقبي", "احرسي"), ("الخيول",)),
     ("والبقاء", "ومشاهدة", "ابق هنا", "راقب الخيول", "فيكتوريا")),
    ("women", "Abigail! Run to the house and lock the door!",
     "أبيغيل! اركضي إلى المنزل وأغلقي الباب!",
     (("أبيغيل",), ("اركضي", "اهربي"), ("أغلقي", "اقفلي")),
     ("اركض ", "وأغلق ", "أغلق الباب", "فيكتوريا")),
    ("women", "Karen is waiting for us by the river.",
     "كارين تنتظرنا عند النهر.",
     (("كارين",), ("تنتظرنا", "بانتظارنا"), ("النهر",)),
     ("ينتظرنا", "فيكتوريا")),
    ("women", "I told Tilly to pack her things before dawn.",
     "أخبرت تيلي أن تحزم أغراضها قبل الفجر.",
     (("تيلي",), ("تحزم", "تجمع", "تجهز"), ("أغراضها", "أمتعتها", "أشياءها"), ("الفجر",)),
     ("يحزم", "أغراضه ", "فيكتوريا")),
    ("women", "Mrs. Adler, are you sure about this?",
     "السيدة آدلر، هل أنت متأكدة من هذا؟",
     (("سيدة آدلر", "السيدة آدلر"), ("متأكدة",)),
     ("متأكد ", "متأكد؟", "فيكتوريا")),
    ("women", "Miss Grimshaw wants to speak with you right now.",
     "الآنسة غريمشو تريد التحدث معك الآن.",
     (("الآنسة غريمشو",), ("تريد", "ترغب"), ("التحدث", "تتحدث")),
     ("يريد", "فيكتوريا")),
    ("women", "Sadie, Tilly and Karen left the camp an hour ago.",
     "سايدي وتيلي وكارين غادرن المخيم قبل ساعة.",
     (("سايدي",), ("تيلي",), ("كارين",), ("غادرن", "غادرت"), ("المخيم", "المعسكر")),
     ("غادروا", "غادر المخيم", "فيكتوريا", "كاثرين", "إليزابيث")),
    ("women", "Don't worry, Charlotte. You're safe now.",
     "لا تقلقي يا شارلوت. أنت بأمان الآن.",
     (("لا تقلقي",), ("شارلوت",), ("بأمان", "آمنة")),
     ("لا تقلق ", "لا تقلق،", "فيكتوريا")),
    ("women", "Mary-Beth found a lead on a stagecoach robbery.",
     "ماري بيث وجدت دليلاً على سرقة عربة.",
     (("ماري بيث",), ("وجدت", "عثرت"), ("سرقة", "سطو"), ("عربة",)),
     ("وجد ", "حافلة", "فيكتوريا")),
    ("women", "Listen to me, Molly! Come inside before the storm hits!",
     "استمعي لي يا مولي! تعالي للداخل قبل أن تضرب العاصفة!",
     (("استمعي", "اسمعيني", "اسمعي"), ("مولي",), ("تعالي", "ادخلي"), ("العاصفة",)),
     ("استمع ", "اسمع ", "تعال ", "ادخل ", "فيكتوريا")),

    # 7. Numbers (8)
    ("numbers", "He owes me $250 and I want every cent today.",
     "إنه مدين لي بـ250 دولار وأريد كل سنت اليوم.",
     (("مدين", "يدين"), ("250",), ("دولار",), ("سنت",)),
     ()),
    ("numbers", "There's a 50% chance the guards are still awake.",
     "هناك احتمال 50٪ أن الحراس لا يزالون مستيقظين.",
     (("50",), ("الحراس",), ("مستيقظين",)),
     ("لا تزال مستيقظا", "فرصة 50٪ الحراس")),
    ("numbers", "The train leaves at 10:30, so don't be late.",
     "سيغادر القطار الساعة 10:30 لذا لا تتأخر.",
     (("القطار",), ("10:30",), ("لا تتأخر",)),
     ("10: 30", "10 :30", "لا تتأخري")),
    ("numbers", "We rode 15 miles through the snow in 1899.",
     "ركبنا 15 ميلاً عبر الثلج في عام 1899.",
     (("15",), ("ميل",), ("الثلج", "الثلوج"), ("1899",)),
     ()),
    ("numbers", "Count to 3, then blow the safe open.",
     "عد إلى 3 ثم فجر الخزنة.",
     (("عد", "عدّ"), ("3", "ثلاثة"), ("فجر", "فجّر"), ("الخزنة",)),
     ("انفخ", "آمنة")),
    ("numbers", "They offered a $5,000 bounty on his head.",
     "عرضوا مكافأة قدرها 5000 دولار على رأسه.",
     (("مكافأة", "جائزة", "فدية"), ("5000", "5,000"), ("دولار",), ("رأسه",)),
     ()),
    ("numbers", "Only 4 of the 12 horses survived the winter.",
     "لم ينج سوى 4 من أصل 12 حصاناً في فصل الشتاء.",
     (("4", "أربعة"), ("12",), ("حصان", "خيول"), ("الشتاء",)),
     ()),
    ("numbers", "Give me 20 minutes and I'll have that lock open.",
     "أمهلني 20 دقيقة وسأفتح ذلك القفل.",
     (("20", "عشرين"), ("دقيقة",), ("أفتح", "سأفتح"), ("القفل",)),
     ("اعطني", "أعطيني")),

    # 8. Slang & contractions (10)
    ("slang", "I ain't gonna lie to you, partner.",
     "لن أكذب عليك يا شريكي.",
     (("لن أكذب", "لا أكذب"), ("شريكي", "صديقي", "رفيقي")),
     ("، شريك.",)),
    ("slang", "We gotta get outta here before the law shows up.",
     "يجب أن نخرج من هنا قبل وصول الشرطة.",
     (("نخرج", "نغادر", "نهرب"), ("من هنا",), ("الشرطة", "رجال القانون")),
     ("يظهر القانون",)),
    ("slang", "It's freezin' out here and I'm starvin'.",
     "الجو بارد هنا وأنا أتضور جوعاً.",
     (("بارد", "متجمد", "صقيع"), ("أتضور جوعاً", "جائع جداً")),
     ("إنه حر هنا", "الجو حار")),
    ("slang", "I dunno what you're talkin' about.",
     "أنا لا أعرف ما الذي تتحدث عنه.",
     (("لا أعرف", "لا أدري"), ("تتحدث", "تتكلم")),
     ("تتحدثين", "تتكلمين")),
    ("slang", "Lemme see what you've got in that bag.",
     "دعني أرى ما لديك في تلك الحقيبة.",
     (("دعني", "خلني"), ("أرى",), ("الحقيبة", "الكيس")),
     ("لديكِ",)),
    ("slang", "Gimme the keys and nobody gets hurt.",
     "أعطني المفاتيح ولن يتأذى أحد.",
     (("أعطني",), ("المفاتيح",), ("يتأذى", "يصاب")),
     ("اعطني", "أعطيني")),
    ("slang", "Y'all better get some rest tonight.",
     "من الأفضل لكم جميعاً أن ترتاحوا الليلة.",
     (("الأفضل", "عليكم"), ("جميعاً", "كلكم"), ("ترتاحوا", "الراحة"), ("الليلة",)),
     ()),
    ("slang", "I cant believe he didnt warn us.",
     "لا أصدق أنه لم يحذرنا.",
     (("لا أصدق", "لا أستطيع تصديق"), ("لم يحذرنا", "لم ينبهنا")),
     ("كانت", "ديدنت")),
    ("slang", "Whatcha doin' out here all by yourself?",
     "ماذا تفعل هنا وحدك؟",
     (("ماذا تفعل", "ما الذي تفعله"), ("هنا",), ("وحدك", "لوحدك", "بمفردك")),
     ("تفعلين", "لوحدكِ")),
    ("slang", "C'mere and give me a hand with this crate.",
     "تعال إلى هنا وساعدني في هذا الصندوق.",
     (("تعال",), ("ساعدني",), ("الصندوق",)),
     ("تعالي", "ساعديني", "أعطني يداً")),

    # 9. Idioms (12)
    ("idioms", "Keep an eye on the road while I check the horses.",
     "راقب الطريق بينما أتحقق من الخيول.",
     (("راقب", "انتبه"), ("الطريق",), ("الخيول",)),
     ("أبقِ عينك", "ابقي عينك", "راقبي")),
    ("idioms", "Get a hold of yourself, we're not dead yet.",
     "تمالك نفسك، نحن لم نمت بعد.",
     (("تمالك نفسك", "اهدأ"), ("لم نمت",), ("بعد",)),
     ("اهدأي", "اهدئي", "أمسك بنفسك", "أمسكي بنفسك", "لم نموت")),
    ("idioms", "Don't take it out on me, it wasn't my fault.",
     "لا تلمني، لم يكن خطأي.",
     (("لا تلمني", "لا تفرغ غضبك"), ("خطئي", "خطأي", "ذنبي")),
     ("لا تلومني", "لا تلوميني", "تأخذه علي", "تخرجه علي")),
    ("idioms", "Hold your horses, I'm coming as fast as I can.",
     "تمهّل قليلاً، أنا قادم بأسرع ما يمكن.",
     (("تمهّل", "تمهل", "انتظر لحظة"), ("قادم", "آتٍ"), ("بأسرع",)),
     ("أمسك خيولك", "امسك خيولك", "أمسكوا خيولكم")),
    ("idioms", "We're in the clear now, slow down.",
     "نحن في أمان الآن، تمهل.",
     (("في أمان", "بأمان"), ("الآن",), ("تمهل", "تمهّل", "خفف")),
     ("في الواضح",)),
    ("idioms", "Let's call it a day and head back to camp.",
     "لنكتفِ بهذا اليوم ونعود إلى المخيم.",
     (("اليوم",), ("نعود", "نرجع"), ("المخيم", "المعسكر")),
     ("ندعوه يوماً", "نسميه يوماً", "ندعوه a")),
    ("idioms", "He vanished into thin air right in front of us.",
     "لقد اختفى بدون أي أثر أمامنا.",
     (("اختفى",), ("دون أثر", "بدون أي أثر", "بدون أثر", "تماماً", "من العدم"), ("أمام",)),
     ("الهواء الرقيق", "اختفى في الهواء")),
    ("idioms", "Make up your mind before it's too late.",
     "اتخذ قرارك قبل فوات الأوان.",
     (("اتخذ قرارك", "احسم أمرك", "قرر"), ("قبل فوات الأوان",)),
     ("اصنع عقلك", "إتخذ")),
    ("idioms", "Save your breath, he won't listen to reason.",
     "لا تتعب نفسك في الكلام، فهو لن يستمع إلى المنطق.",
     (("لا تتعب نفسك", "لا تضيع كلامك"), ("لن يستمع", "لن يصغي"), ("المنطق", "العقل")),
     ("وفّر أنفاسك", "وفر أنفاسك", "احفظ أنفاسك", "إلى السبب")),
    ("idioms", "Mark my words, this whole plan will end in blood.",
     "تذكر كلماتي، هذه الخطة كلها ستنتهي بالدم.",
     (("تذكر", "تذكّر", "اسمعها مني"), ("الخطة",), ("الدم", "الدماء")),
     ("علّم كلماتي", "ضع علامة")),
    ("idioms", "I'm sick and tired of your excuses.",
     "لقد سئمت من أعذارك.",
     (("سئمت", "مللت", "ضقت ذرعاً"), ("أعذارك", "حججك")),
     ("مريض ومتعب",)),
    ("idioms", "By the way, your horse threw a shoe.",
     "بالمناسبة، فقد حصانك حدوته.",
     (("بالمناسبة", "على فكرة"), ("حصانك",), ("حدوته", "حدوة")),
     ("ألقى حذاء", "رمى حذاء", "حدوة حصانه")),

    # 10. Phrasal verbs (12)
    ("phrasal", "The bridge is out, we'll have to go around.",
     "الجسر مسدود، لذا يجب أن نلتف حوله.",
     (("الجسر",), ("مقطوع", "مدمّر", "مدمر", "محطم", "مسدود", "مغلق", "معطل"), ("نلتف", "طريق آخر", "طريقاً آخر")),
     ("الجسر خارج", "سيكون لدينا", "للذهاب حولها")),
    ("phrasal", "The fire is out, and the night is getting colder.",
     "لقد انطفأت النار والليل يزداد برودة.",
     (("انطفأت", "أطفئت"), ("النار",), ("الليل",), ("برودة", "أبرد")),
     ("النار خارج", "اطفئت")),
    ("phrasal", "He lost a lot of blood, I don't think he'll make it.",
     "لقد فقد الكثير من الدماء، لا أعتقد أنه سينجو.",
     (("فقد", "خسر"), ("الدماء", "الدم"), ("لا أعتقد", "لا أظن"), ("سينجو", "سيعيش")),
     ("يصنعها", "يفعلها", "الدماء لا أعتقد")),
    ("phrasal", "Times are hard, but we'll get by somehow.",
     "الأوقات صعبة، لكننا سنتدبر أمرنا بطريقة ما.",
     (("صعبة", "قاسية"), ("سنتدبر", "نتدبر"), ("بطريقة ما", "بشكل ما")),
     ("سنمر", "سنحصل على")),
    ("phrasal", "It's past midnight, I'm going to turn in.",
     "لقد فات منتصف الليل، لذا سأخلد للنوم.",
     (("منتصف الليل",), ("سأخلد", "سأذهب", "أخلد"), ("النوم", "للنوم")),
     ("سأسلم نفسي", "أتحول في", "أنعطف")),
    ("phrasal", "If they catch you, they'll turn you in to the sheriff.",
     "إذا أمسكوا بك، سيسلمونك إلى الشريف.",
     (("أمسكوا", "قبضوا"), ("سيسلمونك", "يسلمونك"), ("الشريف", "المأمور")),
     ("يحولونك",)),
    ("phrasal", "We're running out of ammo, make every shot count!",
     "لقد نفدت ذخيرتنا، لذا لا تهدر طلقة واحدة!",
     (("نفدت", "تنفد"), ("الذخيرة", "ذخيرتنا"), ("لا تضيعوا", "لا تهدر", "لا تضيع", "كل طلقة في محلها")),
     ("نفذت", "تجري خارج", "اجعلوا كل طلقة تحسب", "اجعلوا كل طلقة تُحسب")),
    ("phrasal", "My horse gave out halfway up the mountain.",
     "انهار حصاني من الإرهاق في منتصف الطريق إلى أعلى الجبل.",
     (("انهار", "خارت قوى", "أنهك"), ("حصاني",), ("منتصف",), ("الجبل",)),
     ("تخلى عن", "أعطى خارج", "خرج في منتصف")),
    ("phrasal", "Hold out a little longer, help is on the way!",
     "اصمدوا قليلاً بعد، المساعدة في الطريق!",
     (("اصمد", "اصمدوا", "تحمّل", "تحمل", "انتظر"), ("المساعدة", "النجدة"), ("الطريق",)),
     ("امسك للخارج",)),
    ("phrasal", "They called off the search when the blizzard started.",
     "لقد أوقفوا البحث عندما بدأت العاصفة الثلجية.",
     (("أوقفوا", "ألغوا"), ("البحث",), ("العاصفة الثلجية",)),
     ("اتصلوا بـ", "نادوا البحث")),
    ("phrasal", "Keep your voice down or you'll give us away.",
     "أخفض صوتك وإلا فضحتنا.",
     (("اخفض", "أخفض"), ("صوتك",), ("فضحتنا", "تفضح", "تكشف", "كشفت")),
     ("ستتركنا", "تعطينا بعيداً", "تتخلى عن")),
    ("phrasal", "We need to lay low until the heat dies down.",
     "يجب أن نختبئ حتى تهدأ الأمور.",
     (("نختبئ", "نتوارى", "التواري"), ("تهدأ",), ("الأمور", "الأوضاع")),
     ("تزول الحرارة", "تموت الحرارة", "نستلقي منخفضين")),
)

# Per-line quality tiers measured before Round 2 improvements (47 exact=2, 14 near=1, 39 broken=0).
BASELINE_TIERS: tuple[int, ...] = (
    0, 2, 2, 2, 0, 1, 2, 1, 0, 1,  # orders
    0, 0, 0, 0, 0, 0, 2, 2, 2, 0,  # threats
    0, 2, 2, 1, 0, 0, 1, 0, 0,     # jokes
    2, 2, 2, 2, 2, 2, 2, 1, 2,     # questions
    2, 2, 0, 2, 2, 2, 2, 0, 1, 0,  # names
    0, 0, 2, 2, 2, 2, 0, 2, 0, 2,  # women
    2, 0, 0, 2, 2, 2, 1, 2,        # numbers
    2, 0, 2, 2, 2, 2, 2, 2, 1, 1,  # slang
    2, 0, 0, 1, 2, 1, 0, 2, 0, 2, 2, 0,  # idioms
    0, 0, 0, 0, 0, 1, 0, 0, 1, 2, 0, 0,  # phrasal
)


def _norm_cmp(s: str) -> str:
    return (
        s.replace("ِ", "").replace("ُ", "").replace("َ", "").replace("ّ", "")
        .replace("إ", "ا").replace("أ", "ا").replace("،", "")
    )


def score_line(ar: str, ideal: str, accept_groups: tuple[tuple[str, ...], ...], bad_substrings: tuple[str, ...]) -> int:
    """Returns 2 for exact match, 1 for near match, 0 for literal or broken output."""
    if any("a" <= c.lower() <= "z" for c in ar):
        return 0
    if any(b in ar for b in bad_substrings):
        return 0
    if not all(any(opt in ar for opt in grp) for grp in accept_groups):
        return 0
    if _norm_cmp(ar) == _norm_cmp(ideal):
        return 2
    return 1


def evaluate_engine() -> dict:
    """Run the 100-line evaluation set through CachedTranslator (uncached) and return quality & latency stats."""
    pack = json.loads((paths.REPO / "packs" / "rdr2.json").read_text(encoding="utf-8"))
    glossary = {row["en"]: row["ar"] for row in pack["names"]}
    female = {row["en"] for row in pack["names"] if row.get("f")}

    engine = OpusTranslator()
    engine.translate("Hello.")
    cache = Cache(":memory:")
    tr = CachedTranslator(engine, cache, profile="rdr2", glossary=glossary, female=female)

    # Pre-warm only the glossary names that appear in the evaluation set (just as prepare_names does in session).
    used_names = []
    all_en = " ".join(item[1] for item in EVAL_SET)
    for en, ar, pat in tr._patterns:
        if pat.search(all_en):
            used_names.append((en, ar))
    tr.names.prepare(used_names)

    tiers: list[int] = []
    times: list[float] = []
    outputs: list[str] = []
    regressions: list[tuple[int, str, str, int, int]] = []

    for idx, (cat, en, ideal, accept, bad) in enumerate(EVAL_SET):
        t0 = time.perf_counter()
        ar, hit, _ = tr.translate(en)
        dt = (time.perf_counter() - t0) * 1000.0
        assert not hit, f"Duplicate line in EVAL_SET at index {idx}: {en}"
        tier = score_line(ar, ideal, accept, bad)
        tiers.append(tier)
        times.append(dt)
        outputs.append(ar)
        # Worse means broken or word-for-word where it was not before. Another correct wording
        # (exact -> near: «استمعي إليّ» for «استمعي لي») is not a regression.
        if tier == 0 and BASELINE_TIERS[idx] > 0:
            regressions.append((idx, en, ar, BASELINE_TIERS[idx], tier))

    return {
        "total": len(EVAL_SET),
        "exact": tiers.count(2),
        "near": tiers.count(1),
        "broken": tiers.count(0),
        "p50_ms": float(np.percentile(times, 50)),
        "p90_ms": float(np.percentile(times, 90)),
        "tiers": tiers,
        "outputs": outputs,
        "regressions": regressions,
    }


def test_eval_set_quality_and_zero_regressions():
    assert len(EVAL_SET) >= 80
    assert len(EVAL_SET) == len(BASELINE_TIERS)
    res = evaluate_engine()
    assert res["regressions"] == [], f"Lines got worse than baseline: {res['regressions']}"
    assert res["exact"] + res["near"] >= 90, f"Expected >=90 good translations, got {res['exact']} exact + {res['near']} near ({res['broken']} broken)"
    assert res["exact"] >= 65, f"Expected >=65 exact matches, got {res['exact']}"
    assert res["broken"] <= 10, f"Expected <=10 broken outputs, got {res['broken']}"
