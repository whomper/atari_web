#!/usr/bin/env python3
"""
Falcon IMAP proxy  (log + optional rewrite of what TROLL sees; default = pass-through)

  TROLL --plain IMAP--> [this proxy :1143] --verified TLS--> imap.mail.me.com:993

Without --rewrite, bytes are forwarded unchanged and immediately; a side-tap
logger records what TROLL asks for and the *shape* of the server's answers.

With --rewrite, whole-message fetches (BODY[] / RFC822) are buffered and every
multipart/* Content-Type header is normalised so that boundary="..." is the ONLY
parameter (TROLL cannot parse a boundary followed by ';' or type=...).  Nothing
else in the message is touched; messages that need no change are forwarded
byte-for-byte; any error falls back to the original bytes.

Privacy: passwords (LOGIN / AUTHENTICATE) and all literal data (message bodies,
APPEND payloads) are never logged.  Logging errors can never break forwarding.
"""
import argparse, asyncio, base64, codecs, itertools, logging, os, quopri, re, ssl, sys, unicodedata
from email.header import Header, decode_header, make_header
from email.utils import formataddr, getaddresses
from html.parser import HTMLParser

VERSION = "v7e hebrew-glyph 2026-10-03"
log = logging.getLogger("imaplog")
sess_ids = itertools.count(1)
LITERAL_RE = re.compile(rb"\{(\d+)\+?\}$")
MAXLINE = 300


LOGIN_RE = re.compile(rb'^\S+ LOGIN (?:"((?:[^"\\]|\\.)*)"|([^\s"]+)) (?:"((?:[^"\\]|\\.)*)"|([^\s"]+))$', re.I)


def login_shape(line):
    """Describe a LOGIN command WITHOUT revealing username or password."""
    m = LOGIN_RE.match(line)
    if not m:
        return b"(shape: could not parse - may use literals)"
    user = m.group(1) if m.group(1) is not None else m.group(2)
    pw = m.group(3) if m.group(3) is not None else m.group(4)
    return (b"(shape: user_len=%d user_has_at=%s user_has_space=%s "
            b"pass_len=%d pass_has_dash=%s pass_has_space=%s)" % (
                len(user), str(b"@" in user).encode(), str(b" " in user).encode(),
                len(pw), str(b"-" in pw).encode(), str(b" " in pw).encode()))


# ---------------------------------------------------------------- rewrite engine
# Everything below only changes what is SENT TO the Falcon.  The message stored
# in iCloud is never modified.
CT_RE = re.compile(rb"(?im)^Content-Type:[ \t]*((?:[^\r\n]*)(?:\r\n[ \t][^\r\n]*)*)")
MAX_REWRITE = 30 * 1024 * 1024

# ---- Hebrew -> Latin, letter for letter.  Edit this table to taste.
HEB_MAP = {
    "\\u05D0": "a",  "\\u05D1": "b",  "\\u05D2": "g",  "\\u05D3": "d",  "\\u05D4": "h",
    "\\u05D5": "v",  "\\u05D6": "z",  "\\u05D7": "ch", "\\u05D8": "t",  "\\u05D9": "y",
    "\\u05DB": "k",  "\\u05DA": "k",  "\\u05DC": "l",  "\\u05DE": "m",  "\\u05DD": "m",
    "\\u05E0": "n",  "\\u05DF": "n",  "\\u05E1": "s",  "\\u05E2": "e",  "\\u05E4": "p",
    "\\u05E3": "p",  "\\u05E6": "ts", "\\u05E5": "ts", "\\u05E7": "q",  "\\u05E8": "r",
    "\\u05E9": "sh", "\\u05EA": "t",
    "\\u05F0": "vv", "\\u05F1": "vy", "\\u05F2": "yy",          # Yiddish ligatures
    "\\u05BE": "-",  "\\u05C0": "|",  "\\u05C3": ":",  "\\u05F3": "'",  "\\u05F4": '"',
}
HEB_RE = re.compile("[\\u0590-\\u05FF\\uFB1D-\\uFB4F]")
HEB_PRES_RE = re.compile("[\\uFB1D-\\uFB4F]")
BIDI_RE = re.compile("[\\u200e\\u200f\\u202a-\\u202e\\u2066-\\u2069]")


