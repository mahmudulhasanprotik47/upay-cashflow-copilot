# English and Bangla message templates for the Cash-Flow Copilot. All data is simulated.
# Tone: calm, plain, empowering. No urgency or pressure words. Numbers are filled in from data.
# Run: python -m src.i18n.messages   (writes docs/messages_preview.md as UTF-8; prints no Bangla)

import re  # Singular English words and lakh grouping.
import string  # Finds the {placeholders} in a template.

from src import config as cfg  # Central settings.

# Sentence endings for reasons: what goes with the risk in this simulated data, never a cause.
_UP_EN, _DOWN_EN = " In this simulated data, this goes with higher risk.", " In this simulated data, this goes with lower risk."
_UP_BN, _DOWN_BN = " এই সিমুলেটেড ডেটায় এটি বেশি ঝুঁকির সাথে দেখা যায়।", " এই সিমুলেটেড ডেটায় এটি কম ঝুঁকির সাথে দেখা যায়।"

# English "1 months" -> "1 month" (and days, cash-outs, bills). Not after a digit, comma or dot (21, 1,001, 0.1).
_SINGULAR_EN = re.compile(r"(?<![\d.,])1 (months|days|cash-outs|bills)\b")

# Every message: key -> {"en": ..., "bn": ...}. {name} marks a value filled in at run time.
MESSAGES = {
    # --- Risk bands (no probability is ever shown) ---
    "band_low": {
        "en": "Low risk: your balance looks on track for the rest of the month.",
        "bn": "কম ঝুঁকি: মাসের বাকি সময়ের জন্য আপনার ব্যালেন্স ঠিক পথে আছে বলে মনে হচ্ছে।"},
    "band_medium": {
        "en": "Medium risk: your balance may run low before the month ends.",
        "bn": "মাঝারি ঝুঁকি: মাস শেষ হওয়ার আগে আপনার ব্যালেন্স কমে যেতে পারে।"},
    "band_high": {
        "en": "High risk: your balance is likely to run low before the month ends.",
        "bn": "বেশি ঝুঁকি: মাস শেষ হওয়ার আগে আপনার ব্যালেন্স কমে যাওয়ার সম্ভাবনা বেশি।"},

    # --- Shortfall warning and buffer (only with an alert) ---
    "shortfall_warning": {
        "en": "Our estimate is that your balance could drop below {floor} BDT before the month ends. "
              "You can plan for this now.",
        "bn": "আমাদের অনুমান, মাস শেষ হওয়ার আগে আপনার ব্যালেন্স {floor} টাকার নিচে নেমে যেতে পারে। "
              "আপনি এখন থেকেই এর জন্য পরিকল্পনা করতে পারেন।"},
    "buffer": {  # A rule (days of the user's own spending), not a model output: no error sentence.
        "en": "Idea: keep about {buffer} BDT, roughly {days} days of your usual spending, unspent until the "
              "month ends.",
        "bn": "পরামর্শ: মাস শেষ হওয়া পর্যন্ত প্রায় {buffer} টাকা খরচ না করে হাতে রাখতে পারেন, যা আপনার "
              "স্বাভাবিক খরচের মোটামুটি {days} দিনের সমান।"},
    "buffer_capped": {  # The balance limits the buffer, so no days-of-spending claim and no error sentence.
        "en": "Idea: keep about {buffer} BDT, close to your current balance, unspent until the month ends.",
        "bn": "পরামর্শ: মাস শেষ হওয়া পর্যন্ত প্রায় {buffer} টাকা, যা আপনার বর্তমান ব্যালেন্সের কাছাকাছি, "
              "খরচ না করে হাতে রাখতে পারেন।"},
    "no_buffer_low_balance": {
        "en": "Your current balance is small, so we are not suggesting a buffer amount this time.",
        "bn": "আপনার বর্তমান ব্যালেন্স কম, তাই এবার আমরা হাতে রাখার কোনো পরিমাণ প্রস্তাব করছি না।"},

    # --- Cash-out fee tip (never says cash-out is bad) ---
    "cashout_saver": {
        "en": "So far this month you made {count} cash-outs and paid {fees} BDT in fees "
              "(assumed fee rate {fee_rate}%, a placeholder, not yet sourced). If some of these payments "
              "could be made from the wallet, you could avoid up to about {fees} BDT in fees. "
              "Cash-out is fine when you need cash.",
        "bn": "এই মাসে এ পর্যন্ত আপনি {count} বার ক্যাশ আউট করেছেন এবং ফি দিয়েছেন {fees} টাকা "
              "(ধরে নেওয়া ফি হার {fee_rate}%, এটি অস্থায়ী, এখনো যাচাই করা হয়নি)। এর কিছু পেমেন্ট যদি "
              "ওয়ালেট থেকে করা যায়, তাহলে প্রায় {fees} টাকা পর্যন্ত ফি বাঁচাতে পারেন। "
              "নগদ টাকার দরকার হলে ক্যাশ আউট করায় কোনো সমস্যা নেই।"},

    # --- Savings plan ---
    "savings_feasible": {
        "en": "You can reach {goal} BDT in {months} months by saving {monthly} BDT a month. That fits within "
              "the {capacity} BDT a month your earlier months suggest you could set aside.",
        "bn": "প্রতি মাসে {monthly} টাকা জমিয়ে আপনি {months} মাসে {goal} টাকায় পৌঁছাতে পারেন। আগের মাসগুলো "
              "দেখে মনে হয় আপনি মাসে {capacity} টাকা পর্যন্ত আলাদা রাখতে পারেন; এটি তার মধ্যেই আছে।"},
    "savings_not_feasible": {
        "en": "Reaching {goal} BDT in {months} months would need {needed} BDT a month, more than the {capacity} "
              "BDT a month your earlier months suggest. At {capacity} BDT a month it would take about "
              "{months_needed} months.",
        "bn": "{months} মাসে {goal} টাকায় পৌঁছাতে মাসে {needed} টাকা লাগবে, যা আগের মাসগুলো অনুযায়ী "
              "আপনার মাসিক {capacity} টাকার চেয়ে বেশি। মাসে {capacity} টাকা করে জমালে প্রায় "
              "{months_needed} মাস লাগবে।"},
    "savings_not_reached": {
        "en": "Reaching {goal} BDT in {months} months would need {needed} BDT a month, more than the {capacity} "
              "BDT a month your earlier months suggest. At {capacity} BDT a month, {max_months} months would "
              "give about {saved} BDT, so a smaller goal may suit you better.",
        "bn": "{months} মাসে {goal} টাকায় পৌঁছাতে মাসে {needed} টাকা লাগবে, যা আগের মাসগুলো অনুযায়ী "
              "আপনার মাসিক {capacity} টাকার চেয়ে বেশি। মাসে {capacity} টাকা করে জমালে {max_months} মাসে "
              "প্রায় {saved} টাকা হবে, তাই একটু ছোট লক্ষ্য আপনার জন্য সহজ হতে পারে।"},
    "savings_option": {
        "en": "Option: {monthly} BDT a month for {months} months.",
        "bn": "বিকল্প: মাসে {monthly} টাকা করে {months} মাস।"},
    "savings_option_not_reached": {
        "en": "Option: {monthly} BDT a month; the goal would take more than {max_months} months.",
        "bn": "বিকল্প: মাসে {monthly} টাকা করে; লক্ষ্যে পৌঁছাতে {max_months} মাসের বেশি লাগবে।"},
    "savings_blocked_alert": {
        "en": "Because your balance may run low this month, we are not suggesting savings right now. "
              "You may want to keep a buffer first.",
        "bn": "এই মাসে আপনার ব্যালেন্স কমে যেতে পারে, তাই এখন আমরা সঞ্চয়ের পরামর্শ দিচ্ছি না। "
              "আগে কিছু টাকা হাতে রাখার কথা ভাবতে পারেন।"},
    "savings_no_history": {
        "en": "There are no earlier months to learn from yet, so we cannot suggest a savings plan.",
        "bn": "হিসাব করার মতো আগের কোনো মাসের তথ্য এখনো নেই, তাই আমরা সঞ্চয়ের পরিকল্পনা দিতে পারছি না।"},
    "savings_no_room": {
        "en": "Your earlier months show no room to save yet, so we are not suggesting a savings plan.",
        "bn": "আপনার আগের মাসগুলোতে এখনো সঞ্চয়ের মতো বাড়তি টাকা দেখা যায়নি, তাই আমরা সঞ্চয়ের পরিকল্পনা দিচ্ছি না।"},

    # --- What-if ---
    "whatif_lower": {
        "en": "With these changes, the risk would be lower.",
        "bn": "এই পরিবর্তনগুলো হলে ঝুঁকি কম হবে।"},
    "whatif_same": {
        "en": "With these changes, the risk would be about the same.",
        "bn": "এই পরিবর্তনগুলো হলে ঝুঁকি প্রায় একই থাকবে।"},
    "whatif_higher": {
        "en": "With these changes, the risk would be higher.",
        "bn": "এই পরিবর্তনগুলো হলে ঝুঁকি বেশি হবে।"},
    "whatif_note": {
        "en": "A what-if only changes the inputs you entered. It does not re-simulate the month.",
        "bn": "'যদি এমন হয়' শুধু আপনার দেওয়া তথ্যগুলো বদলায়। এটি পুরো মাসটি নতুন করে হিসাব করে না।"},

    # --- Month summary (why do I run short before month-end?) ---
    "summary_biggest_week": {
        "en": "Your biggest spending week so far was days {start_day} to {end_day}, with {amount} BDT out of "
              "{total} BDT spent so far this month. The largest category was {category} ({category_amount} BDT).",
        "bn": "এ পর্যন্ত আপনার সবচেয়ে বেশি খরচের সপ্তাহ ছিল {start_day} থেকে {end_day} তারিখ; এই মাসে মোট "
              "{total} টাকার মধ্যে {amount} টাকা খরচ হয়েছে। সবচেয়ে বড় খাত ছিল {category} ({category_amount} টাকা)।"},
    "cat_merchant": {"en": "shop payments", "bn": "দোকানে পেমেন্ট"},
    "cat_bills": {"en": "bills", "bn": "বিল"},
    "cat_recharge": {"en": "mobile recharge", "bn": "মোবাইল রিচার্জ"},
    "cat_family": {"en": "money sent to family", "bn": "পরিবারে পাঠানো টাকা"},
    "cat_cashout": {"en": "cash-out", "bn": "ক্যাশ আউট"},

    # --- Disclaimer and honest summary ---
    "disclaimer": {
        "en": "This is an estimate from simulated data, not a guarantee. You decide.",
        "bn": "এটি সিমুলেটেড ডেটা থেকে করা একটি অনুমান, কোনো নিশ্চয়তা নয়। সিদ্ধান্ত আপনার।"},
    "honest_summary": {
        "en": "The model has a small lead over a simple balance rule, but it is not statistically clear.",
        "bn": "একটি সহজ ব্যালেন্স নিয়মের চেয়ে মডেলটি সামান্য এগিয়ে, তবে পরিসংখ্যানগতভাবে তা স্পষ্ট নয়।"},

    # --- Errors (short and generic, never echo the input) ---
    "error_not_found": {
        "en": "We could not find that.",
        "bn": "এটি খুঁজে পাওয়া যায়নি।"},
    "error_invalid": {
        "en": "Some details are not valid. Please check them and try again.",
        "bn": "কিছু তথ্য সঠিক নয়। অনুগ্রহ করে দেখে আবার চেষ্টা করুন।"},
    "error_server": {
        "en": "Something went wrong on our side. Please try again later.",
        "bn": "আমাদের দিকে একটি সমস্যা হয়েছে। অনুগ্রহ করে পরে আবার চেষ্টা করুন।"},
}

