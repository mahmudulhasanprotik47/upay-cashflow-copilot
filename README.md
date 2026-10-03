# upay Smart Cash-Flow Copilot

**Team:** TriStack
**Event:** AI Dev Fest 2026, AI Hackathon (DIU CPC × upay)
**Track:** Track 03, Customer Innovation & Financial Independence

## What it is

A prototype for the upay wallet. On day 20 of a month it predicts whether a
simulated wallet balance will drop below 500 BDT on days 21-30. It explains why
in English and বাংলা, then suggests a buffer, a cash-out fee saver and a
savings plan. These are suggestions only. The user decides. Nothing happens
automatically.

**All data is simulated. No real upay customer data is used.**

## What is inside

- A seeded data generator (1,000 simulated users, 6 months).
- An XGBoost model with SHAP reasons. The buffer, fee saver and savings plan
  are rules, not model output. Messages are fixed templates. There is no LLM.
- A FastAPI service and one self-contained web page with two tabs:
  Wallet, and Results (for judges, English only).
- 6 one-click demo cases and 16 self-checks.

## Honest results

On simulated data the model's lead over a simple day-20 balance rule is small
and not statistically clear. Its measurable extras are a minimum-balance
estimate and a reason for every alert. See the Results tab and
`docs/model_card.md`. The cash-out fee rate in the code (1.5%) is a placeholder.

## Quick start (Windows PowerShell)

Tested on Python 3.14.8. Other versions are untested.

```
git clone https://github.com/mahmudulhasanprotik47/upay-cashflow-copilot
cd upay-cashflow-copilot
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m src.data.generator
python -m src.api.service
python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000
```

Then open http://127.0.0.1:8000/ in a browser.

- `python -m src.data.generator` creates the simulated data in `data/`.
- `python -m src.api.service` runs the 16 self-checks. All should pass.
- Use months 4 and 5 for demos (months 0-3 were used for training).

## Docs

- `docs/model_card.md`: model, results, limits
- `docs/target_definition.md`: what "shortfall" means
- `docs/api_contract.md`: API responses
- `docs/synthetic_assumptions.md` and `docs/data_assumptions.md`: simulator assumptions

## Team

- Mahmudul Hasan: build
- Fahim Montasir: research
- Ahsanur Rahman Nakib: slides and presentation