# ---- Hebrew -> Latin, phonetic ("Shalom Olam") ---------------------------------
# Unpointed Hebrew has no vowels, so this is: (1) a built-in word list for common
# words and names, (2) prefix handling (ha-, ve-, be-, le-, me-, ke-, she-), and
# (3) rules that guess vowels for words not in the list.  Add or fix words in the
# optional file given with --hebrew-words (one "hebrew-word latin-word" per line).
DEFAULT_WORDS = """
# greetings and courtesy
שלום shalom
היי hi
הי hi
בוקר boker
טוב tov
טובה tova
טובים tovim
ערב erev
לילה layla
תודה toda
רבה raba
בבקשה bevakasha
סליחה slicha
להתראות lehitraot
ברכה bracha
ברכות brachot
בברכה beveracha
מזל mazal
חג chag
שמח sameach
שמחה smecha
שבת Shabbat
כן ken
לא lo
אולי ulai
בסדר beseder
סבבה sababa
ביי bye
אוקיי okay
# pronouns
אני ani
אתה ata
את at
הוא hu
היא hi
אנחנו anachnu
אנו anu
אתם atem
אתן aten
הם hem
הן hen
אותי oti
אותך otcha
אותו oto
אותה ota
אותנו otanu
לי li
לך lecha
לו lo
לה la
לנו lanu
לכם lachem
להם lahem
שלי sheli
שלך shelcha
שלו shelo
שלה shela
שלנו shelanu
שלכם shelachem
שלהם shelahem
שלומך shlomcha
# question words
מה ma
מי mi
איפה eifo
מתי matai
למה lama
איך eich
כמה kama
איזה eize
איזו eizo
מדוע madua
האם haim
# small words
של shel
עם im
על al
אל el
מן min
כי ki
אם im
או o
אבל aval
גם gam
רק rak
עוד od
כבר kvar
עכשיו achshav
היום hayom
מחר machar
אתמול etmol
מחרתיים macharatayim
בקרוב bekarov
תמיד tamid
כל kol
כולם kulam
הכל hakol
משהו mashehu
מישהו mishehu
אין ein
יש yesh
היה haya
יהיה yihye
להיות lihyot
זה ze
זאת zot
אלה ele
זו zo
פה po
שם sham
כאן kan
בין bein
לפני lifnei
אחרי acharei
ליד leyad
בלי bli
בשביל bishvil
לגבי legabei
כמו kmo
כדי kdei
# numbers
אחד echad
אחת achat
שניים shnayim
שתיים shtayim
שלושה shlosha
שלוש shalosh
ארבעה arbaa
ארבע arba
חמישה chamisha
חמש chamesh
שישה shisha
שש shesh
שבעה shiva
שבע sheva
שמונה shmone
תשעה tisha
תשע tesha
עשרה asara
עשר eser
מאה mea
אלף elef
# time
יום yom
ימים yamim
שבוע shavua
חודש chodesh
שנה shana
שנים shanim
שעה shaa
דקה daka
דקות dakot
שנייה shniya
צהריים tzohorayim
צוהריים tzohorayim
ראשון rishon
שני sheni
שלישי shlishi
רביעי revii
חמישי chamishi
שישי shishi
ינואר Yanuar
פברואר Februar
מרץ Merts
אפריל April
מאי May
יוני Yuni
יולי Yuli
אוגוסט Ogust
ספטמבר September
אוקטובר October
נובמבר November
דצמבר December
# mail, work, daily life
מייל mail
אימייל email
הודעה hodaa
הודעות hodaot
מצורף mitzoraf
מצורפת mitzorefet
קובץ kovetz
קבצים kvatzim
מסמך mismach
מסמכים mismachim
פגישה pgisha
פגישות pgishot
שיחה sicha
טלפון telefon
נייד nayad
כתובת ktovet
שם shem
נושא nose
שאלה sheela
שאלות sheelot
תשובה tshuva
בקשה bakasha
הצעה hatzaa
חשבונית cheshbonit
תשלום tashlum
הזמנה hazmana
משלוח mishloach
מחיר mechir
הנחה hanacha
עבודה avoda
פרויקט proyekt
לקוח lakoach
לקוחות lekochot
חברה chevra
בית bayit
משרד misrad
רחוב rechov
עיר ir
מדינה medina
ארץ eretz
עולם olam
בדיקה bdika
בדיקות bdikot
ביטוח bituach
ביטוחים bituchim
בריאות briut
רופא rofe
רופאה rofa
חולים cholim
מכתב michtav
מכתבים michtavim
דואר doar
אתר atar
סיסמה sisma
חשבון cheshbon
בנק bank
כרטיס kartis
אשראי ashrai
תור tor
זמן zman
תאריך taarich
מקום makom
מספר mispar
פרטים pratim
מידע meida
עדכון idkun
אישור ishur
בעיה baaya
פתרון pitaron
עזרה ezra
תמיכה tmicha
שירות sherut
מוצר mutzar
מוצרים mutzarim
מכירה mechira
חדשות chadashot
חדש chadash
חדשה chadasha
ישן yashan
# verbs and adjectives
אפשר efshar
צריך tzarich
צריכה tzricha
רוצה rotze
רוצים rotzim
יכול yachol
יכולה yechola
אשמח esmach
מצטער mitztaer
מצטערת mitztaeret
תשלח tishlach
שלח shalach
שלחתי shalachti
שלחנו shalachnu
קיבלתי kibalti
קיבלנו kibalnu
לאשר leasher
לבדוק livdok
בדקתי badakti
מצאתי matzati
יודע yodea
יודעת yodaat
הבנתי hevanti
חשוב chashuv
דחוף dachuf
גדול gadol
קטן katan
יפה yafe
רע ra
מאוד meod
מעולה meula
נהדר nehedar
נפלא nifla
מצוין metzuyan
אחלה achla
# family
אבא aba
אמא ima
אח ach
אחות achot
בן ben
בת bat
ילד yeled
ילדה yalda
ילדים yeladim
משפחה mishpacha
חבר chaver
חברים chaverim
הורים horim
סבא saba
סבתא savta
# names and places
דוד David
משה Moshe
יוסי Yossi
יוסף Yosef
אברהם Avraham
יצחק Yitzchak
יעקב Yaakov
דניאל Daniel
דניאלה Daniela
מיכל Michal
רונית Ronit
שרה Sarah
רחל Rachel
לאה Leah
דנה Dana
נועה Noa
אורי Uri
גיל Gil
עמית Amit
רן Ran
אבי Avi
אריאל Ariel
מאיה Maya
תמר Tamar
ענת Anat
עידו Ido
ארז Erez
כהן Cohen
לוי Levi
ישראלי Israeli
ישראל Israel
ירושלים Yerushalayim
תל Tel
אביב Aviv
חיפה Haifa
אילת Eilat
באר Beer
ברלין Berlin
גרמניה Germania
אמריקה America
לונדון London
פריז Paris
יוון Yavan
נועם Noam
איתי Itai
עומר Omer
יובל Yuval
שיר Shir
טל Tal
גלית Galit
מירי Miri
יעל Yael
הילה Hila
שירה Shira
עדי Adi
ליאור Lior
רועי Roi
אלון Alon
גיא Guy
דור Dor
מור Mor
ניר Nir
שי Shai
אסף Asaf
יונתן Yonatan
אמיר Amir
אילן Ilan
אלי Eli
שמעון Shimon
בנימין Binyamin
מנחם Menachem
אפרת Efrat
ורד Vered
סיגל Sigal
אורית Orit
אסתר Ester
נעמי Naomi
מרים Miriam
חנה Hana
רבקה Rivka
שושנה Shoshana
מאיר Meir
חיים Chaim
אהרון Aharon
שלמה Shlomo
אליהו Eliyahu
זאב Zeev
אריה Arie
# acronyms (written with a gershayim, which is ignored when matching)
צהל Tzahal
בעמ beam
חשבונית cheshbonit
"""

_HL = "\\u05D0-\\u05EA\\u05F0-\\u05F2\\uFB1D-\\uFB4F"
_MK = "\\u0591-\\u05C7"
_GER = "\\u05D2\\u05D6\\u05E6\\u05EA\\u05D7\\u05D3\\u05D8"
HEB_TOKEN_RE = re.compile(
    "(?:[" + _HL + _MK + "]|(?<=[" + _GER + "])\\u05F3|(?<=[" + _GER + "])'(?=[" + _HL + "]))+"
    "(?:[\\u05F4\\"][" + _HL + "](?:[" + _HL + _MK + "]|(?<=[" + _GER + "])\\u05F3)*)*")
_STRIP_RE = re.compile("[" + _MK + "\\u05F3\\u05F4'\\"]")
_FINAL_FORM = {"\\u05DA": "\\u05DB", "\\u05DD": "\\u05DE", "\\u05DF": "\\u05E0",
               "\\u05E3": "\\u05E4", "\\u05E5": "\\u05E6"}
_CONS = {"\\u05D1": "b", "\\u05D2": "g", "\\u05D3": "d", "\\u05D4": "h", "\\u05D6": "z",
         "\\u05D7": "ch", "\\u05D8": "t", "\\u05DB": "kh", "\\u05DC": "l", "\\u05DE": "m",
         "\\u05E0": "n", "\\u05E1": "s", "\\u05E4": "f", "\\u05E6": "tz", "\\u05E7": "k",
         "\\u05E8": "r", "\\u05E9": "sh", "\\u05EA": "t"}
_GERESH_CONS = {"\\u05D2": "j", "\\u05D6": "zh", "\\u05E6": "ch", "\\u05EA": "th",
                "\\u05D7": "kh", "\\u05D3": "dh", "\\u05D8": "t"}
_PREFIX = {"\\u05D5": "ve", "\\u05D4": "ha", "\\u05D1": "be", "\\u05DC": "le",
           "\\u05DE": "me", "\\u05DB": "ke", "\\u05E9": "she"}

HEB_WORDS = {}
HEB_MODE = "phonetic"          # or "literal"


def _norm_key(w):
    return _STRIP_RE.sub("", w)


