"""Swahili / English detection by common-word scoring (research R7). No model call."""

import re

SWAHILI = set("""
na ni kwa ya wa za la cha vya kwenye katika hii hizi huu hiyo hilo hapa pale sana tu pia au lakini
kama je gani nini nani wapi lini vipi ngapi kiasi bei nataka ninataka tunataka naomba ningependa
nina una ana tuna mna wana sina hana hakuna ipo kuna yupo nipe niletee nionyeshe onyesha ongeza
weka ondoa futa lipa kulipa kununua nunua nauza unauza mnauza mnasafirisha kusafirisha
usafirishaji kurudisha rudisha mzigo oda agizo kikapu habari asante tafadhali sawa ndiyo ndio hapana
siyo karibu mambo poa shikamoo leo kesho jana sasa bado tayari nyingine hizo hivyo vyote yote zote
chini juu zaidi kidogo kubwa ndogo mpya rangi saizi viatu kiatu nguo shati simu chaja nyekundu
vyekundu nyeusi nyeupe bluu kijani elfu laki shilingi mimi wewe yeye sisi nyinyi wao changu chako
yangu yako langu lako wangu wako hadi mpaka kutoka baada kabla ili kwamba ninaweza unaweza
naweza mnaweza inawezekana
""".split())

ENGLISH = set("""
the a an and or but is are was were be been do does did have has had i you he she we they it my your
our this that these those what which who where when how much many price cost want need would like
please can could will shall should may show me give send find search buy order pay checkout cart
add remove delete deliver delivery shipping return refund to from in on at for with of about under
over less more than size color colour red blue black white green shoes shoe phone phones charger
available stock yes no ok thanks thank hello hi any some one two second first last new
""".split())

_WORD = re.compile(r"[a-zA-Z']+")


def detect_language(text, previous="sw"):
    """Return "sw" or "en". Keeps `previous` when the text gives no clear signal."""
    words = [w.lower().strip("'") for w in _WORD.findall(text or "")]
    sw = sum(1 for w in words if w in SWAHILI)
    en = sum(1 for w in words if w in ENGLISH and w not in SWAHILI)
    if sw + en < 2 or sw == en:
        return previous
    return "sw" if sw > en else "en"