# Reasons: what the model looked at, in the user's own numbers (en, bn, preview sample value).
# The _none and _today variants of days_since_last_inflow have no number: 20 means nothing came in on days 1-20.
_REASON_FACTS = {
    "balance_day20": ("Your current balance: {value} BDT.",
                      "আপনার বর্তমান ব্যালেন্স: {value} টাকা।", 3250),
    "min_balance_d1_20": ("Your lowest balance so far this month: {value} BDT.",
                          "এই মাসে এ পর্যন্ত আপনার সর্বনিম্ন ব্যালেন্স: {value} টাকা।", 820),
    "avg_daily_spend_d1_20": ("Your average spending per day so far this month: {value} BDT.",
                              "এই মাসে এ পর্যন্ত আপনার দৈনিক গড় খরচ: {value} টাকা।", 640),
    "total_inflow_d1_20": ("Money received so far this month: {value} BDT.",
                           "এই মাসে এ পর্যন্ত আসা টাকা: {value} টাকা।", 18500),
    "total_outflow_d1_20": ("Money out of your wallet so far this month, including fees: {value} BDT.",
                            "এই মাসে এ পর্যন্ত ফি সহ ওয়ালেট থেকে যাওয়া টাকা: {value} টাকা।", 15200),
    "cashout_count_d1_20": ("So far this month you made {value} cash-outs.",
                            "এই মাসে এ পর্যন্ত আপনি {value} বার ক্যাশ আউট করেছেন।", 3),
    "cashout_amount_d1_20": ("Cash taken out so far this month: {value} BDT.",
                             "এই মাসে এ পর্যন্ত নগদ তুলেছেন: {value} টাকা।", 17158),
    "days_since_last_inflow": ("Money last came in {value} days ago.",
                               "শেষবার টাকা এসেছে {value} দিন আগে।", 5),
    "days_since_last_inflow_none": ("No money has come in so far this month.",
                                    "এই মাসে এ পর্যন্ত কোনো টাকা আসেনি।", None),
    "days_since_last_inflow_today": ("Money came in today.",
                                     "আজ টাকা এসেছে।", None),
    "bill_payments_d1_20": ("So far this month you paid {value} bills.",
                            "এই মাসে এ পর্যন্ত আপনি {value}টি বিল পরিশোধ করেছেন।", 2),
    "inflow_vs_prev_month": ("Money received so far this month, compared with all of last month: {value}%.",
                             "গত মাসে মোট যত টাকা এসেছিল, এই মাসে এ পর্যন্ত তার {value}% এসেছে।", 85),
}
for _feature, (_en, _bn, _) in _REASON_FACTS.items():  # Build the "up" and "down" key for each fact.
    MESSAGES[f"reason_{_feature}_up"] = {"en": _en + _UP_EN, "bn": _bn + _UP_BN}
    MESSAGES[f"reason_{_feature}_down"] = {"en": _en + _DOWN_EN, "bn": _bn + _DOWN_BN}