def load_hebrew_words(path=None):
    words = {}
    sources = [DEFAULT_WORDS]
    if path:
        try:
            with open(path, encoding="utf-8") as f:
                sources.append(f.read())
        except OSError as e:
            log.warning("hebrew words file %s not read: %s", path, e)
    for src in sources:
        for line in src.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(None, 1)
            if len(parts) == 2:
                words[_norm_key(parts[0])] = parts[1].strip()
    return words


HEB_WORDS = load_hebrew_words()


def _phonetic_word(tok):
    """Guess pronunciation of one unpointed Hebrew word (no dictionary)."""
    letters, i = [], 0
    while i < len(tok):
        ch = tok[i]
        if ch in "\\u05F3'\\"\\u05F4" or "\\u0591" <= ch <= "\\u05C7":
            i += 1
            continue
        ger = i + 1 < len(tok) and tok[i + 1] in "\\u05F3'" and ch in _GERESH_CONS
        letters.append((_FINAL_FORM.get(ch, ch), ch in _FINAL_FORM, ger))
        i += 2 if ger else 1
    n, units, k = len(letters), [], 0           # unit: [kind, text, strength]
    while k < n:
        base, final, ger = letters[k]
        last = k == n - 1
        nxt = letters[k + 1][0] if k + 1 < n else None
        prev = units[-1] if units else None
        prev_real_v = prev is not None and prev[0] == "V" and prev[2] == "real"
        prev_carrier = prev is not None and prev[0] == "V" and prev[2] == "carrier"
        if ger:
            units.append(["C", _GERESH_CONS[base], ""])
        elif base == "\\u05D5":                                   # vav
            if nxt == "\\u05D5":
                units.append(["C", "v", ""]); k += 1
            elif k == 0 or prev_real_v:
                units.append(["C", "v", ""])
            else:
                units.append(["V", "o", "real"])
        elif base == "\\u05D9":                                   # yod
            if nxt == "\\u05D9":
                units.append(["C", "y", ""]); k += 1
            elif k == 0 or prev_real_v:
                units.append(["C", "y", ""])
            else:
                units.append(["V", "i", "real"])
        elif base in "\\u05D0\\u05E2":                             # alef / ayin
            units.append(["V", "a", "carrier"])
        elif base == "\\u05D4" and last and k > 0:                # final he
            units.append(["V", "a", "weak"])
        elif base == "\\u05D1":
            units.append(["C", "v" if (last and k > 0) else "b", ""])
        elif base == "\\u05DB":
            units.append(["C", "kh" if (final or k > 0) else "k", ""])
        elif base == "\\u05E4":
            units.append(["C", "f" if (final or k > 0) else "p", ""])
        else:
            units.append(["C", _CONS.get(base, "?"), ""])
        k += 1
    merged = []                                                   # collapse vowel pairs
    for u in units:
        if u[0] == "V" and merged and merged[-1][0] == "V":
            if merged[-1][2] != "real" and u[2] == "real":
                merged[-1] = u
            continue
        merged.append(u)
    units, m = merged, len(merged)
    has_v = any(u[0] == "V" for u in units)
    ins, j = {}, 0
    while j < m:                                                  # guess missing vowels
        if units[j][0] != "C":
            j += 1
            continue
        s = j
        while j < m and units[j][0] == "C":
            j += 1
        e, L = j, j - s
        if not has_v:
            if L == 2:
                ins[s + 1] = "a"
            elif L == 3:
                ins[s + 1] = "e"; ins[s + 2] = "e"
            elif L >= 4:
                ins[s + 1] = "a"; ins[e - 1] = "e"
        elif s == 0 and L >= 2:
            ins[s + 1] = "a"
        elif e == m and s > 0 and L >= 2:
            ins[s + 1] = "e"
        elif s > 0 and e < m and L >= 3:
            ins[s + 1] = "e"
    return "".join(ins.get(p, "") + units[p][1] for p in range(m))


def hebrew_word_to_latin(tok, words):
    key = _norm_key(tok)
    if key in words:
        return words[key]
    for plen in (1, 2):                                           # prefix + known word (shortest first)
        if len(key) >= plen + 2:
            p, rest = key[:plen], key[plen:]
            if all(c in _PREFIX for c in p) and rest in words:
                syl = ""
                for idx, c in enumerate(p):
                    s = _PREFIX[c]
                    if c == "\\u05D5" and idx == 0 and rest[0] in "\\u05D1\\u05DE\\u05E4\\u05D5":
                        s = "u"
                    syl += s
                tail = words[rest]
                return syl + ("-" if tail[:1].isupper() else "") + tail
    return _phonetic_word(tok)


def translit_hebrew_literal(s):
    """Letter-for-letter Hebrew -> ASCII (old behaviour; --literal-hebrew)."""
    s = HEB_PRES_RE.sub(lambda m: unicodedata.normalize("NFKD", m.group(0)), s)
    out = []
    for ch in s:
        if ch in HEB_MAP:
            out.append(HEB_MAP[ch])
        elif "\\u0591" <= ch <= "\\u05C7":
            continue
        elif BIDI_RE.match(ch):
            continue
        else:
            out.append(ch)
    return "".join(out)


def translit_hebrew(s, capitalize_all=False):
    """Hebrew -> Latin.  Phonetic by default ('Shalom olam'); see HEB_MODE."""
    if HEB_MODE == "literal":
        return translit_hebrew_literal(s)
    s = HEB_PRES_RE.sub(lambda m: unicodedata.normalize("NFKD", m.group(0)), s)
    out, pos = [], 0
    for m in HEB_TOKEN_RE.finditer(s):
        out.append(s[pos:m.start()])
        lat = hebrew_word_to_latin(m.group(0), HEB_WORDS)
        j = m.start() - 1
        while j >= 0 and s[j] in " \t":
            j -= 1
        if lat and lat[0].islower() and (capitalize_all or j < 0 or s[j] in "\n\r.!?:"):
            lat = lat[0].upper() + lat[1:]
        out.append(lat)
        pos = m.end()
    out.append(s[pos:])
    return translit_hebrew_literal("".join(out))      # leftover marks / stray letters



# ---- Hebrew as real glyphs on the Atari (--hebrew-mode glyph) --------------------
# The Atari ST character set has the Hebrew letters at 0xC2-0xDC (table taken from
# the Claude ST bridge, atari_text.py).  TOS has no right-to-left support, so the
# text is also put into VISUAL order here: Hebrew runs reversed, numbers and Latin
# words kept left-to-right, brackets mirrored, long lines wrapped.
_ST_HIGH = ("ÇüéâäàåçêëèïîìÄÅ"
            "ÉæÆôöòûùÿÖÜ¢£¥ßƒ"
            "áíóúñÑªº¿⌐¬½¼¡«»"
            "ãõØøœŒÀÃÕ¨´†¶©®™"
            "ĳĲאבגדהוזחטיכלמנ"
            "סעפצקרשתןךםףץ§∧∞"
            "αβΓπΣσµτΦΘΩδ∮ϕ∈∩"
            "≡±≥≤⌠⌡÷≈°∙·√ⁿ²³¯")
