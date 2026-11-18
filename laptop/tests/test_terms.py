"""Game words (tarjim/terms.py): what changes, and what must stay as it is."""

import pytest

from tarjim import terms
from tarjim.translate import Cache, CachedTranslator


@pytest.mark.parametrize("profile, title, series", [
    ("rdr2", "", "rdr"), ("gta5", "", "gta"), ("tlou2", "", "tlou"), ("lad8", "", "yakuza"),
    ("my-rdr", "Red Dead Redemption 2", "rdr"), ("x", "Like a Dragon Gaiden", "yakuza"), ("default", "", ""),
    ("bg3", "Baldur's Gate 3", ""),
])
def test_series(profile, title, series):
    assert terms.series_of(profile, title) == series


@pytest.mark.parametrize("en, series, out", [
    ("Hogtie him and put him on your horse.", "rdr", "tie him up and put him on your horse."),
    ("Lasso the horse before it runs off.", "rdr", "catch the horse with your rope before it runs away."),
    ("Parley with them first.", "", "negotiate with them first."),
    ("We'll case the bank tomorrow.", "", "We'll scout the bank tomorrow."),
    ("Lose the law before you go back to camp.", "rdr", "escape from the police before you go back to camp."),
    ("The cops are on us, lose them!", "gta", "The cops are on us, escape from them!"),
    ("Shake them off!", "", "escape from them!"),
    ("If the law finds us here, we're finished.", "", "If the police finds us here, we're finished."),
    ("The law is coming, saddle up!", "", "The police is coming, get on your horse!"),
    ("Uncle, wake up, we've got company.", "", "Uncle, wake up, we have visitors."),
    ("Meet me at the safehouse.", "", "Meet me at the hideout."),
    ("You've got a five-star wanted level.", "gta", "the police are chasing you with five stars."),
    ("Take the stolen wagon to the fence.", "rdr", "Take the stolen wagon to the stolen goods dealer."),
    ("Do your chores.", "", "Do your tasks."),
    ("Lay low for a few days.", "", "stay out of sight for a few days."),
    ("Kiryu-chan, you came!", "yakuza", "Kiryu, you came!"),
    ("He's my sworn brother.", "yakuza", "He's my brother by oath."),
    ("The patriarch of the Dojima Family has spoken.", "yakuza", "The head of the Dojima Family has spoken."),
    ("We hit the train tomorrow night.", "rdr", "We rob the train tomorrow night."),
])
def test_rewrites(en, series, out):
    assert terms.rewrite(en, series).lower() == out.lower()


@pytest.mark.parametrize("en, series", [
    ("That's against the law, Arthur.", "rdr"),
    ("It's the law.", "rdr"),
    ("In case the bank is guarded, bring dynamite.", "rdr"),
    ("Jump over the fence and wait for me.", "rdr"),
    ("We can't lose him, he's family.", "rdr"),
    ("I don't want to lose them.", ""),
    ("Fish are jumping in the lake.", "rdr"),
    ("The car hit the truck.", "gta"),
    ("Hold up, I need to catch my breath.", ""),
    ("The company is doing well.", "gta"),
    ("He's the patriarch.", "rdr"),  # only in Yakuza
    ("Kiryu-chan!", "rdr"),  # honorifics only in Yakuza
    ("Majima-san wants to see you.", "yakuza"),  # "-san" keeps the model from taking him for a woman
])
def test_left_alone(en, series):
    assert terms.rewrite(en, series) == en


@pytest.mark.parametrize("ar, en, out", [
    ("شراء بعض منشط في المتجر العام.", "Buy some tonic at the general store.", "اشتر بعض منشط في المتجر العام."),
    ("دفع أموال الحماية في الوقت المحدد.", "Pay the protection money on time.", "ادفع أموال الحماية في الوقت المحدد."),
    ("التفاوض معهم أولاً.", "negotiate with them first.", "تفاوض معهم أولاً."),
    ("سلخ الغزلان واتخاذ اللحم.", "Skin the deer and take the meat.", "اسلخ الغزلان وخذ اللحم."),
    ("سايدي، شراء بعض المنشط.", "Sadie, buy some tonic.", "سايدي، اشتر بعض المنشط."),
    ("إنقاذها!", "Save her!", "أنقذها!"),
    # a noun, not a command: left alone
    ("الهروب مستحيل.", "Escape is impossible.", "الهروب مستحيل."),
    ("الصيد ممتع.", "Hunting is fun.", "الصيد ممتع."),
    ("شراء الأسلحة غير قانوني.", "The buying of guns is illegal.", "شراء الأسلحة غير قانوني."),
])
def test_commands_not_nouns(ar, en, out):
    assert terms.commands_not_nouns(ar, en) == out


def test_fix_arabic():
    assert terms.fix_arabic("ابتعد عن الجراثيم.", "Stay away from the spores.", "tlou") == "ابتعد عن الأبواغ."
    assert terms.fix_arabic("ابتعد عن الجراثيم.", "Stay away from the germs.", "tlou") == "ابتعد عن الجراثيم."
    assert terms.fix_arabic("ابتعد عن الجراثيم.", "Stay away from the spores.", "rdr") == "ابتعد عن الجراثيم."


class _Echo:
    """An engine that shows what it was given: the rewritten English, then one Arabic word."""

    name = "echo"

    def __init__(self):
        self.seen = []

    def translate(self, text, context=None):
        self.seen.append(text)
        return "شراء بعض المنشط." if text.lower().startswith("buy") else "حسناً."


def test_translator_uses_the_series(tmp_path):
    engine = _Echo()
    t = CachedTranslator(engine, Cache(tmp_path / "c.sqlite"), profile="rdr2", series="rdr")
    t.translate("Take it to the fence and sell it.")
    assert engine.seen[-1] == "Take it to the stolen goods dealer and sell it."
    ar, _hit, _ms = t.translate("Buy some tonic.")
    assert ar.startswith("اشتر")
    plain = CachedTranslator(engine, Cache(tmp_path / "d.sqlite"), profile="bg3")
    plain.translate("Take it to the fence and sell it.")
    assert engine.seen[-1] == "Take it to the fence and sell it."