# Last month's shortfall is a yes/no, so its wording follows the value (1 = up, 0 = down).
MESSAGES["reason_prev_month_shortfall_up"] = {
    "en": "Last month your balance ran low before the month ended." + _UP_EN,
    "bn": "গত মাসে মাস শেষ হওয়ার আগে আপনার ব্যালেন্স কমে গিয়েছিল।" + _UP_BN}
MESSAGES["reason_prev_month_shortfall_down"] = {
    "en": "Last month your balance did not run low." + _DOWN_EN,
    "bn": "গত মাসে আপনার ব্যালেন্স কমে যায়নি।" + _DOWN_BN}

# Western digits -> Bengali digits (০-৯).
_BENGALI_DIGITS = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")


class MissingValueError(ValueError):
    """Raised when a template is rendered without all the values it needs."""


def to_bengali_digits(text):
    """Turn 0-9 into Bengali digits."""
    return text.translate(_BENGALI_DIGITS)


def lakh_grouping(text):
    """Regroup a "200,000"-style number as 2,00,000 (last three digits, then pairs). Below 1,00,000 nothing changes."""
    whole, dot, fraction = text.partition(".")  # Only the whole part is grouped.
    sign = "-" if whole.startswith("-") else ""
    digits = whole.lstrip("-").replace(",", "")
    if len(digits) > 3:
        digits = re.sub(r"\B(?=(\d{2})+$)", ",", digits[:-3]) + "," + digits[-3:]  # Commas every two digits.
    return sign + digits + dot + fraction


