"""Bug #5: Persian half-space (ZWNJ, U+200C) normalization of model output.

The AI model occasionally drops the نیم‌فاصله in Persian compounds (می‌شود →
میشود). This module restores it with a conservative, auditable dictionary
plus one high-precision rule (می + whitelisted verb forms). Everything is
word-boundary-guarded and idempotent — the #1 requirement is NEVER
corrupting valid text, so there are deliberately no broad regexes (e.g.
blind "ها" or "شده" suffixes would mangle words like رها، بهای، نشده).
"""
from __future__ import annotations

import re

Z = "\u200c"

# Exact bad -> good word pairs. Keys must never contain ZWNJ. This mirrors
# the technique proven on the README (/tmp/fix_zwnj.py) — deterministic and
# auditable, extended here with formal book-register vocabulary.
FIXES = {
    # می + verb (colloquial + standard)
    "میشود": f"می{Z}شود",
    "میشن": f"می{Z}شن",
    "میشه": f"می{Z}شه",
    "میشد": f"می{Z}شد",
    "میشدند": f"می{Z}شدند",
    "میکنید": f"می{Z}کنید",
    "میکنه": f"می{Z}کنه",
    "میکنم": f"می{Z}کنم",
    "میکند": f"می{Z}کند",
    "میکنیم": f"می{Z}کنیم",
    "میکنند": f"می{Z}کنند",
    "میکرد": f"می{Z}کرد",
    "میکردند": f"می{Z}کردند",
    "میبینید": f"می{Z}بینید",
    "میذارید": f"می{Z}ذارید",
    "میمونه": f"می{Z}مونه",
    "میگیرن": f"می{Z}گیرن",
    "میرید": f"می{Z}رید",
    "میزنید": f"می{Z}زنید",
    "میتونید": f"می{Z}تونید",
    "میدید": f"می{Z}دید",
    "میداند": f"می{Z}داند",
    "میدانم": f"می{Z}دانم",
    "میدانند": f"می{Z}دانند",
    "میگوید": f"می{Z}گوید",
    "میگفت": f"می{Z}گفت",
    "میخواهد": f"می{Z}خواهد",
    "میخواست": f"می{Z}خواست",
    "میرود": f"می{Z}رود",
    "میروند": f"می{Z}روند",
    "میرفت": f"می{Z}رفت",
    "میآید": f"می{Z}آید",
    "میآیند": f"می{Z}آیند",
    "میآمد": f"می{Z}آمد",
    "میگذارد": f"می{Z}گذارد",
    "میگذاشت": f"می{Z}گذاشت",
    "میگیرد": f"می{Z}گیرد",
    "میگرفت": f"می{Z}گرفت",
    "میافتد": f"می{Z}افتد",
    "میشنود": f"می{Z}شنود",
    "میفهمد": f"می{Z}فهمد",
    "میماند": f"می{Z}ماند",
    "میمانند": f"می{Z}مانند",
    "میخورد": f"می{Z}خورد",
    "میخورند": f"می{Z}خورند",
    "میخوابد": f"می{Z}خوابد",
    "میایستد": f"می{Z}ایستد",
    "مینشیند": f"می{Z}نشیند",
    "مینشست": f"می{Z}نشست",
    "نمیشود": f"نمی{Z}شود",
    "نمیشه": f"نمی{Z}شه",
    "نمیکنه": f"نمی{Z}کنه",
    # ب + verb (colloquial imperative/subjunctive)
    "بشه": f"ب{Z}شه",
    "بشید": f"ب{Z}شید",
    "ببرید": f"ب{Z}برید",
    "بندازید": f"ب{Z}ندازید",
    # به + noun
    "بههمراه": f"به{Z}همراه",
    "بهعنوان": f"به{Z}عنوان",
    "بهازای": f"به{Z}ازای",
    "بهروزرسانی": f"به{Z}روزرسانی",
    "بهجز": f"به{Z}جز",
    "بهویژه": f"به{Z}ویژه",
    "بهطور": f"به{Z}طور",
    "بهصورت": f"به{Z}صورت",
    "بهدقت": f"به{Z}دقت",
    "بهراحتی": f"به{Z}راحتی",
    "بهزودی": f"به{Z}زودی",
    "بهندرت": f"به{Z}ندرت",
    "بهتدریج": f"به{Z}تدریج",
    "بهکلی": f"به{Z}کلی",
    "بههیچوجه": f"به{Z}هیچ{Z}وجه",
    "بههرحال": f"به{Z}هر{Z}حال",
    "بهنوعی": f"به{Z}نوعی",
    "بهگونهای": f"به{Z}گونه{Z}ای",
    "بهمنظور": f"به{Z}منظور",
    "بهدلیل": f"به{Z}دلیل",
    "بهخاطر": f"به{Z}خاطر",
    "بهجای": f"به{Z}جای",
    "بهسوی": f"به{Z}سوی",
    "بهسمت": f"به{Z}سمت",
    # هم / هیچ / پس / پیش / تک / راستی compounds
    "همینطور": f"همین{Z}طور",
    "همانطور": f"همان{Z}طور",
    "هیچجا": f"هیچ{Z}جا",
    "هیچوقت": f"هیچ{Z}وقت",
    "هیچکس": f"هیچ{Z}کس",
    "هیچچیز": f"هیچ{Z}چیز",
    "هیچکدام": f"هیچ{Z}کدام",
    "هیچگاه": f"هیچ{Z}گاه",
    "پسزمینه": f"پس{Z}زمینه",
    "پیشتنظیم": f"پیش{Z}تنظیم",
    "تککاربره": f"تک{Z}کاربره",
    "راستیآزمایی": f"راستی{Z}آزمایی",
    "بایتبهبایت": f"بایت{Z}به{Z}بایت",
    "فصلبهفصل": f"فصل{Z}به{Z}فصل",
    "چندزبانه": f"چند{Z}زبانه",
    # بی / نا / غیر compounds
    "بیشمار": f"بی{Z}شمار",
    "بیشک": f"بی{Z}شک",
    "بیتردید": f"بی{Z}تردید",
    "بینهایت": f"بی{Z}نهایت",
    "بیوقفه": f"بی{Z}وقفه",
    "بیهیچ": f"بی{Z}هیچ",
    "ناامید": f"نا{Z}امید",
    "غیرممکن": f"غیر{Z}ممکن",
    "غیرقابل": f"غیر{Z}قابل",
    "غیرمنتظره": f"غیر{Z}منتظره",
    # ها / های plurals (exact words only — no blind suffix rule)
    "کتابها": f"کتاب{Z}ها",
    "کتابهای": f"کتاب{Z}های",
    "فصلها": f"فصل{Z}ها",
    "فصلهای": f"فصل{Z}های",
    "اسمها": f"اسم{Z}ها",
    "ترجمهها": f"ترجمه{Z}ها",
    "ورودیهای": f"ورودی{Z}های",
    "فایلهای": f"فایل{Z}های",
    "خانهها": f"خانه{Z}ها",
    "خانههای": f"خانه{Z}های",
    "سالها": f"سال{Z}ها",
    "سالهای": f"سال{Z}های",
    "روزها": f"روز{Z}ها",
    "روزهای": f"روز{Z}های",
    "شبها": f"شب{Z}ها",
    "شبهای": f"شب{Z}های",
    "دستها": f"دست{Z}ها",
    "دستهای": f"دست{Z}های",
    "چشمها": f"چشم{Z}ها",
    "واژهها": f"واژه{Z}ها",
    "واژههای": f"واژه{Z}های",
    "جملهها": f"جمله{Z}ها",
    "جملههای": f"جمله{Z}های",
    "بخشها": f"بخش{Z}ها",
    "بخشهای": f"بخش{Z}های",
    "صفحهها": f"صفحه{Z}ها",
    "نسخهها": f"نسخه{Z}ها",
    "خطاها": f"خطا{Z}ها",
    "پیامها": f"پیام{Z}ها",
    "متنها": f"متن{Z}ها",
    "متنهای": f"متن{Z}های",
    "برنامهها": f"برنامه{Z}ها",
    "برنامههای": f"برنامه{Z}های",
    "خروجیها": f"خروجی{Z}ها",
    "کتابخانهها": f"کتابخانه{Z}ها",
    "کتابخانههای": f"کتابخانه{Z}های",
    # X‌شده participles (exact words only)
    "تاییدشده": f"تایید{Z}شده",
    "بازسازیشده": f"بازسازی{Z}شده",
    "استخراجشده": f"استخراج{Z}شده",
    "دستنخورده": f"دست{Z}نخورده",
    "خوشساخت": f"خوش{Z}ساخت",
    "ساختهشده": f"ساخته{Z}شده",
    "سروشده": f"سرو{Z}شده",
    "نرمالسازی": f"نرمال{Z}سازی",
    "اعمالشده": f"اعمال{Z}شده",
    "اعمالشدهی": f"اعمال{Z}شدهی",
    "انجامشده": f"انجام{Z}شده",
    "انجامشدهی": f"انجام{Z}شدهی",
    "تبدیلشده": f"تبدیل{Z}شده",
    "حذفشده": f"حذف{Z}شده",
    "اضافهشده": f"اضافه{Z}شده",
    "ذخیرهشده": f"ذخیره{Z}شده",
    "ثبتشده": f"ثبت{Z}شده",
    "گفتهشده": f"گفته{Z}شده",
    "نوشتهشده": f"نوشته{Z}شده",
    "خواندهشده": f"خوانده{Z}شده",
    "دیدهشده": f"دیده{Z}شده",
    "منتشرشده": f"منتشر{Z}شده",
    "انتخابشده": f"انتخاب{Z}شده",
    "تعریفشده": f"تعریف{Z}شده",
    "مشخصشده": f"مشخص{Z}شده",
    "ارائهشده": f"ارائه{Z}شده",
    "پیشنهادشده": f"پیشنهاد{Z}شده",
    "معرفیشده": f"معرفی{Z}شده",
    "علامتگذاری": f"علامت{Z}گذاری",
    "یککلیکی": f"یک{Z}کلیکی",
    # loanword halves
    "بکاند": f"بک{Z}اند",
    "فرانتاند": f"فرانت{Z}اند",
    "وزیرمتن": f"وزیر{Z}متن",
}