assert len(_ST_HIGH) == 128
ST_TO = {ch: 0x80 + i for i, ch in enumerate(_ST_HIGH)}
HEB_PUNCT = {"\\u05BE": "-", "\\u05F3": "'", "\\u05F4": '"', "\\u05C0": "|", "\\u05C3": ":"}
MIRROR = {"(": ")", ")": "(", "[": "]", "]": "[", "{": "}", "}": "{", "<": ">", ">": "<",
          "\\u00AB": "\\u00BB", "\\u00BB": "\\u00AB"}
GLYPH = {"label": "x-atari-st", "cte": "8bit", "width": 60, "subject": "encoded-q",
         "subject_label": None}


def to_atari_bytes(text):
    out = bytearray()
    for ch in text:
        o = ord(ch)
        ch = HEB_PUNCT.get(ch, ch)
        if ch in ("\r", "\n"):
            out.append(ord(ch))
        elif o == 9:
            out += b"    "
        elif 32 <= ord(ch[0]) < 127 and len(ch) == 1:
            out.append(ord(ch))
        elif ch in ST_TO:
            out.append(ST_TO[ch])
        elif ch == "\\u20AC":
            out += b"EUR"
        elif ch == "\\u00D7":
            out += b"x"
        elif len(ch) == 1 and unicodedata.combining(ch):
            continue                                         # niqqud, accents
        else:
            base = [b for b in unicodedata.normalize("NFKD", ch) if not unicodedata.combining(b)]
            if base and all(32 <= ord(b) < 127 or b in ST_TO for b in base):
                for b in base:
                    out.append(ST_TO[b] if b in ST_TO else ord(b))
            elif unicodedata.category(ch[0]).startswith("S"):
                continue                                     # emoji, pictographs
            else:
                out.append(63)
    return bytes(out)


def _bidi_class(ch):
    c = unicodedata.bidirectional(ch)
    if c in ("R", "AL"):
        return "R"
    if c in ("L", "EN", "AN"):
        return "L"                                           # numbers read left-to-right
    return "N"


def bidi_base(text):
    for ch in text:
        c = unicodedata.bidirectional(ch)
        if c in ("R", "AL"):
            return "R"
        if c == "L":
            return "L"
    return "L"


def bidi_visual(line, base):
    """One line, logical -> visual order (simplified UAX #9)."""
    cls = [_bidi_class(c) for c in line]
    n, res, i = len(line), cls[:], 0
    while i < n:
        if cls[i] != "N":
            i += 1
            continue
        j = i
        while j < n and cls[j] == "N":
            j += 1
        left = cls[i - 1] if i > 0 else base
        right = cls[j] if j < n else base
        d = left if left == right else base
        for k in range(i, j):
            res[k] = d
        i = j
    runs = []
    for ch, d in zip(line, res):
        if runs and runs[-1][0] == d:
            runs[-1][1].append(ch)
        else:
            runs.append((d, [ch]))
    out = []
    for d, chars in runs:
        s = "".join(chars)
        if d == "R":
            s = "".join(MIRROR.get(c, c) for c in reversed(s))
        out.append(s)
    if base == "R":
        out.reverse()
    return "".join(out)


def _wrap_line(line, width):
    if len(line) <= width:
        return [line]
    lead = len(line) - len(line.lstrip())
    words, cur, rows = line.split(), "", []
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            rows.append(cur)
            cur = w
        else:
            cur = (cur + " " + w) if cur else w
    if cur:
        rows.append(cur)
    return [(" " * lead if k == 0 else "") + r for k, r in enumerate(rows)] or [line]


def hebrew_visual_text(text, width=60):
    """Whole text body -> visual order for a left-to-right-only display."""
    lines, out, para = text.split("\n"), [], []

    def flush():
        base = bidi_base("\n".join(para))
        for ln in para:
            if HEB_RE.search(ln):
                for piece in _wrap_line(ln, width):
                    out.append(bidi_visual(piece, base))
            else:
                out.extend(_wrap_line(ln, 200))
        para.clear()
    for ln in lines:
        if ln.strip():
            para.append(ln)
        else:
            flush()
            out.append(ln)
    flush()
    return "\n".join(out)


def _encoded_words(raw, label, enc="B"):
    """RFC 2047 encoded-word(s) for raw bytes in an arbitrary charset label."""
    if enc == "Q":
        words = []
        for i in range(0, max(len(raw), 1), 14):
            q = "".join(chr(b) if (48 <= b <= 57 or 65 <= b <= 90 or 97 <= b <= 122)
                        else "_" if b == 32 else "=%02X" % b for b in raw[i:i + 14])
            words.append("=?%s?Q?%s?=" % (label, q))
        return " ".join(words).encode("ascii")
    words = [base64.b64encode(raw[i:i + 30]).decode() for i in range(0, max(len(raw), 1), 30)]
    return " ".join("=?%s?B?%s?=" % (label, w) for w in words).encode("ascii")


def glyph_header_value(text, address=False):
    """Header text containing Hebrew -> bytes for the header line (Atari encoding)."""
    vis = bidi_visual(text, bidi_base(text))
    raw = to_atari_bytes(vis)
    if GLYPH["subject"] == "raw":
        return raw
    return _encoded_words(raw, GLYPH["subject_label"] or GLYPH["label"],
                          "Q" if GLYPH["subject"] == "encoded-q" else "B")


def qp_encode(raw):
    """Quoted-printable with CRLF line ends and proper CRLF soft line breaks (<=75 chars)."""
    out = []
    for l in raw.split(b"\r\n"):
        toks = []
        for i, b in enumerate(l):
            if 33 <= b <= 126 and b != 61:
                toks.append(chr(b))
            elif b in (32, 9) and i < len(l) - 1:
                toks.append(chr(b))
            else:
                toks.append("=%02X" % b)
        cur, segs = "", []
        for t in toks:
            if len(cur) + len(t) > 75:
                segs.append(cur + "=")
                cur = t
            else:
                cur += t
        segs.append(cur)
        out.append("\r\n".join(segs))
    return "\r\n".join(out).encode("ascii")


def _build_glyph_part(headers, text, top, marker=None):
    text = BIDI_RE.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))
    if marker:
        text = marker + "\n\n" + text
    vis = hebrew_visual_text(text.strip("\n"), GLYPH["width"])
    raw = to_atari_bytes(vis.replace("\n", "\r\n"))
    cte = GLYPH["cte"]
    if cte == "base64":
        b64 = base64.b64encode(raw).decode()
        body = "\r\n".join(b64[i:i + 76] for i in range(0, len(b64), 76)).encode()
    elif cte == "quoted-printable":
        body = qp_encode(raw)
    else:
        cte, body = "8bit", raw
    if top:
        body += b"\r\n"
    base = drop_headers(headers, {b"content-type", b"content-transfer-encoding", b"content-length"})
    label = GLYPH["label"]
    new_h = (b"Content-Type: text/plain" + (b'; charset="' + label.encode() + b'"' if label else b"") +
             b"\r\nContent-Transfer-Encoding: " + cte.encode())
    if base.strip():
        new_h = base + b"\r\n" + new_h
    return new_h + b"\r\n\r\n" + body



class Ctx:
    def __init__(self, strip_html=True, translit=True, clean=True):
        self.strip_html, self.translit, self.clean = strip_html, translit, clean
        self.stats = {"ct": 0, "html_dropped": 0, "html_converted": 0,
                      "heb_parts": 0, "heb_headers": 0, "text_cleaned": 0}

    def summary(self):
        return ", ".join("%s=%d" % kv for kv in self.stats.items() if kv[1])



