# Central settings for the upay Smart Cash-Flow Copilot. All data is simulated.
# Change values here to change the behaviour everywhere else in the project.

from pathlib import Path  # Standard tool for building file paths that work on any OS.

# Project root folder (one level above src/), so paths work from anywhere.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

SEED = 42  # Random seed so every run produces the same simulated data and results.
N_USERS = 1000  # Number of simulated upay users to generate.
N_MONTHS = 6  # Number of simulated months of history per user.
DAYS_IN_MONTH = 30  # Every simulated month has this many days, to keep things simple.
PREDICTION_DAY = 20  # We predict at the end of this day, using only days 1 to this day.
SHORTFALL_FLOOR_BDT = 500  # A user is flagged if their balance falls below this many BDT after the prediction day.
TEST_MONTHS = 2  # The latest this-many months are held out for testing; earlier months are for training.
SAVINGS_CAP_FRACTION = 0.5  # A savings suggestion never exceeds this share of the user's predicted safe surplus.
CASHOUT_FEE_RATE = 0.015  # ASSUMPTION placeholder. Researcher must replace with a sourced figure from upay's official site.
FAIRNESS_COLUMNS = ["income_band", "region", "age_band"]  # Groups we compare results across; never used as model inputs.
LANGUAGES = ["en", "bn"]  # Supported languages: English and Bangla.

DATA_DIR = PROJECT_ROOT / "data"  # Folder for generated simulated data (ignored by git).
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"  # Folder for saved models, metrics and other outputs.

# ---------------------------------------------------------------------------
# Phase 1: synthetic data generator knobs. Every value is an ASSUMPTION.
# ---------------------------------------------------------------------------

# Who the simulated users are.
REGIONS = ["Dhaka", "Chattogram", "Khulna", "Rajshahi", "Sylhet"]  # The 5 simulated regions.
REGION_SHARES = [0.35, 0.20, 0.15, 0.15, 0.15]  # Share of users living in each region.
AGE_BANDS = ["18-25", "26-35", "36-50", "51+"]  # The 4 simulated age bands.
AGE_BAND_SHARES = [0.25, 0.35, 0.28, 0.12]  # Share of users in each age band.
INCOME_BANDS = ["low", "mid", "high"]  # The 3 simulated income bands.
INCOME_BAND_SHARES = [0.45, 0.40, 0.15]  # Share of users in each income band (before the city shift below).
CITY_HIGH_INCOME_SHIFT = 0.05  # In Dhaka and Chattogram this share moves from "low" to "high" income.
INCOME_BAND_RANGES_BDT = {"low": (8000, 15000), "mid": (15000, 35000), "high": (35000, 80000)}  # Monthly income range per band.
INCOME_TYPES = ["salaried", "gig", "business"]  # Salaried, gig/irregular, small business.
INCOME_TYPE_SHARES = [0.55, 0.30, 0.15]  # Share of users with each income type.
INCOME_NOISE_SD = {"salaried": 0.03, "gig": 0.30, "business": 0.20}  # Month-to-month wobble in income, per type.

# Habits each user gets once (drawn from these ranges).
SALARY_DAY_RANGE = (1, 7)  # Salaried users are normally paid on one fixed day in this range.
OPENING_BALANCE_SHARE_RANGE = (0.10, 0.50)  # Starting wallet balance, as a share of monthly income.
BILL_LOAD_RANGE = (0.08, 0.20)  # Share of monthly income paid as regular bills.
CASHOUT_HABIT_RANGE = (0.20, 0.60)  # Share of each income payment the user cashes out at an agent.
FAMILY_SEND_SHARE_RANGE = (0.05, 0.15)  # Share of each income payment sent to family.
RECHARGE_SHARE = 0.03  # Share of monthly income spent on mobile recharge.
SPEND_RATIO_MEAN = 0.85  # Average planned total outflow in a month, as a share of usual income.
SPEND_RATIO_SD = 0.06  # How much that planned outflow varies from month to month.
MERCHANT_DAY_PROB = 0.6  # Chance the user pays a merchant on any given day.
ADD_MONEY_PROB = 0.30  # Chance per month that the user tops up from a bank or card.
ADD_MONEY_SHARE = 0.05  # Size of that top-up, as a share of monthly income.
SWEEP_BALANCE_MONTHS = 1.0  # On day 1, a balance above this many months of income is cashed out (kept elsewhere).
AGENT_CHANNEL_PROB = 0.4  # Chance a gig or business income payment comes in through an agent, not the app.

