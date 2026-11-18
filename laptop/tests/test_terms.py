"""Game words (tarjim/terms.py): what changes, and what must stay as it is."""

import pytest

from tarjim import terms
from tarjim.translate import Cache, CachedTranslator


@pytest.mark.parametrize("profile, title, series", [
    ("rdr2", "", "rdr"), ("gta5", "", "gta"), ("tlou2", "", "tlou"), ("lad8", "", "yakuza"),
    ("my-rdr", "Red Dead Redemption 2", "rdr"), ("x", "Like a Dragon Gaiden", "yakuza"), ("default", "", ""),
    ("bg3", "Baldur's Gate 3", "bg3"), ("kcd2", "", "kcd"), ("mafia-toc", "", "mafia"), ("p5r", "", "persona"),
    ("my-sh", "Silent Hill 2", "sh"), ("x", "Some Other Game", ""),
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


@pytest.mark.parametrize("en, series, out", [
    ("Howdy, partner. Much obliged.", "rdr", "Hello, partner. Thank you very much."),
    ("We gotta high-tail it outta here.", "rdr", "We gotta run away outta here."),
    ("The jig is up, Dutch.", "rdr", "It's over, Dutch."),
    ("Yonder's the cabin.", "rdr", "Over there is the cabin."),
    ("He's packing a heater, be careful.", "lanoire", "He's carrying a gun, be careful."),
    ("Let's sweat him a little.", "lanoire", "Let's pressure him a little."),
    ("He's a made man now.", "mafia", "He's a full member of the mafia now."),
    ("Omertà is everything.", "mafia", "The law of silence is everything."),
    ("Pay the pizzo.", "mafia", "Pay the protection money."),
    ("They whacked him last night.", "mafia", "They killed him last night."),
    ("He ratted us out.", "gta", "He informed on us to the police."),
    ("You strapped?", "gta", "You armed?"),
    ("The opps are rolling up on us.", "gta", "The enemies are coming at us."),
    ("We gotta hit a lick tonight.", "gta", "We gotta do a robbery tonight."),
    ("Nice whip, bro.", "gta", "Nice car, bro."),
    ("Five-O! Run!", "gta", "Police! Run!"),
    ("Hold thy tongue, peasant!", "kcd", "Be quiet, peasant!"),
    ("Methinks he lies.", "kcd", "I think he lies."),
    ("Wait here ere nightfall.", "kcd", "Wait here before nightfall."),
    ("Tango down.", "", "The enemy is dead."),
    ("Roger that.", "", "Understood."),
    ("Clear!", "", "The area is clear!"),
    ("The favela is crawling with gangsters.", "maxpayne", "The favela is full of gangsters."),
    ("The boss wants a word with you.", "", "The boss wants to talk to you."),
    ("Don't worry about me, worry about yourself.", "", "Don't worry about me, take care of yourself."),
    ("The radio is making static again.", "sh", "The radio is making noise again."),
    ("Go to class or you'll get detention.", "bully", "Go to class or you'll get punished after school."),
    ("Don't let them give you a wedgie.", "bully", "Don't let them humiliate you."),
    ("We need to send the calling card.", "persona", "We need to send the warning card."),
    ("Makoto-senpai, wait!", "persona", "Makoto, wait!"),
    ("The lieutenant wants to see you.", "yakuza", "The deputy wants to see you."),
    ("Runners! Get behind me.", "tlou", "Runners are coming! Get behind me."),
])
def test_slang_and_series_words(en, series, out):
    assert terms.rewrite(en, series) == out


@pytest.mark.parametrize("en, series", [
    ("He's a self-made man.", "mafia"),
    ("He whacked him with a stick.", "bully"),  # killed only in a crime story
    ("Use your whip on the horse.", "rdr"),  # a car only in GTA
    ("I'm strapped for cash.", "gta"),
    ("The coast is clear, let's go.", ""),
    ("I'll wait here.", "kcd"),
    ("The lieutenant wants to see you.", "maxpayne"),  # deputy only in Yakuza
    ("We need to send the calling card.", "gta"),
    ("Runners are fast.", "tlou"),
    ("The static on his shirt.", "rdr"),
])
def test_slang_left_alone(en, series):
    assert terms.rewrite(en, series) == en


@pytest.mark.parametrize("ar, en, out", [
    ("الرانرز قادمون! إبقى خلفي.", "Runners are coming! Get behind me.", "الرانرز قادمون! ابق خلفي."),
    ("لا تطلق النار إلا إذا أطلقوا أولاً.", "Don't shoot unless they shoot first.", "لا تطلق النار إلا إذا أطلقوا النار أولاً."),
    ("أطلقوا سراحه.", "They shot him free.", "أطلقوا سراحه."),
    ("أطلقوا أولاً.", "They released it first.", "أطلقوا أولاً."),  # not about shooting
])
def test_arabic_patterns(ar, en, out):
    assert terms.fix_arabic(ar, en, "") == out


def test_vocative_title_and_names_ending_in_a():
    from tarjim.translate import _reads_female, _vocative_title
    assert _vocative_title("العم، استيقظ.", "Uncle, wake up.", [("Uncle", "العم")]) == "يا عم، استيقظ."
    assert _vocative_title("(العم)، انهض.", "Uncle, get up.", [("Uncle", "العم")]) == "يا عم، انهض."
    assert _vocative_title("العم نائم.", "Uncle is asleep.", [("Uncle", "العم")]) == "العم نائم."
    assert _vocative_title("الذئاب، اسمعوا.", "Wolves, listen.", [("Wolves", "الذئاب")]) == "الذئاب، اسمعوا."
    assert _reads_female("Majima", "ماجيما") and _reads_female("Luca", "لوكا")
    assert not _reads_female("Kiryu", "كيريو") and not _reads_female("Hosea Matthews", "هوزيا ماثيوز")


def test_gender_hamza_and_anywhere():
    from tarjim import gender
    assert gender.masculinize("إدفعي للحماية وإلا سيحرقون متجرك.") == "ادفع للحماية وإلا سيحرقون متجرك."
    assert gender.masculinize("إذا أردت، أذهب معك.") == "إذا أردت، أذهب معك."  # "I go" stays
    assert gender.masculinize("لا تقلق بشأني اعتني بنفسك.") == "لا تقلق بشأني اعتن بنفسك."
    assert gender.feminize("لا تقلقي بشأني، اعتن بنفسك.") == "لا تقلقي بشأني، اعتني بنفسك."


def test_stay_joined_to_and():
    assert terms.fix_arabic("اخفض صوتك وابقى قريباً.", "Keep your voice down and stay close.") == "اخفض صوتك وابق قريباً."