# ---- Atari-safe text: remove invisible / unsupported characters ---------------
PUNCT_MAP = {
    "\\u2018": "'", "\\u2019": "'", "\\u201A": "'", "\\u201B": "'", "\\u2032": "'",
    "\\u201C": '"', "\\u201D": '"', "\\u201E": '"', "\\u201F": '"', "\\u2033": '"',
    "\\u2013": "-", "\\u2212": "-", "\\u2010": "-", "\\u2011": "-", "\\u2012": "-",
    "\\u2014": "--", "\\u2015": "--", "\\u2026": "...",
    "\\u2022": "*", "\\u2023": "*", "\\u25E6": "*", "\\u25AA": "*", "\\u25CF": "*",
    "\\u2039": "<", "\\u203A": ">", "\\u2044": "/", "\\u2122": "(TM)", "\\u20AA": "NIS",
    "\\u2192": "->", "\\u2190": "<-", "\\u2028": "\n", "\\u2029": "\n",
}
LATIN_MAP = {"\\u0141": "L", "\\u0142": "l", "\\u0110": "D", "\\u0111": "d", "\\u0131": "i",
             "\\u0152": "OE", "\\u0153": "oe", "\\u0126": "H", "\\u0127": "h", "\\u0166": "T",
             "\\u0167": "t", "\\u1E9E": "SS"}
SPACE_RE = re.compile("[\\u00A0\\u1680\\u2000-\\u200A\\u202F\\u205F\\u3000]")
# zero-width / formatting characters and the "combining grapheme joiner" padding
INVISIBLE_RE = re.compile("[\\u00AD\\u034F\\u061C\\u180E\\u200B-\\u200F\\u202A-\\u202E"
                          "\\u2060-\\u2064\\u2066-\\u206F\\uFE00-\\uFE0F\\uFEFF\\U000E0000-\\U000E007F]")


def _clean_line(l):
    t = INVISIBLE_RE.sub("", SPACE_RE.sub(" ", l))
    out = []
    for ch in t:
        o = ord(ch)
        if o < 0x100 or ch == "\\u20AC":
            out.append(ch)
        elif ch in PUNCT_MAP:
            out.append(PUNCT_MAP[ch])
        elif ch in LATIN_MAP:
            out.append(LATIN_MAP[ch])
        elif unicodedata.category(ch) in ("So", "Sk", "Cs", "Co", "Cn"):
            continue                                   # emoji, symbols, dingbats
        elif o < 0x250 or 0x1E00 <= o < 0x1F00:      # Latin Extended: drop accents
            base = "".join(c for c in unicodedata.normalize("NFKD", ch)
                           if not unicodedata.combining(c))
            out.append(base if base and base.isascii() else ch)
        else:
            out.append(ch)
    t = "".join(out)
    if t == l:
        return l                                       # untouched line: keep exactly
    if t != l:                                         # tidy only lines we changed
        t = re.sub(r"(?<=\S) {2,}", " ", t)
        t = re.sub(r"([\[(]) +", r"\1", t)
        t = re.sub(r" +([\])])", r"\1", t) if "[" in t or "(" in t else t
        if not l.startswith(" "):
            t = t.lstrip()
    return t.rstrip()


def clean_text(s, tidy=False):
    """Make text safe for the Falcon: no invisible characters, typographic
    punctuation as ASCII, emoji/pictographs removed.  Latin-1 letters (a-umlaut,
    sharp-s, ...) and the euro sign are kept; other scripts are left alone.
    tidy=True (converted HTML only) also drops adjacent duplicate lines."""
    s = s.replace("\\u2028", "\n").replace("\\u2029", "\n")
    res, last = [], None
    for l in s.split("\n"):
        c = _clean_line(l)
        if tidy and c.strip() and c == last:
            continue
        res.append(c)
        if c.strip():
            last = c
    return "\n".join(res)


# ---- Content-Type normalisation -------------------------------------------------
def _split_semicolons(v):
    out, cur, q = [], "", False
    for ch in v:
        if ch == '"':
            q = not q
        if ch == ";" and not q:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    out.append(cur.strip())
    return out


def canonical_multipart(value):
    """value: unfolded Content-Type value (str).  Returns (new_value_or_None,
    boundary_or_None).  new_value is None when the header is not multipart, has no
    usable boundary, or is already acceptable (boundary is the only parameter)."""
    toks = _split_semicolons(value)
    mtype = toks[0]
    if not mtype.lower().startswith("multipart/"):
        return None, None
    params = toks[1:]
    trailing = bool(params) and params[-1] == ""
    named = []
    for p in params:
        if p:
            k, _, v = p.partition("=")
            named.append((k.strip().lower(), v.strip()))
    bs = [v for k, v in named if k == "boundary"]
    if not bs:
        return None, None
    b = bs[0]
    if len(b) >= 2 and b[0] == '"' and b[-1] == '"':
        b = b[1:-1]
    if not b or '"' in b:
        return None, None
    if len(named) == 1 and not trailing:
        return None, b
    return '%s; boundary="%s"' % (mtype, b), b


# ---- header helpers --------------------------------------------------------------
def _logical_headers(hbytes):
    out = []
    for ln in hbytes.split(b"\r\n"):
        if ln[:1] in (b" ", b"\t") and out:
            out[-1] += b"\r\n" + ln
        else:
            out.append(ln)
    return out


def _hname(chunk):
    return chunk.split(b":", 1)[0].strip().lower()


def header_value(hbytes, name):
    """Unfolded value of header `name` (bytes, lower-case) or None."""
    for ch in _logical_headers(hbytes):
        if _hname(ch) == name and b":" in ch:
            return re.sub(rb"\r\n[ \t]+", b" ", ch.split(b":", 1)[1]).strip().decode("latin-1")
    return None


def drop_headers(hbytes, names):
    keep = [c for c in _logical_headers(hbytes) if _hname(c) not in names]
    return b"\r\n".join(keep)


def _decode_hdr(raw):
    try:
        s = raw.decode("ascii")
    except UnicodeDecodeError:
        return raw.decode("utf-8", "replace")
    try:
        return str(make_header(decode_header(s)))
    except Exception:
        return s


def _encode_hdr(text):
    text = re.sub(r"\s+", " ", text).strip()
    try:
        text.encode("ascii")
        if len(text) < 900:
            return text.encode("ascii")
    except UnicodeEncodeError:
        pass
    return Header(text, "utf-8", maxlinelen=60).encode(linesep="\r\n").encode("ascii")


ADDR_HEADERS = (b"from", b"to", b"cc", b"reply-to", b"sender")