# High-precision productive rule: می + a whitelisted verb form, word-boundary
# guarded. Verb forms are GENERATED from (present_3sg, past_3sg) pairs so no
# inflection is forgotten (رفتند، شنیدند، ...). The whitelist makes this
# safe — میز، میوه، میل، میدان، میراث، میخ can never match because the
# chars after می must be a complete real verb form (دان alone is never in
# the set, only داند/دانم/دانست/... are).
_MI_VERBS = {
    # present_3sg: past_3sg
    "شود": "شد",        # شدن
    "کند": "کرد",       # کردن
    "گوید": "گفت",      # گفتن
    "خواهد": "خواست",   # خواستن
    "رود": "رفت",       # رفتن
    "آید": "آمد",       # آمدن
    "بیند": "دید",      # دیدن
    "داند": "دانست",    # دانستن
    "تواند": "توانست",  # توانستن
    "ماند": "ماند",     # ماندن
    "گذارد": "گذاشت",   # گذاشتن
    "گیرد": "گرفت",     # گرفتن
    "خورد": "خورد",     # خوردن
    "نشیند": "نشست",    # نشستن
    "ایستد": "ایستاد",  # ایستادن
    "ترسد": "ترسید",    # ترسیدن
    "خندد": "خندید",    # خندیدن
    "شنود": "شنید",     # شنیدن
    "فهمد": "فهمید",    # فهمیدن
    "سازد": "ساخت",     # ساختن
    "خواند": "خواند",   # خواندن
    "نویسد": "نوشت",    # نوشتن
    "باشد": "بود",      # بودن
    "دهد": "داد",       # دادن
    "آورد": "آورد",     # آوردن
    "اندازد": "انداخت", # انداختن
    "برد": "برد",       # بردن
    "رسد": "رسید",      # رسیدن
    "کشد": "کشید",      # کشیدن
    "افتد": "افتاد",    # افتادن
    "شمارد": "شمرد",    # شمردن
    "پرد": "پرید",      # پریدن
    "دود": "دوید",      # دویدن
    "بندد": "بست",      # بستن
}


