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