def _fix_one_header(name, raw):
    glyph = HEB_MODE == "glyph" and GLYPH["subject"] != "phonetic"
    if name == b"subject":
        text = _decode_hdr(raw)
        if not HEB_RE.search(text):
            return None
        return glyph_header_value(clean_text(text)) if glyph else _encode_hdr(translit_hebrew(text))
    pairs = getaddresses([raw.decode("latin-1")])
    names = [_decode_hdr(n.encode("latin-1")) if n else "" for n, _ in pairs]
    if not any(HEB_RE.search(n) for n in names):
        return None
    if glyph:
        parts = []
        for n, (_, a) in zip(names, pairs):
            if n and HEB_RE.search(n):
                parts.append(glyph_header_value(clean_text(n)) + b" <" + a.encode("ascii", "replace") + b">")
            else:
                parts.append(formataddr((n, a)).encode("ascii", "replace"))
        return b", ".join(parts)
    fixed = [formataddr((translit_hebrew(n, capitalize_all=True), a)) for n, (_, a) in zip(names, pairs)]
    return ", ".join(fixed).encode("ascii", "replace")


def fix_hebrew_headers(hbytes, ctx):
    chunks, changed = _logical_headers(hbytes), False
    for i, ch in enumerate(chunks):
        name = _hname(ch)
        if (name != b"subject" and name not in ADDR_HEADERS) or b":" not in ch:
            continue
        raw = re.sub(rb"\r\n[ \t]+", b" ", ch.split(b":", 1)[1]).strip()
        try:
            new = _fix_one_header(name, raw)
        except Exception:
            new = None
        if new is not None:
            chunks[i] = ch.split(b":", 1)[0] + b": " + new
            changed = True
            ctx.stats["heb_headers"] += 1
    return b"\r\n".join(chunks) if changed else hbytes


def fix_ct_header(hbytes, ctx):
    """Normalise a multipart Content-Type in a header block.
    Returns (headers, boundary_or_None)."""
    m = CT_RE.search(hbytes)
    if not m:
        return hbytes, None
    value = re.sub(r"\r\n[ \t]+", " ", m.group(1).decode("latin-1")).strip()
    new, boundary = canonical_multipart(value)
    if new is not None:
        hbytes = (hbytes[:m.start()] + b"Content-Type: " + new.encode("latin-1") +
                  hbytes[m.end():])
        ctx.stats["ct"] += 1
    return hbytes, boundary


# ---- text decoding / building ---------------------------------------------------
def _known_charset(headers):
    """False when the part names a charset Python cannot decode (for example our own
    x-atari-st): such parts are already in someone's final encoding and must be left alone."""
    ct = header_value(headers, b"content-type") or ""
    m = re.search(r'charset\s*=\s*"?([^";\s]+)', ct, re.I)
    if not m:
        return True
    cs = m.group(1).lower()
    if cs.startswith("iso-8859-8"):
        cs = "iso-8859-8"
    try:
        codecs.lookup(cs)
        return True
    except LookupError:
        return False


def _decode_text(headers, body):
    cte = (header_value(headers, b"content-transfer-encoding") or "7bit").lower()
    if cte == "base64":
        b = re.sub(rb"[^A-Za-z0-9+/]", b"", body)
        raw = base64.b64decode(b + b"=" * (-len(b) % 4))
    elif cte in ("quoted-printable", "qp"):
        raw = quopri.decodestring(body)
    else:
        raw = body
    ct = header_value(headers, b"content-type") or ""
    m = re.search(r'charset\s*=\s*"?([^";\s]+)', ct, re.I)
    cs = (m.group(1).lower() if m else "utf-8")
    if cs.startswith("iso-8859-8"):
        cs = "iso-8859-8"
    for enc in (cs, "utf-8", "latin-1"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("latin-1", "replace")


def _build_text_part(headers, text, top, marker=None):
    text = BIDI_RE.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))
    if marker:
        text = marker + "\n\n" + text
    text = text.strip("\n")
    lines = text.split("\n")
    try:
        text.encode("ascii")
        ascii_ok = max(len(l) for l in lines) < 900
    except UnicodeEncodeError:
        ascii_ok = False
    if ascii_ok:
        cs, cte = "us-ascii", "7bit"
        body = "\r\n".join(lines).encode("ascii")
    else:
        cs, cte = "utf-8", "base64"
        b64 = base64.b64encode("\r\n".join(lines).encode("utf-8")).decode()
        body = "\r\n".join(b64[i:i + 76] for i in range(0, len(b64), 76)).encode()
    if top:
        body += b"\r\n"
    base = drop_headers(headers, {b"content-type", b"content-transfer-encoding",
                                  b"content-length"})
    new_h = (b"Content-Type: text/plain; charset=\"" + cs.encode() + b"\"\r\n"
             b"Content-Transfer-Encoding: " + cte.encode())
    if base.strip():
        new_h = base + b"\r\n" + new_h
    return new_h + b"\r\n\r\n" + body


