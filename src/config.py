# Central settings for the upay Smart Cash-Flow Copilot. All data is simulated.
# Change values here to change the behaviour everywhere else in the project.

import os  # Reads the optional database path from the environment.
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
SAVINGS_CAP_FRACTION = 0.5  # Savings capacity = this share of the user's average monthly net (money in minus out) over earlier months, day-1 cash-outs left out.
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
CASHOUT_SAVER_MIN_COUNT = 2  # The cash-out fee tip only appears with at least this many cash-outs on days 2-20 (day 1 is left out, see below).
CASHOUT_SAVER_EXCLUDE_DAY1 = True  # Leave day-1 cash-outs out of the tip (they are mostly balance sweeps).
SAVINGS_MAX_MONTHS = 24  # A savings plan never runs longer than this many months.
USE_BENGALI_DIGITS = True  # Show Bangla messages with Bengali digits.
WHATIF_MAX_BDT = 500000  # Largest value accepted for a what-if input (and for a savings goal).
API_HOST = "127.0.0.1"  # The API only listens on this computer.
API_PORT = 8000  # Port the API listens on.
CORS_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000",
                "http://localhost:8000", "http://127.0.0.1:8000"]  # Web pages allowed to call the API.
BANNED_WORDS_EN = ["hurry", "urgent", "act now", "last chance", "don't miss",
                   "limited time", "immediately", "panic", "guaranteed",
                   "fraud", "suspicious"]  # Pressure and accusing words never used in messages.
WHATIF_SAME_TOLERANCE = 0.02  # A what-if risk change smaller than this (internally) is shown as "about the same".

# ---------------------------------------------------------------------------
# Phase 3 fix: Bangla pressure words, causal words and the buffer rule.
# ---------------------------------------------------------------------------
BANNED_WORDS_BN = ["এখনই", "জরুরি", "তাড়াতাড়ি", "অবিলম্বে", "শেষ সুযোগ", "সীমিত সময়"]  # Bangla pressure words never used in messages.
CAUSAL_WORDS_EN = ["pushes", "helps", "reduces", "causes", "improves"]  # Reasons never claim a cause (English).
CAUSAL_WORDS_BN = ["বাড়ায়", "বাড়াতে", "কমায়", "কমাতে", "সাহায্য", "কারণে", "উন্নত"]  # Reasons never claim a cause (Bangla).
BUFFER_DAYS_OF_SPEND = 3  # ASSUMPTION: the suggested buffer is this many days of the user's own average daily spending.

# ---------------------------------------------------------------------------
# Phase 2A: database, accounts, sessions, API keys, rate limits.
# ---------------------------------------------------------------------------
# SQLite file (ignored by git). Holds accounts, consents, live data and logs. COPILOT_DB_PATH can point a
# test server at a throwaway file instead.
DB_PATH = Path(os.environ.get("COPILOT_DB_PATH") or DATA_DIR / "copilot.db")
DB_SCHEMA_VERSION = 1  # Stored in the database; raise it when the tables change.
ROLES = ["admin", "analyst", "customer"]  # Who can sign in. Customers are linked to one simulated user_id.
ADMIN_USERNAME = "admin"  # Username of the first admin, created on the first start.
ADMIN_PASSWORD_ENV = "COPILOT_ADMIN_PASSWORD"  # Environment variable with the first admin's password.
PASSWORD_MIN_LENGTH = 10  # Shortest password accepted when an account is created or reset.
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 14, 8, 1  # Cost settings for the scrypt password hash (about 16 MB each).
SESSION_COOKIE = "copilot_session"  # Name of the HttpOnly session cookie.
SESSION_HOURS = 8  # A session ends after this many hours.
LOGIN_MAX_FAILURES = 5  # This many wrong passwords in a row lock the account...
LOCKOUT_MINUTES = 5  # ...for this many minutes.
RATE_WINDOW_SECONDS = 60  # Length of the sliding window for rate limits.
RATE_LIMIT_SESSION = 300  # Requests per window for one signed-in session.
RATE_LIMIT_API_KEY = 3000  # Requests per window for one API key (machine clients send more).
RATE_LIMIT_IP = 120  # Requests per window from one IP address without a session or key.
RATE_LIMIT_LOGIN = 10  # Sign-in attempts per window from one IP address (on top of the limits above).
AUDIT_PAGE_SIZE = 100  # Most audit entries returned at once.
FEATURE_SWITCHES = ["live_transactions", "budget_warnings", "unusual_check"]  # Admin can turn these off.

# ---------------------------------------------------------------------------
# Phase 2B: live transactions, consent, budgets, unusual-activity check.
# ---------------------------------------------------------------------------
LIVE_TYPES = {"salary_or_income": "in", "add_money": "in", "merchant_payment": "out",
              "bill_payment": "out", "mobile_recharge": "out", "send_money_family": "out",
              "cash_out": "out"}  # The 7 transaction types in the simulated data, with their direction.
LIVE_MAX_AMOUNT_BDT = 200000  # Largest single live transaction accepted (whole BDT).
CONSENT_NOTICE_VERSION = "2026-10-v1"  # Version of the data notice; change it when the notice text changes.
BUDGET_TYPES = ["merchant_payment", "bill_payment", "mobile_recharge", "send_money_family",
                "cash_out"]  # Spending types that get a monthly budget bar.
BUDGET_CLOSE_SHARE = 0.8  # A budget bar shows "close to budget" from this share of the budget.
ANOMALY_TRAIN_FLAG_RATE = 0.01  # The unusual-activity cut flags this share of training transactions.
ANOMALY_INJECTED_ROWS = 500  # Artificial outliers injected into a copy of the test months for evaluation.
ANOMALY_INJECT_MULT = (5.0, 10.0)  # Injected outliers are this many times a real transaction's amount.
ANOMALY_DIR = ARTIFACTS_DIR / "anomaly"  # Saved unusual-activity model and its evaluation.

# ---------------------------------------------------------------------------
# Phase 2E/2D: integration events, load test, challenger experiment.
# ---------------------------------------------------------------------------
INTEGRATION_MAX_BATCH = 500  # Most transactions accepted in one POST /integration/events batch.
LOAD_TEST_FILE = ARTIFACTS_DIR / "load_test.json"  # Written by scripts/load_test.py.
CHALLENGER_DIR = ARTIFACTS_DIR / "challenger"  # Written by python -m src.models.tune_challenger.
CHALLENGER_TRIALS = 30  # Random-search settings tried for the challenger (training months only).