# Stress mechanisms (stress only comes from these, never from a stamped label).
LATE_SALARY_PROB = 0.12  # Chance per month that a salaried user's pay is late.
LATE_SALARY_DELAY_DAYS = (3, 22)  # How many days late it can be (so sometimes after day 20).
GIG_PAYMENTS_RANGE = (4, 10)  # Number of separate payments a gig user gets in a month.
GIG_THIN_MONTH_PROB = 0.20  # Chance per month that a gig user has a thin month.
GIG_THIN_MONTH_FACTOR = 0.6  # In a thin month, gig income is multiplied by this.
BUSINESS_RECEIPTS_PER_MONTH = 4  # Small-business users receive money about this many times a month.
BILL_SHOCK_PROB = 0.20  # Chance per month of a one-off large bill.
BILL_SHOCK_MULT = 4.0  # A bill shock is this many times the user's normal monthly bill load.
FAMILY_EMERGENCY_PROB = 0.15  # Chance per month of an emergency send to family.
FAMILY_EMERGENCY_SHARE = 0.50  # Size of an emergency send, as a share of monthly income.
FESTIVAL_MONTH_INDEX = 3  # Which simulated month (0-based) is the festival month.
FESTIVAL_FAMILY_MULT = 2.0  # Family sends are multiplied by this in the festival month.
FESTIVAL_SHOPPING_MULT = 1.4  # Merchant spending is multiplied by this in the festival month.

# ---------------------------------------------------------------------------
# Phase 2: model settings. Fixed in advance, never tuned on the test months.
# ---------------------------------------------------------------------------
MODEL_N_ESTIMATORS = 300  # Number of trees in each XGBoost model.
MODEL_MAX_DEPTH = 4  # Maximum depth of each tree.
MODEL_LEARNING_RATE = 0.05  # How much each new tree corrects the previous ones.
TOP_REASONS = 3  # How many reasons we show with each prediction.
ALERT_THRESHOLD_OVERRIDE = None  # If set (e.g. 0.4), replaces the learned alert threshold everywhere.
BOOTSTRAP_RESAMPLES = 200  # Number of user-level bootstrap resamples for confidence intervals.
MIN_GROUP_ROWS = 150  # Fairness groups with fewer test rows than this are marked LOW SAMPLE.

# ---------------------------------------------------------------------------
# Phase 3: suggestion rules, messages and API.
# ---------------------------------------------------------------------------
RISK_BAND_HIGH_PROB = 0.6  # An alert with a chance at or above this is shown as "High", below it as "Medium".
BUFFER_ROUND_BDT = 500  # Buffer amounts (and the shown minimum balance) are rounded to this many BDT.
BUFFER_MIN_BDT = 500  # A suggested buffer is never smaller than this.
CASHOUT_SAVER_MIN_COUNT = 2  # The cash-out fee tip only appears with at least this many cash-outs on days 1-20.
CASHOUT_SAVER_EXCLUDE_DAY1 = True  # Leave day-1 cash-outs out of the tip (they are mostly balance sweeps).
SAVINGS_MAX_MONTHS = 24  # A savings plan never runs longer than this many months.
USE_BENGALI_DIGITS = True  # Show Bangla messages with Bengali digits.
WHATIF_MAX_BDT = 500000  # Largest value accepted for a what-if input (and for a savings goal).
API_HOST = "127.0.0.1"  # The API only listens on this computer.
API_PORT = 8000  # Port the API listens on.
CORS_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000",
                "http://localhost:8000", "http://127.0.0.1:8000"]  # Web pages allowed to call the API.
BANNED_WORDS_EN = ["hurry", "urgent", "act now", "last chance", "don't miss",
                   "limited time", "immediately", "panic", "guaranteed"]  # Pressure words never used in messages.
WHATIF_SAME_TOLERANCE = 0.02  # A what-if risk change smaller than this (internally) is shown as "about the same".

# ---------------------------------------------------------------------------
# Phase 3 fix: Bangla pressure words, causal words and the buffer rule.
# ---------------------------------------------------------------------------
BANNED_WORDS_BN = ["এখনই", "জরুরি", "তাড়াতাড়ি", "অবিলম্বে", "শেষ সুযোগ", "সীমিত সময়"]  # Bangla pressure words never used in messages.
CAUSAL_WORDS_EN = ["pushes", "helps", "reduces", "causes", "improves"]  # Reasons never claim a cause (English).
CAUSAL_WORDS_BN = ["বাড়ায়", "বাড়াতে", "কমায়", "কমাতে", "সাহায্য", "কারণে", "উন্নত"]  # Reasons never claim a cause (Bangla).
BUFFER_DAYS_OF_SPEND = 3  # ASSUMPTION: the suggested buffer is this many days of the user's own average daily spending.