def _verb_forms(present_3sg: str, past_3sg: str) -> list:
    """All 12 inflections, generated so no form is forgotten.

    Present: stem (=3sg minus final د) + م/ی/د/یم/ید/ند  ->  روم روی رود رویم روید روند
    Past:    3sg itself is the stem + م/ی/یم/ید/ند         ->  رفتم رفتی رفت رفتیم رفتید رفتند
    """
    p_stem = present_3sg[:-1]
    p_d = present_3sg[-1]
    present = [p_stem + s for s in ["م", "ی", p_d, "یم", "ید", "ند"]]
    past = [past_3sg + s for s in ["م", "ی", "", "یم", "ید", "ند"]]
    return present + past


_MI_VERB_FORMS = sorted(
    {f for p, pa in _MI_VERBS.items() for f in _verb_forms(p, pa)},
    key=len,
    reverse=True,
)
_MI_VERB_RE = re.compile(
    r"می(?=(?:" + "|".join(re.escape(f) for f in _MI_VERB_FORMS) + r")\b)"
)

# Word-boundary guard for dictionary replacements: the bad form must be a
# standalone token, not a substring of a longer word (e.g. کتابها must not
# fire inside کتابهایم).
_DICT_RE = re.compile(
    "|".join(
        rf"(?<!\w){re.escape(bad)}(?!\w)"
        for bad in sorted(FIXES, key=len, reverse=True)  # longest first
    )
)
_DICT_MAP = {bad: good for bad, good in FIXES.items()}


def normalize_half_spaces(text: str) -> str:
    """Restore missing ZWNJ in Persian compounds. Idempotent: correct text
    passes through byte-identical, English passes through untouched."""
    if not text or not any("\u0600" <= c <= "\u06ff" for c in text):
        return text  # no Persian characters — nothing to do

    def _repl(m: re.Match) -> str:
        return _DICT_MAP[m.group(0)]

    out = _DICT_RE.sub(_repl, text)
    out = _MI_VERB_RE.sub(f"می{Z}", out)
    return out