# ---- HTML -> text ------------------------------------------------------------------
class _H2T(HTMLParser):
    BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table",
             "ul", "ol", "blockquote", "pre", "hr", "section", "article", "header",
             "footer", "dl", "dt", "dd"}
    SKIP = {"script", "style", "head", "title"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif self.skip:
            return
        elif tag == "li":
            self.out.append("\n* ")
        elif tag in self.BLOCK:
            self.out.append("\n")
        elif tag in ("td", "th"):
            self.out.append(" ")
        elif tag == "img":
            alt = (dict(attrs).get("alt") or "").strip()
            if alt:
                self.out.append("[" + alt + "]")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif not self.skip and tag in self.BLOCK and tag != "br":
            self.out.append("\n")

    def handle_data(self, d):
        if not self.skip:
            self.out.append(d)


def html_to_text(h):
    p = _H2T()
    p.feed(h)
    p.close()
    t = "".join(p.out).replace("\xa0", " ").replace("\\u200b", "")
    lines = [re.sub(r"[ \t]+", " ", l).strip() for l in t.split("\n")]
    t = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


# ---- entity processing ---------------------------------------------------------
def _split_entity(data):
    if data.startswith(b"\r\n"):
        return b"", data[2:]
    i = data.find(b"\r\n\r\n")
    if i < 0:
        return None, None
    return data[:i], data[i + 4:]


def _split_parts(body, boundary):
    delim = re.compile(rb"(?:^|\r\n)--" + re.escape(boundary) + rb"(--)?[ \t]*(?=\r\n|\Z)")
    ms = list(delim.finditer(body))
    if not ms:
        return None
    parts, tail = [], None
    for i, m in enumerate(ms):
        if m.group(1):
            tail = body[m.end():]
            break
        end = ms[i + 1].start() if i + 1 < len(ms) else len(body)
        seg = body[m.end():end]
        parts.append(seg[2:] if seg.startswith(b"\r\n") else seg)
    if tail is None:
        return None
    return body[:ms[0].start()], ms[0].group(0).startswith(b"\r\n"), parts, tail


def _join_parts(pre, lead, parts, boundary, tail):
    out, first = [pre], True
    for p in parts:
        out.append((b"\r\n" if (lead or not first) else b"") + b"--" + boundary +
                   b"\r\n" + p)
        first = False
    out.append(b"\r\n--" + boundary + b"--" + tail)
    return b"".join(out)


def _ctype(headers):
    v = header_value(headers, b"content-type") or "text/plain"
    return v.split(";")[0].strip().lower()


def _is_attachment(headers):
    return (header_value(headers, b"content-disposition") or "").lower().startswith("attachment")


def _kind(part, depth=0):
    """'plain' | 'html' | 'other' for a child of multipart/alternative."""
    h, b = _split_entity(part)
    if h is None or _is_attachment(h):
        return "other"
    t = _ctype(h)
    if t == "text/plain":
        return "plain"
    if t == "text/html":
        return "html"
    if t == "multipart/related" and depth < 4:
        _, bd = fix_ct_header(h, Ctx())
        sp = _split_parts(b, bd.encode("latin-1")) if bd else None
        if sp and sp[2]:
            return "html" if _kind(sp[2][0], depth + 1) == "html" else "other"
    return "other"


def _alt_filter(parts, ctx):
    kinds = [_kind(p) for p in parts]
    if "html" not in kinds or "plain" not in kinds:
        return parts
    pi = kinds.index("plain")
    ph, pb = _split_entity(parts[pi])
    try:
        useless = len(re.sub(r"\s+", "", _decode_text(ph, pb))) < 25
    except Exception:
        useless = False
    if useless:                                   # keep the HTML (it will be converted)
        return [p for p, k in zip(parts, kinds) if k != "plain"]
    ctx.stats["html_dropped"] += kinds.count("html")
    return [p for p, k in zip(parts, kinds) if k != "html"]


def process_entity(data, depth, ctx):
    if depth > 8:
        return data
    headers, body = _split_entity(data)
    if headers is None:
        return data
    orig_h, orig_b = headers, body
    if depth == 0 and ctx.translit:
        headers = fix_hebrew_headers(headers, ctx)
    mtype = _ctype(headers)

    if mtype.startswith("multipart/"):
        headers, boundary = fix_ct_header(headers, ctx)
        if boundary is not None:
            bd = boundary.encode("latin-1")
            sp = _split_parts(body, bd)
            if sp:
                pre, lead, parts, tail = sp
                new_parts = _alt_filter(parts, ctx) if (
                    mtype == "multipart/alternative" and ctx.strip_html) else parts
                new_parts = [process_entity(p, depth + 1, ctx) for p in new_parts]
                if new_parts != parts:
                    body = _join_parts(pre, lead, new_parts, bd, tail)
    elif not _is_attachment(headers) and _known_charset(headers):
        try:
            if mtype == "text/plain" and (ctx.translit or ctx.clean):
                norm = _decode_text(headers, body).replace("\r\n", "\n").replace("\r", "\n")
                new_text = norm
                if HEB_MODE == "glyph" and ctx.translit and HEB_RE.search(norm):
                    ctx.stats["heb_parts"] += 1
                    return _build_glyph_part(headers, clean_text(norm) if ctx.clean else norm, depth == 0)
                if ctx.translit and HEB_RE.search(norm):
                    ctx.stats["heb_parts"] += 1
                    new_text = translit_hebrew(new_text)
                if ctx.clean:
                    new_text = clean_text(new_text)
                if new_text != norm:
                    if ctx.clean and not HEB_RE.search(norm):
                        ctx.stats["text_cleaned"] += 1
                    return _build_text_part(headers, new_text, depth == 0)
            elif mtype == "text/html" and ctx.strip_html:
                text = html_to_text(_decode_text(headers, body))
                if ctx.clean:
                    text = clean_text(text, tidy=True)
                ctx.stats["html_converted"] += 1
                if HEB_MODE == "glyph" and ctx.translit and HEB_RE.search(text):
                    ctx.stats["heb_parts"] += 1
                    return _build_glyph_part(headers, text, depth == 0,
                                             "[Converted from HTML by the Falcon mail gateway]")
                if ctx.translit and HEB_RE.search(text):
                    ctx.stats["heb_parts"] += 1
                    text = translit_hebrew(text)
                return _build_text_part(headers, text, depth == 0,
                                        "[Converted from HTML by the Falcon mail gateway]")
        except Exception as e:
            log.warning("text conversion failed (%r); part left as is", e)

    if headers == orig_h and body is orig_b:
        return data
    return (headers + b"\r\n\r\n" + body) if headers else (b"\r\n" + body)


def fix_header_block(data, ctx):
    """For header-only fetches (the message list)."""
    i = data.find(b"\r\n\r\n")
    hdr, rest = (data, b"") if i < 0 else (data[:i], data[i:])
    if ctx.translit:
        hdr = fix_hebrew_headers(hdr, ctx)
    hdr, _ = fix_ct_header(hdr, ctx)
    return hdr + rest


WHOLE_MSG_RE = re.compile(rb"(?:BODY\[\]|\bRFC822) \{(\d+)\}$")
HEADER_LIT_RE = re.compile(rb"(?:BODY\[HEADER[^\]]*\]|\bRFC822\.HEADER) \{(\d+)\}$")


class ServerFilter:
    """Server->client stream: buffers whole-message and header literals, rewrites
    them, fixes the {size}; everything else is forwarded untouched."""
    def __init__(self, sid, strip_html=True, translit=True, clean=True):
        self.sid, self.strip_html, self.translit, self.clean = sid, strip_html, translit, clean
        self.buf = b""
        self.mode = "line"        # line | pass | hold
        self.remaining = 0
        self.kind = "msg"
        self.held_line = b""
        self.held = []

    def feed(self, data):
        out = []
        self.buf += data
        while True:
            if self.mode == "line":
                i = self.buf.find(b"\r\n")
                if i < 0:
                    break
                line, self.buf = self.buf[:i], self.buf[i + 2:]
                m = LITERAL_RE.search(line)
                if not m:
                    out.append(line + b"\r\n")
                    continue
                n = int(m.group(1))
                if n <= MAX_REWRITE and WHOLE_MSG_RE.search(line):
                    self.kind = "msg"
                elif n <= MAX_REWRITE and HEADER_LIT_RE.search(line):
                    self.kind = "hdr"
                else:
                    self.mode, self.remaining = "pass", n
                    out.append(line + b"\r\n")
                    continue
                self.mode, self.remaining = "hold", n
                self.held_line, self.held = line, []
            elif self.mode == "pass":
                if not self.buf:
                    break
                take = self.buf[:self.remaining]
                self.buf = self.buf[len(take):]
                self.remaining -= len(take)
                out.append(take)
                if self.remaining == 0:
                    self.mode = "line"
            else:  # hold
                take = self.buf[:self.remaining]
                self.buf = self.buf[len(take):]
                self.remaining -= len(take)
                self.held.append(take)
                if self.remaining > 0:
                    break
                orig = b"".join(self.held)
                ctx = Ctx(self.strip_html, self.translit, self.clean)
                try:
                    new = (process_entity(orig, 0, ctx) if self.kind == "msg"
                           else fix_header_block(orig, ctx))
                except Exception as e:
                    log.warning("[%s] rewrite error, passing original: %r", self.sid, e)
                    new = orig
                line = self.held_line
                if new != orig:
                    line = re.sub(rb"\{\d+\}$", b"{%d}" % len(new), line)
                    log.info("[%s] * REWROTE %s (%d -> %d bytes): %s", self.sid,
                             "message" if self.kind == "msg" else "headers",
                             len(orig), len(new), ctx.summary())
                out.append(line + b"\r\n" + new)
                self.held, self.held_line = [], b""
                self.mode = "line"
        return b"".join(out)


class Tap:
    """Feeds on one direction of the stream; emits log lines. Never raises."""
    def __init__(self, sid, who, state, hints=False):
        self.sid, self.who, self.state, self.hints = sid, who, state, hints
        self.buf = b""
        self.skip = 0            # bytes of literal still to skip
        self.lit_total = 0

    def feed(self, data):
        try:
            self._feed(data)
        except Exception as e:           # logging must never break the proxy
            log.warning("[%s] tap error (%s): %r", self.sid, self.who, e)

    def _feed(self, data):
        while data:
            if self.skip:
                n = min(self.skip, len(data))
                self.skip -= n
                data = data[n:]
                if not self.skip:
                    log.info("[%s] %s   [literal of %d bytes not logged]",
                             self.sid, self.who, self.lit_total)
                continue
            self.buf += data
            data = b""
            while True:
                i = self.buf.find(b"\r\n")
                if i < 0:
                    if len(self.buf) > 65536:       # runaway line; drop
                        self.buf = b""
                    break
                line, self.buf = self.buf[:i], self.buf[i + 2:]
                self._line(line)
                if self.skip:                        # literal starts here
                    rest, self.buf = self.buf, b""
                    data = rest
                    break

    def _line(self, line):
        shown = line
        if self.who == "C":
            if self.state["auth"]:
                shown = b"[credentials redacted]"
            else:
                parts = line.split(None, 3)
                cmd = parts[1].upper() if len(parts) > 1 else b""
                if cmd == b"LOGIN":
                    shown = parts[0] + b" LOGIN [redacted]"
                    if self.hints:
                        shown += b" " + login_shape(line)
                elif cmd == b"AUTHENTICATE":
                    mech = parts[2] if len(parts) > 2 else b""
                    shown = parts[0] + b" AUTHENTICATE " + mech + b" [redacted]"
                    self.state["auth"] = True
        elif self.state["auth"] and re.match(rb"^\S+ (OK|NO|BAD)\b", line):
            self.state["auth"] = False       # tagged result ends authentication
        m = LITERAL_RE.search(line)
        txt = shown.decode("latin-1")
        if len(txt) > MAXLINE:
            txt = txt[:MAXLINE] + " ...[truncated]"
        log.info("[%s] %s %s", self.sid, self.who, txt)
        if m:
            self.skip = self.lit_total = int(m.group(1))


async def pump(reader, writer, tap, filt=None):
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            out = filt.feed(data) if filt else data
            if out:
                writer.write(out)       # forward first, log second
                await writer.drain()
            tap.feed(data)              # log what the server actually sent
    except (ConnectionError, asyncio.CancelledError):
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def handle(cr, cw, args, ctx):
    sid = next(sess_ids)
    peer = cw.get_extra_info("peername")
    log.info("[%s] --- client connected from %s", sid, peer[0] if peer else "?")
    try:
        ur, uw = await asyncio.wait_for(
            asyncio.open_connection(args.upstream_host, args.upstream_port,
                                    ssl=ctx, server_hostname=args.upstream_host
                                    if ctx else None), timeout=20)
    except Exception as e:
        log.error("[%s] upstream connect failed: %r", sid, e)
        cw.close()
        return
    state = {"auth": False}
    ctap = Tap(sid, "C", state, args.login_hints)
    stap = Tap(sid, "S", state)
    filt = (ServerFilter(sid, not args.keep_html, not args.no_translit, not args.no_clean)
            if args.rewrite else None)
    await asyncio.gather(pump(cr, uw, ctap), pump(ur, cw, stap, filt))
    log.info("[%s] --- session closed", sid)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", action="version", version="falcon_imap_logproxy " + VERSION)
    ap.add_argument("--listen", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=1143)
    ap.add_argument("--upstream-host", default="imap.mail.me.com")
    ap.add_argument("--upstream-port", type=int, default=993)
    ap.add_argument("--login-hints", action="store_true",
                    help="log only the SHAPE of LOGIN credentials (lengths, '@', dashes)")
    ap.add_argument("--rewrite", action="store_true",
                    help="normalise multipart Content-Type headers in fetched messages")
    ap.add_argument("--keep-html", action="store_true",
                    help="with --rewrite: do NOT strip/convert HTML parts")
    ap.add_argument("--hebrew-words", default="/opt/falcon-imap/hebrew_words.txt",
                    help="optional file of extra Hebrew words: 'hebrew-word latin-word' per line")
    ap.add_argument("--literal-hebrew", action="store_true",
                    help="letter-for-letter Hebrew (shlvm) instead of phonetic (shalom)")
    ap.add_argument("--hebrew-mode", choices=["phonetic", "literal", "glyph"], default=None,
                    help="glyph = real Hebrew letters in the Atari character set, in visual order")
    ap.add_argument("--glyph-charset", default="x-atari-st",
                    help="charset label put on converted parts (TROLL must not convert it)")
    ap.add_argument("--glyph-cte", choices=["base64", "8bit", "quoted-printable"],
                    default="8bit", help="8bit and quoted-printable work in TROLL, base64 does not; "
                                         "8bit is the default (no line-length issues)")
    ap.add_argument("--glyph-width", type=int, default=60, help="wrap width for lines with Hebrew")
    ap.add_argument("--glyph-subject-label", default="x",
                    help="charset label for Subject/From encoded words; TROLL shows it as {LABEL} before "
                         "the title, so keep it short (default: x)")
    ap.add_argument("--glyph-subject", choices=["encoded", "encoded-q", "raw", "phonetic"],
                    default="encoded-q",
                    help="encoded = RFC 2047 B words; encoded-q = Q words; raw = 8-bit bytes in the header "
                         "(garbled in TROLL); phonetic = Latin transliteration in the Subject/From "
                         "(no {charset} marker); the body stays real Hebrew")
    ap.add_argument("--no-clean", action="store_true",
                    help="with --rewrite: do NOT remove invisible/unsupported characters")
    ap.add_argument("--no-translit", action="store_true",
                    help="with --rewrite: do NOT transliterate Hebrew")
    ap.add_argument("--no-tls", action="store_true",
                    help="plain upstream (local testing ONLY)")
    args = ap.parse_args()
    logging.basicConfig(stream=sys.stdout, level=logging.INFO,
                        format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    global HEB_WORDS, HEB_MODE
    HEB_WORDS = load_hebrew_words(args.hebrew_words)
    HEB_MODE = args.hebrew_mode or ("literal" if args.literal_hebrew else "phonetic")
    GLYPH.update(label=args.glyph_charset, cte=args.glyph_cte, width=args.glyph_width,
                 subject=args.glyph_subject, subject_label=args.glyph_subject_label)
    ctx = None if args.no_tls else ssl.create_default_context()  # verifies chain+hostname
    srv = await asyncio.start_server(lambda r, w: handle(r, w, args, ctx),
                                     args.listen, args.port)
    mode = ", pass-through"
    if args.rewrite:
        mode = ", REWRITE ON (html %s, hebrew %s, %d words)" % (
            "kept" if args.keep_html else "stripped",
            "kept" if args.no_translit else HEB_MODE, len(HEB_WORDS))
    log.info("falcon_imap_logproxy %s: listening on %s:%d -> %s:%d (%s%s)", VERSION,
             args.listen, args.port, args.upstream_host, args.upstream_port,
             "PLAIN, testing" if ctx is None else "verified TLS", mode)
    async with srv:
        await srv.serve_forever()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
