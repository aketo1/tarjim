"""Commands put in the gender of the one spoken to (tarjim/gender.py), and the engine rules
around them. Sentences written for these tests."""

from tarjim import gender
from tarjim.translate import Cache, CachedTranslator, _is_group, preprocess_english


def test_a_command_to_nobody_named_or_a_man_is_masculine():
    m = gender.masculinize
    assert m("خافيير، غطّي الجانب الأيسر.") == "خافيير، غطّ الجانب الأيسر."
    assert m("ابصقيها الآن!") == "ابصقها الآن!"
    assert m("خذي البندقية وغطّيني.") == "خذ البندقية وغطّني."
    assert m("ابقي خلفي ولا تصدري صوتاً.") == "ابق خلفي ولا تصدر صوتاً."
    assert m("لا تخافي!") == "لا تخف!"
    assert m("اهدئي، كل شيء بخير.") == "اهدأ، كل شيء بخير."
    assert m("اعطيني المفتاح.") == "أعطني المفتاح."  # the missing hamza comes back
    assert m("سأعطيك المال، ثم اذهبي.") == "سأعطيك المال، ثم اذهب."
    assert m("ماذا تفعلين هنا؟") == "ماذا تفعل هنا؟"
    assert m("قولي لي الحقيقة.") == "قل لي الحقيقة."


def test_words_that_only_look_like_commands_stay():
    m = gender.masculinize
    assert m("جدي كان رجلاً طيباً.") == "جدي كان رجلاً طيباً."  # my grandfather
    assert m("دوري الآن.") == "دوري الآن."  # my turn
    assert m("دعني ألقي نظرة على الجرح.") == "دعني ألقي نظرة على الجرح."  # "I" take a look
    assert m("لا تعني شيئاً.") == "لا تعني شيئاً."  # she does not mean anything
    f = gender.feminize
    assert f("وقف الرجل أمام الباب.") == "وقف الرجل أمام الباب."  # stood, not "stop"
    assert f("وجد الحصان في الوادي.") == "وجد الحصان في الوادي."
    assert f("إذا أردت، أذهب معك.") == "إذا أردت، أذهب معك."  # "I" go


def test_a_command_to_a_woman_is_feminine():
    f = gender.feminize
    assert f("سايدي، ابق هنا وراقب الخيول.") == "سايدي، ابقي هنا وراقبي الخيول."
    assert f("كارين، ضع الزجاجة جانباً وساعدني.") == "كارين، ضعي الزجاجة جانباً وساعديني."
    assert f("تيلي، لا تتحرك ولا تتركني.") == "تيلي، لا تتحركي ولا تتركيني."
    assert f("سوزان، عد إلى المخيم.") == "سوزان، عودي إلى المخيم."
    assert f("كارين، كن حذرة.") == "كارين، كوني حذرة."
    assert f("مولي، أجبني!") == "مولي، أجيبيني!"
    assert f("كارين، اقرأ هذا.") == "كارين، اقرئي هذا."


def test_groups_of_people_are_plural():
    assert _is_group("Pinkertons", "البينكرتون") and _is_group("Murfrees", "آل مورفري")
    assert not _is_group("Charles", "تشارلز") and not _is_group("Strauss", "شتراوس")


def test_idioms_become_plain_english_first():
    assert preprocess_english("Thank you, I owe you one.") == "Thank you, I owe you a favor."
    assert preprocess_english("I don't trust him, not one bit.") == "I don't trust him, not at all."
    assert "shameless" in preprocess_english("He's got some nerve asking for more.")
    assert preprocess_english("Spit it out already!") == "Say it now!"


class GenderEngine:
    """Answers like the real model at its worst: every command said to a woman."""

    name = "g"

    def translate(self, text, context=None):
        return {"Javier, cover the left side.": "(خافيير)، غطّي الجانب الأيسر.",
                "Edward, cover the left side.": "إدوارد، غطّي الجانب الأيسر."}.get(text, "كلمة")


def test_a_man_addressed_by_name_gets_masculine_commands():
    tr = CachedTranslator(GenderEngine(), Cache(":memory:"), profile="g", glossary={"Javier": "خافيير"})
    assert tr.translate("Javier, cover the left side.")[0] == "خافيير، غطّ الجانب الأيسر."