def format_value(value, lang="en"):
    """Numbers get commas (en 200,000; bn 2,00,000); decimals keep only what is needed (1.5); text stays as is."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value)
    if float(value).is_integer():
        text = f"{int(value):,}"
    else:
        text = f"{value:,.2f}".rstrip("0").rstrip(".")
    return lakh_grouping(text) if lang == "bn" else text  # Bangla uses lakh grouping.


def placeholders(template):
    """The {names} a template needs."""
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


def render(key, lang, **values):
    """Fill a template in "en" or "bn" (anything else falls back to "en"). Missing values raise an error."""
    if key not in MESSAGES:
        raise KeyError(f"unknown message key: {key}")
    lang = lang if lang in cfg.LANGUAGES else "en"  # Fallback to English.
    template = MESSAGES[key][lang]
    missing = sorted(placeholders(template) - set(values))
    if missing:
        raise MissingValueError(f"message '{key}' needs value(s): {', '.join(missing)}")
    text = template.format(**{name: format_value(v, lang) for name, v in values.items()})
    if lang == "en":
        text = _SINGULAR_EN.sub(lambda m: "1 " + m.group(1)[:-1], text)  # "1 months" -> "1 month".
    if lang == "bn" and cfg.USE_BENGALI_DIGITS:
        text = to_bengali_digits(text)  # Bengali digits for Bangla text.
    return text


def sample_values():
    """One set of example values that fills every template (used by the self-check). Settings come from config."""
    return {"floor": cfg.SHORTFALL_FLOOR_BDT, "buffer": cfg.BUFFER_MIN_BDT * 3, "days": cfg.BUFFER_DAYS_OF_SPEND,
            "count": cfg.CASHOUT_SAVER_MIN_COUNT + 1, "fees": 120,
            "fee_rate": round(cfg.CASHOUT_FEE_RATE * 100, 2),
            "goal": 12000, "months": 6, "monthly": 2000, "capacity": 1500, "needed": 2000,
            "months_needed": 8, "max_months": cfg.SAVINGS_MAX_MONTHS, "saved": 36000,
            "start_day": 8, "end_day": 14, "amount": 6400, "total": 15200,
            "category": "shop payments", "category_amount": 7300, "value": 3250}


# Realistic preview values per key, so each sentence reads like a real case.
_PREVIEW_VALUES = {
    "cashout_saver": {"count": 3, "fees": 135},  # 3 cash-outs of about 3,000 BDT at the 1.5% placeholder.
    "savings_feasible": {"goal": 12000, "months": 6, "monthly": 2000, "capacity": 2500},  # 2,000 fits in 2,500.
    "savings_not_feasible": {"goal": 12000, "months": 6, "needed": 2000, "capacity": 1500, "months_needed": 8},
    "savings_not_reached": {"goal": 60000, "months": 6, "needed": 10000, "capacity": 1500,
                            "saved": 1500 * cfg.SAVINGS_MAX_MONTHS},  # 40 months needed, more than the maximum.
    "savings_option": {"monthly": 1500, "months": 8},
    "savings_option_not_reached": {"monthly": 750},
}

# Extra preview lines for singular and zero forms: (label, key, values).
_PREVIEW_EXTRAS = [
    ("1 cash-out", "reason_cashout_count_d1_20_up", {"value": 1}),
    ("0 cash-outs", "reason_cashout_count_d1_20_down", {"value": 0}),
    ("1 bill", "reason_bill_payments_d1_20_down", {"value": 1}),
    ("1 day", "reason_days_since_last_inflow_up", {"value": 1}),
    ("1 month", "savings_option", {"monthly": 6000, "months": 1}),
    ("lakh grouping", "savings_feasible", {"goal": 200000, "months": 24, "monthly": 8334, "capacity": 9000}),
]


def preview_values(key, lang):
    """Sample values for one key in one language: base values, then per-key and per-language ones."""
    values = {**sample_values(), **_PREVIEW_VALUES.get(key, {})}
    fact = re.sub(r"^reason_|_(up|down)$", "", key)  # e.g. reason_balance_day20_up -> balance_day20.
    if fact in _REASON_FACTS and _REASON_FACTS[fact][2] is not None:
        values["value"] = _REASON_FACTS[fact][2]  # A sensible number for this feature.
    values["category"] = MESSAGES["cat_merchant"][lang]  # Category name in the same language.
    return values


def preview_lines(title, key, en_values, bn_values):
    """One Markdown section with the en and bn sentence."""
    return [f"## {title}", "", f"- en: {render(key, 'en', **en_values)}",
            f"- bn: {render(key, 'bn', **bn_values)}", ""]


def write_preview(path=cfg.PROJECT_ROOT / "docs" / "messages_preview.md"):
    """Write every message in both languages, filled with sample values, to a UTF-8 Markdown file."""
    lines = ["# Messages preview (sample values only)", "",
             "Generated by `python -m src.i18n.messages`. All data is simulated. The numbers are examples.", ""]
    for key in MESSAGES:
        lines += preview_lines(key, key, preview_values(key, "en"), preview_values(key, "bn"))
    lines += ["# Singular, zero and large-number samples", ""]
    for label, key, extra in _PREVIEW_EXTRAS:
        lines += preview_lines(f"{key} ({label})", key, {**preview_values(key, "en"), **extra},
                               {**preview_values(key, "bn"), **extra})
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


if __name__ == "__main__":
    out = write_preview()
    print(f"Wrote {len(MESSAGES)} keys in en and bn to {out.relative_to(cfg.PROJECT_ROOT)}")  # No Bangla printed.
