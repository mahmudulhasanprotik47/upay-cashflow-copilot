# API contract (Phase 3)

All data is **simulated**. Nothing in this API moves money: every suggestion has
`"requires_user_confirmation": true` and `"auto_action": false`.

- Base URL: `http://127.0.0.1:8000`
- Run: `python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000`
- CORS: only `http://localhost:3000`, `http://127.0.0.1:3000`, `http://localhost:8000`, `http://127.0.0.1:8000`.
- `lang` is `en` or `bn`. Bangla text uses Bengali digits (`USE_BENGALI_DIGITS`) and lakh grouping from
  1,00,000 up (200000 is `২,০০,০০০` in Bangla, `200,000` in English). Number fields are plain JSON numbers.
- Every example below was copied from a real run. Long lists are cut where marked.

## Rules the frontend can rely on

- **No probability is ever returned.** Show `risk_band` / `risk_band_text` only (the model is over-confident in the middle).
- `predicted_min_balance` and the `buffer` suggestion appear **only when `alert` is true**. With no alert they are `null` / absent.
- `predicted_min_balance` is also `null` when `alert` is true but the helper model's shown minimum is at or above
  `floor_bdt` (the two models disagree, so nothing is shown). When shown, it carries `typical_error_bdt`.
- **The buffer is a rule, not a model output.** It is `BUFFER_DAYS_OF_SPEND` (3, an ASSUMPTION) days of the
  user's own average daily spending on days 1-20, rounded up to 500 BDT, at least 500 BDT, never more than
  `balance_day20` rounded down to 500 BDT. If that cap is 0 there is no buffer (`no_buffer_low_balance` note).
  The helper model only gives the minimum-balance estimate. Buffer texts carry no error sentence, and the
  buffer has no `is_estimate` (only `predicted_min_balance` does).
- `capped_by_balance` is `false` when the 3 days of spending fit within the balance: the text then says
  "roughly 3 days of your usual spending". It is `true` when the balance limits the buffer: the text then says
  "close to your current balance" and makes no days claim.
- A user with an alert never gets a savings plan (`status: "blocked_alert"`).
- `income_band`, `region` and `age_band` never appear in any response except the fairness numbers in `/model-results` and `/results`.
- `month_in_training` is `true` for months 0-3. Prefer months 4-5 (test months) in the demo.
- Money values are whole BDT. `fee_rate_pct` is a placeholder rate (see `fee_rate_label`).

---

## GET /health

Is the server up? Also returns how long the start-up load took.

Request: `GET /health`

```json
{
  "status": "ok",
  "startup_seconds": 5.31
}
```

Errors: none in normal use.

---

## GET /users

All user ids with their income type, for a dropdown. No fairness columns.

Request: `GET /users`

Response (first 3 of 1000 shown):

```json
[
  {
    "user_id": 1,
    "income_type": "gig"
  },
  {
    "user_id": 2,
    "income_type": "salaried"
  },
  {
    "user_id": 3,
    "income_type": "salaried"
  }
]
```

Errors: see Common errors.

---

## GET /users/{user_id}/months/{month}/forecast?lang=en|bn

The main screen: risk band, top reasons (in the user's own numbers), suggestions, notes, the balance
for days 1-20 (for a chart) and the disclaimer.

- `reasons`: up to 3. A reason whose value is blank (e.g. month 0 has no last month) is skipped, so there can be fewer.
  `direction` is `up` (goes with higher risk in this simulated data) or `down` (goes with lower risk). It is
  not a cause. `unit` is `BDT`, `count` or `percent`. `days_since_last_inflow` 20 means nothing came in on days
  1-20 ("No money has come in so far this month"); 0 means "Money came in today".
- `suggestions`: `buffer` (only with an alert, only if the balance allows one; `days_of_spend` is the rule's
  number of days; `capped_by_balance` picks the wording, see above) and `cashout_saver`
  (only with at least 2 cash-outs on days 2-20). Each has its own `text`.
- `notes`: `shortfall_warning` and `savings_blocked_alert` with an alert, plus `no_buffer_low_balance` when the
  balance is too small for a buffer. Empty with no alert.

### Example 1: alert (Medium), English, minimum balance not shown

The helper model's minimum for this user-month is at or above the floor, so `predicted_min_balance` is `null`
even though `alert` is true. The buffer (rule) is still given. Three days of spending (3 x 1,292 = 3,876 BDT) do not
fit in the 3,308 BDT balance, so the buffer is capped at 3,000 BDT and uses the "close to your current
balance" wording.

Request: `GET /users/1/months/4/forecast?lang=en`

```json
{
  "user_id": 1,
  "month": 4,
  "lang": "en",
  "month_in_training": false,
  "risk_band": "medium",
  "risk_band_text": "Medium risk: your balance may run low before the month ends.",
  "alert": true,
  "floor_bdt": 500,
  "predicted_min_balance": null,
  "reasons": [
    {
      "feature": "avg_daily_spend_d1_20",
      "value": 1292,
      "unit": "BDT",
      "direction": "up",
      "text": "Your average spending per day so far this month: 1,292 BDT. In this simulated data, this goes with higher risk."
    },
    {
      "feature": "total_inflow_d1_20",
      "value": 35552,
      "unit": "BDT",
      "direction": "up",
      "text": "Money received so far this month: 35,552 BDT. In this simulated data, this goes with higher risk."
    },
    {
      "feature": "days_since_last_inflow",
      "value": 7,
      "unit": "count",
      "direction": "down",
      "text": "Money last came in 7 days ago. In this simulated data, this goes with lower risk."
    }
  ],
  "suggestions": [
    {
      "type": "buffer",
      "amount_bdt": 3000,
      "days_of_spend": 3,
      "capped_by_balance": true,
      "text": "Idea: keep about 3,000 BDT, close to your current balance, unspent until the month ends.",
      "requires_user_confirmation": true,
      "auto_action": false
    },
    {
      "type": "cashout_saver",
      "cashout_count": 5,
      "fees_paid_bdt": 274,
      "fee_rate_pct": 1.5,
      "fee_rate_label": "assumed fee rate (placeholder, not yet sourced)",
      "requires_user_confirmation": true,
      "auto_action": false,
      "text": "So far this month you made 5 cash-outs and paid 274 BDT in fees (assumed fee rate 1.5%, a placeholder, not yet sourced). If some of these payments could be made from the wallet, you could avoid up to about 274 BDT in fees. Cash-out is fine when you need cash."
    }
  ],
  "notes": [
    {
      "type": "shortfall_warning",
      "text": "Our estimate is that your balance could drop below 500 BDT before the month ends. You can plan for this now."
    },
    {
      "type": "savings_blocked_alert",
      "text": "Because your balance may run low this month, we are not suggesting savings right now. You may want to keep a buffer first."
    }
  ],
  "balance_by_day": [
    {
      "day": 1,
      "balance_bdt": 11871
    },
    {
      "day": 2,
      "balance_bdt": 13651
    },
    {
      "day": 3,
      "balance_bdt": 18774
    },
    {
      "day": 4,
      "balance_bdt": 18644
    },
    {
      "day": 5,
      "balance_bdt": 18644
    },
    {
      "day": 6,
      "balance_bdt": 18298
    },
    {
      "day": 7,
      "balance_bdt": 17854
    },
    {
      "day": 8,
      "balance_bdt": 0
    },
    {
      "day": 9,
      "balance_bdt": 0
    },
    {
      "day": 10,
      "balance_bdt": 0
    },
    {
      "day": 11,
      "balance_bdt": 11276
    },
    {
      "day": 12,
      "balance_bdt": 6992
    },
    {
      "day": 13,
      "balance_bdt": 7772
    },
    {
      "day": 14,
      "balance_bdt": 4230
    },
    {
      "day": 15,
      "balance_bdt": 4078
    },
    {
      "day": 16,
      "balance_bdt": 3601
    },
    {
      "day": 17,
      "balance_bdt": 3312
    },
    {
      "day": 18,
      "balance_bdt": 3308
    },
    {
      "day": 19,
      "balance_bdt": 3308
    },
    {
      "day": 20,
      "balance_bdt": 3308
    }
  ],
  "disclaimer": "This is an estimate from simulated data, not a guarantee. You decide."
}
```

### Example 2: same user-month in Bangla

Request: `GET /users/1/months/4/forecast?lang=bn`

```json
{
  "user_id": 1,
  "month": 4,
  "lang": "bn",
  "month_in_training": false,
  "risk_band": "medium",
  "risk_band_text": "মাঝারি ঝুঁকি: মাস শেষ হওয়ার আগে আপনার ব্যালেন্স কমে যেতে পারে।",
  "alert": true,
  "floor_bdt": 500,
  "predicted_min_balance": null,
  "reasons": [
    {
      "feature": "avg_daily_spend_d1_20",
      "value": 1292,
      "unit": "BDT",
      "direction": "up",
      "text": "এই মাসে এ পর্যন্ত আপনার দৈনিক গড় খরচ: ১,২৯২ টাকা। এই সিমুলেটেড ডেটায় এটি বেশি ঝুঁকির সাথে দেখা যায়।"
    },
    {
      "feature": "total_inflow_d1_20",
      "value": 35552,
      "unit": "BDT",
      "direction": "up",
      "text": "এই মাসে এ পর্যন্ত আসা টাকা: ৩৫,৫৫২ টাকা। এই সিমুলেটেড ডেটায় এটি বেশি ঝুঁকির সাথে দেখা যায়।"
    },
    {
      "feature": "days_since_last_inflow",
      "value": 7,
      "unit": "count",
      "direction": "down",
      "text": "শেষবার টাকা এসেছে ৭ দিন আগে। এই সিমুলেটেড ডেটায় এটি কম ঝুঁকির সাথে দেখা যায়।"
    }
  ],
  "suggestions": [
    {
      "type": "buffer",
      "amount_bdt": 3000,
      "days_of_spend": 3,
      "capped_by_balance": true,
      "text": "পরামর্শ: মাস শেষ হওয়া পর্যন্ত প্রায় ৩,০০০ টাকা, যা আপনার বর্তমান ব্যালেন্সের কাছাকাছি, খরচ না করে হাতে রাখতে পারেন।",
      "requires_user_confirmation": true,
      "auto_action": false
    },
    {
      "type": "cashout_saver",
      "cashout_count": 5,
      "fees_paid_bdt": 274,
      "fee_rate_pct": 1.5,
      "fee_rate_label": "assumed fee rate (placeholder, not yet sourced)",
      "requires_user_confirmation": true,
      "auto_action": false,
      "text": "এই মাসে এ পর্যন্ত আপনি ৫ বার ক্যাশ আউট করেছেন এবং ফি দিয়েছেন ২৭৪ টাকা (ধরে নেওয়া ফি হার ১.৫%, এটি অস্থায়ী, এখনো যাচাই করা হয়নি)। এর কিছু পেমেন্ট যদি ওয়ালেট থেকে করা যায়, তাহলে প্রায় ২৭৪ টাকা পর্যন্ত ফি বাঁচাতে পারেন। নগদ টাকার দরকার হলে ক্যাশ আউট করায় কোনো সমস্যা নেই।"
    }
  ],
  "notes": [
    {
      "type": "shortfall_warning",
      "text": "আমাদের অনুমান, মাস শেষ হওয়ার আগে আপনার ব্যালেন্স ৫০০ টাকার নিচে নেমে যেতে পারে। আপনি এখন থেকেই এর জন্য পরিকল্পনা করতে পারেন।"
    },
    {
      "type": "savings_blocked_alert",
      "text": "এই মাসে আপনার ব্যালেন্স কমে যেতে পারে, তাই এখন আমরা সঞ্চয়ের পরামর্শ দিচ্ছি না। আগে কিছু টাকা হাতে রাখার কথা ভাবতে পারেন।"
    }
  ],
  "balance_by_day": [
    {
      "day": 1,
      "balance_bdt": 11871
    },
    {
      "day": 2,
      "balance_bdt": 13651
    },
    {
      "day": 3,
      "balance_bdt": 18774
    },
    {
      "day": 4,
      "balance_bdt": 18644
    },
    {
      "day": 5,
      "balance_bdt": 18644
    },
    {
      "day": 6,
      "balance_bdt": 18298
    },
    {
      "day": 7,
      "balance_bdt": 17854
    },
    {
      "day": 8,
      "balance_bdt": 0
    },
    {
      "day": 9,
      "balance_bdt": 0
    },
    {
      "day": 10,
      "balance_bdt": 0
    },
    {
      "day": 11,
      "balance_bdt": 11276
    },
    {
      "day": 12,
      "balance_bdt": 6992
    },
    {
      "day": 13,
      "balance_bdt": 7772
    },
    {
      "day": 14,
      "balance_bdt": 4230
    },
    {
      "day": 15,
      "balance_bdt": 4078
    },
    {
      "day": 16,
      "balance_bdt": 3601
    },
    {
      "day": 17,
      "balance_bdt": 3312
    },
    {
      "day": 18,
      "balance_bdt": 3308
    },
    {
      "day": 19,
      "balance_bdt": 3308
    },
    {
      "day": 20,
      "balance_bdt": 3308
    }
  ],
  "disclaimer": "এটি সিমুলেটেড ডেটা থেকে করা একটি অনুমান, কোনো নিশ্চয়তা নয়। সিদ্ধান্ত আপনার।"
}
```

### Example 3: alert with the minimum balance shown

Request: `GET /users/20/months/4/forecast?lang=en` (`balance_by_day` cut to 3 days)

```json
{
  "user_id": 20,
  "month": 4,
  "lang": "en",
  "month_in_training": false,
  "risk_band": "high",
  "risk_band_text": "High risk: your balance is likely to run low before the month ends.",
  "alert": true,
  "floor_bdt": 500,
  "predicted_min_balance": {
    "amount_bdt": 0,
    "is_estimate": true,
    "typical_error_bdt": 2153
  },
  "reasons": [
    {
      "feature": "balance_day20",
      "value": 592,
      "unit": "BDT",
      "direction": "up",
      "text": "Your current balance: 592 BDT. In this simulated data, this goes with higher risk."
    },
    {
      "feature": "total_inflow_d1_20",
      "value": 12777,
      "unit": "BDT",
      "direction": "up",
      "text": "Money received so far this month: 12,777 BDT. In this simulated data, this goes with higher risk."
    },
    {
      "feature": "bill_payments_d1_20",
      "value": 1,
      "unit": "count",
      "direction": "up",
      "text": "So far this month you paid 1 bill. In this simulated data, this goes with higher risk."
    }
  ],
  "suggestions": [
    {
      "type": "buffer",
      "amount_bdt": 500,
      "days_of_spend": 3,
      "capped_by_balance": true,
      "text": "Idea: keep about 500 BDT, close to your current balance, unspent until the month ends.",
      "requires_user_confirmation": true,
      "auto_action": false
    }
  ],
  "notes": [
    {
      "type": "shortfall_warning",
      "text": "Our estimate is that your balance could drop below 500 BDT before the month ends. You can plan for this now."
    },
    {
      "type": "savings_blocked_alert",
      "text": "Because your balance may run low this month, we are not suggesting savings right now. You may want to keep a buffer first."
    }
  ],
  "balance_by_day": [
    {
      "day": 1,
      "balance_bdt": 1874
    },
    {
      "day": 2,
      "balance_bdt": 1874
    },
    {
      "day": 3,
      "balance_bdt": 1850
    }
  ],
  "disclaimer": "This is an estimate from simulated data, not a guarantee. You decide."
}
```

### Example 3b: alert with an uncapped buffer

Three days of spending (3 x 288 = 864, rounded up to 1,000 BDT) fit within the 2,675 BDT balance, so
`capped_by_balance` is `false` and the text keeps the "3 days" wording.

Request: `GET /users/8/months/4/forecast?lang=en` (`balance_by_day` cut to 3 days)

```json
{
  "user_id": 8,
  "month": 4,
  "lang": "en",
  "month_in_training": false,
  "risk_band": "medium",
  "risk_band_text": "Medium risk: your balance may run low before the month ends.",
  "alert": true,
  "floor_bdt": 500,
  "predicted_min_balance": null,
  "reasons": [
    {
      "feature": "cashout_amount_d1_20",
      "value": 2101,
      "unit": "BDT",
      "direction": "up",
      "text": "Cash taken out so far this month: 2,101 BDT. In this simulated data, this goes with higher risk."
    },
    {
      "feature": "avg_daily_spend_d1_20",
      "value": 288,
      "unit": "BDT",
      "direction": "down",
      "text": "Your average spending per day so far this month: 288 BDT. In this simulated data, this goes with lower risk."
    },
    {
      "feature": "balance_day20",
      "value": 2675,
      "unit": "BDT",
      "direction": "down",
      "text": "Your current balance: 2,675 BDT. In this simulated data, this goes with lower risk."
    }
  ],
  "suggestions": [
    {
      "type": "buffer",
      "amount_bdt": 1000,
      "days_of_spend": 3,
      "capped_by_balance": false,
      "text": "Idea: keep about 1,000 BDT, roughly 3 days of your usual spending, unspent until the month ends.",
      "requires_user_confirmation": true,
      "auto_action": false
    },
    {
      "type": "cashout_saver",
      "cashout_count": 7,
      "fees_paid_bdt": 32,
      "fee_rate_pct": 1.5,
      "fee_rate_label": "assumed fee rate (placeholder, not yet sourced)",
      "requires_user_confirmation": true,
      "auto_action": false,
      "text": "So far this month you made 7 cash-outs and paid 32 BDT in fees (assumed fee rate 1.5%, a placeholder, not yet sourced). If some of these payments could be made from the wallet, you could avoid up to about 32 BDT in fees. Cash-out is fine when you need cash."
    }
  ],
  "notes": [
    {
      "type": "shortfall_warning",
      "text": "Our estimate is that your balance could drop below 500 BDT before the month ends. You can plan for this now."
    },
    {
      "type": "savings_blocked_alert",
      "text": "Because your balance may run low this month, we are not suggesting savings right now. You may want to keep a buffer first."
    }
  ],
  "balance_by_day": [
    {
      "day": 1,
      "balance_bdt": 712
    },
    {
      "day": 2,
      "balance_bdt": 3472
    },
    {
      "day": 3,
      "balance_bdt": 3472
    }
  ],
  "disclaimer": "This is an estimate from simulated data, not a guarantee. You decide."
}
```

### Example 4: no alert (Low), `predicted_min_balance` is null

Request: `GET /users/1/months/5/forecast?lang=en` (`balance_by_day` cut to 3 days)

```json
{
  "user_id": 1,
  "month": 5,
  "lang": "en",
  "month_in_training": false,
  "risk_band": "low",
  "risk_band_text": "Low risk: your balance looks on track for the rest of the month.",
  "alert": false,
  "floor_bdt": 500,
  "predicted_min_balance": null,
  "reasons": [
    {
      "feature": "balance_day20",
      "value": 13864,
      "unit": "BDT",
      "direction": "down",
      "text": "Your current balance: 13,864 BDT. In this simulated data, this goes with lower risk."
    },
    {
      "feature": "total_inflow_d1_20",
      "value": 39282,
      "unit": "BDT",
      "direction": "up",
      "text": "Money received so far this month: 39,282 BDT. In this simulated data, this goes with higher risk."
    },
    {
      "feature": "cashout_amount_d1_20",
      "value": 17158,
      "unit": "BDT",
      "direction": "down",
      "text": "Cash taken out so far this month: 17,158 BDT. In this simulated data, this goes with lower risk."
    }
  ],
  "suggestions": [
    {
      "type": "cashout_saver",
      "cashout_count": 6,
      "fees_paid_bdt": 258,
      "fee_rate_pct": 1.5,
      "fee_rate_label": "assumed fee rate (placeholder, not yet sourced)",
      "requires_user_confirmation": true,
      "auto_action": false,
      "text": "So far this month you made 6 cash-outs and paid 258 BDT in fees (assumed fee rate 1.5%, a placeholder, not yet sourced). If some of these payments could be made from the wallet, you could avoid up to about 258 BDT in fees. Cash-out is fine when you need cash."
    }
  ],
  "notes": [],
  "balance_by_day": [
    {
      "day": 1,
      "balance_bdt": 898
    },
    {
      "day": 2,
      "balance_bdt": 264
    },
    {
      "day": 3,
      "balance_bdt": 264
    }
  ],
  "disclaimer": "This is an estimate from simulated data, not a guarantee. You decide."
}
```

Errors: 404 unknown user, e.g. `404` `{"error": "We could not find that.", "error_bn": "এটি খুঁজে পাওয়া যায়নি।"}`; 422 month outside 0-5 or `lang` not `en`/`bn`.

---

## POST /savings-plan

A savings plan for a goal. Capacity per month = `SAVINGS_CAP_FRACTION` x the user's average monthly net
(money in minus money out, including fees) over the months **before** the chosen month.

`status` is one of:
- `feasible`: the goal fits within capacity in the target months.
- `not_feasible`: the plan saves the full capacity each month and `plan.months` is the time needed. If even
  `max_months` is not enough, `plan.reaches_goal` is false and `plan.saved_in_max_months_bdt` is given.
- `blocked_alert`: the user has an alert. No plan, buffer first.
- `no_history`: month 0, no earlier months. No plan.
- `no_room`: the earlier months' average net is 0 or below. No plan.

`options`: up to 3 choices at half, three quarters and all of the capacity, each with months needed.

Body fields: `user_id` (int), `month` (0-5), `goal_bdt` (int, 1-500000), `months` (int, 1-24), `lang` (`en`/`bn`,
default `en`). Numbers must be JSON numbers, not strings. No extra fields.

### Feasible

Request: `POST /savings-plan` `{"user_id": 19, "month": 5, "goal_bdt": 10000, "months": 6, "lang": "en"}`

```json
{
  "user_id": 19,
  "month": 5,
  "lang": "en",
  "goal_bdt": 10000,
  "target_months": 6,
  "max_months": 24,
  "capacity_bdt": 2043,
  "plan": {
    "type": "savings_plan",
    "monthly_bdt": 1667,
    "months": 6,
    "reaches_goal": true,
    "needed_monthly_bdt": 1667,
    "requires_user_confirmation": true,
    "auto_action": false
  },
  "options": [
    {
      "monthly_bdt": 1021,
      "months": 10,
      "reaches_goal": true,
      "text": "Option: 1,021 BDT a month for 10 months."
    },
    {
      "monthly_bdt": 1532,
      "months": 7,
      "reaches_goal": true,
      "text": "Option: 1,532 BDT a month for 7 months."
    },
    {
      "monthly_bdt": 2043,
      "months": 5,
      "reaches_goal": true,
      "text": "Option: 2,043 BDT a month for 5 months."
    }
  ],
  "status": "feasible",
  "text": "You can reach 10,000 BDT in 6 months by saving 1,667 BDT a month. That fits within the 2,043 BDT a month your earlier months suggest you could set aside.",
  "disclaimer": "This is an estimate from simulated data, not a guarantee. You decide."
}
```

### Feasible, Bangla (same request with `"lang": "bn"`)

```json
{
  "user_id": 19,
  "month": 5,
  "lang": "bn",
  "goal_bdt": 10000,
  "target_months": 6,
  "max_months": 24,
  "capacity_bdt": 2043,
  "plan": {
    "type": "savings_plan",
    "monthly_bdt": 1667,
    "months": 6,
    "reaches_goal": true,
    "needed_monthly_bdt": 1667,
    "requires_user_confirmation": true,
    "auto_action": false
  },
  "options": [
    {
      "monthly_bdt": 1021,
      "months": 10,
      "reaches_goal": true,
      "text": "বিকল্প: মাসে ১,০২১ টাকা করে ১০ মাস।"
    },
    {
      "monthly_bdt": 1532,
      "months": 7,
      "reaches_goal": true,
      "text": "বিকল্প: মাসে ১,৫৩২ টাকা করে ৭ মাস।"
    },
    {
      "monthly_bdt": 2043,
      "months": 5,
      "reaches_goal": true,
      "text": "বিকল্প: মাসে ২,০৪৩ টাকা করে ৫ মাস।"
    }
  ],
  "status": "feasible",
  "text": "প্রতি মাসে ১,৬৬৭ টাকা জমিয়ে আপনি ৬ মাসে ১০,০০০ টাকায় পৌঁছাতে পারেন। আগের মাসগুলো দেখে মনে হয় আপনি মাসে ২,০৪৩ টাকা পর্যন্ত আলাদা রাখতে পারেন; এটি তার মধ্যেই আছে।",
  "disclaimer": "এটি সিমুলেটেড ডেটা থেকে করা একটি অনুমান, কোনো নিশ্চয়তা নয়। সিদ্ধান্ত আপনার।"
}
```

### Not feasible in the target months

Request: `POST /savings-plan` `{"user_id": 2, "month": 5, "goal_bdt": 10000, "months": 6, "lang": "en"}`

```json
{
  "user_id": 2,
  "month": 5,
  "lang": "en",
  "goal_bdt": 10000,
  "target_months": 6,
  "max_months": 24,
  "capacity_bdt": 587,
  "plan": {
    "type": "savings_plan",
    "monthly_bdt": 587,
    "months": 18,
    "reaches_goal": true,
    "needed_monthly_bdt": 1667,
    "requires_user_confirmation": true,
    "auto_action": false
  },
  "options": [
    {
      "monthly_bdt": 293,
      "months": 24,
      "reaches_goal": false,
      "text": "Option: 293 BDT a month; the goal would take more than 24 months."
    },
    {
      "monthly_bdt": 440,
      "months": 23,
      "reaches_goal": true,
      "text": "Option: 440 BDT a month for 23 months."
    },
    {
      "monthly_bdt": 587,
      "months": 18,
      "reaches_goal": true,
      "text": "Option: 587 BDT a month for 18 months."
    }
  ],
  "status": "not_feasible",
  "text": "Reaching 10,000 BDT in 6 months would need 1,667 BDT a month, more than the 587 BDT a month your earlier months suggest. At 587 BDT a month it would take about 18 months.",
  "disclaimer": "This is an estimate from simulated data, not a guarantee. You decide."
}
```

### Not reachable within 24 months

Request: `POST /savings-plan` `{"user_id": 2, "month": 5, "goal_bdt": 200000, "months": 6, "lang": "en"}`

```json
{
  "user_id": 2,
  "month": 5,
  "lang": "en",
  "goal_bdt": 200000,
  "target_months": 6,
  "max_months": 24,
  "capacity_bdt": 587,
  "plan": {
    "type": "savings_plan",
    "monthly_bdt": 587,
    "months": 24,
    "reaches_goal": false,
    "saved_in_max_months_bdt": 14088,
    "needed_monthly_bdt": 33334,
    "requires_user_confirmation": true,
    "auto_action": false
  },
  "options": [
    {
      "monthly_bdt": 293,
      "months": 24,
      "reaches_goal": false,
      "text": "Option: 293 BDT a month; the goal would take more than 24 months."
    },
    {
      "monthly_bdt": 440,
      "months": 24,
      "reaches_goal": false,
      "text": "Option: 440 BDT a month; the goal would take more than 24 months."
    },
    {
      "monthly_bdt": 587,
      "months": 24,
      "reaches_goal": false,
      "text": "Option: 587 BDT a month; the goal would take more than 24 months."
    }
  ],
  "status": "not_feasible",
  "text": "Reaching 200,000 BDT in 6 months would need 33,334 BDT a month, more than the 587 BDT a month your earlier months suggest. At 587 BDT a month, 24 months would give about 14,088 BDT, so a smaller goal may suit you better.",
  "disclaimer": "This is an estimate from simulated data, not a guarantee. You decide."
}
```

### Blocked by an alert

Request: `POST /savings-plan` `{"user_id": 1, "month": 4, "goal_bdt": 10000, "months": 6, "lang": "en"}`

```json
{
  "user_id": 1,
  "month": 4,
  "lang": "en",
  "goal_bdt": 10000,
  "target_months": 6,
  "max_months": 24,
  "capacity_bdt": null,
  "plan": null,
  "options": [],
  "status": "blocked_alert",
  "text": "Because your balance may run low this month, we are not suggesting savings right now. You may want to keep a buffer first.",
  "disclaimer": "This is an estimate from simulated data, not a guarantee. You decide."
}
```

### No room to save

Request: `POST /savings-plan` `{"user_id": 1, "month": 5, "goal_bdt": 10000, "months": 6, "lang": "en"}`

```json
{
  "user_id": 1,
  "month": 5,
  "lang": "en",
  "goal_bdt": 10000,
  "target_months": 6,
  "max_months": 24,
  "capacity_bdt": null,
  "plan": null,
  "options": [],
  "status": "no_room",
  "text": "Your earlier months show no room to save yet, so we are not suggesting a savings plan.",
  "disclaimer": "This is an estimate from simulated data, not a guarantee. You decide."
}
```

### No earlier months (month 0)

Request: `POST /savings-plan` `{"user_id": 2, "month": 0, "goal_bdt": 10000, "months": 6, "lang": "en"}`

```json
{
  "user_id": 2,
  "month": 0,
  "lang": "en",
  "goal_bdt": 10000,
  "target_months": 6,
  "max_months": 24,
  "capacity_bdt": null,
  "plan": null,
  "options": [],
  "status": "no_history",
  "text": "There are no earlier months to learn from yet, so we cannot suggest a savings plan.",
  "disclaimer": "This is an estimate from simulated data, not a guarantee. You decide."
}
```

Errors: 404 unknown user; 422 for out-of-range values, strings instead of numbers (e.g. `422` `{"error": "Some details are not valid. Please check them and try again.", "error_bn": "কিছু তথ্য সঠিক নয়। অনুগ্রহ করে দেখে আবার চেষ্টা করুন।"}`),
extra fields and bad JSON.

---

## POST /whatif

Change some model inputs and compare with the original. `risk_change` is `lower`, `about the same` or
`higher` (worked out inside the service; small changes count as "about the same"). A what-if only changes the
inputs. It does **not** re-simulate the month, so `original` and `whatif` contain no `balance_by_day` and no
cash-out tip.

Allowed keys (the 11 model inputs only): `balance_day20`, `min_balance_d1_20`, `avg_daily_spend_d1_20`,
`total_inflow_d1_20`, `total_outflow_d1_20`, `cashout_count_d1_20`, `cashout_amount_d1_20`,
`days_since_last_inflow`, `bill_payments_d1_20`, `prev_month_shortfall`, `inflow_vs_prev_month`.

Value rules: a JSON number, finite, not negative, at most 500000. `days_since_last_inflow` at most 20.
`prev_month_shortfall` 0 or 1. Counts and days must be whole numbers.

### English

Request: `POST /whatif` `{"user_id": 1, "month": 4, "overrides": {"balance_day20": 6000}, "lang": "en"}`

```json
{
  "user_id": 1,
  "month": 4,
  "lang": "en",
  "changed_inputs": {
    "balance_day20": 6000
  },
  "risk_change": "lower",
  "risk_change_text": "With these changes, the risk would be lower.",
  "original": {
    "risk_band": "medium",
    "risk_band_text": "Medium risk: your balance may run low before the month ends.",
    "alert": true,
    "floor_bdt": 500,
    "predicted_min_balance": null,
    "reasons": [
      {
        "feature": "avg_daily_spend_d1_20",
        "value": 1292,
        "unit": "BDT",
        "direction": "up",
        "text": "Your average spending per day so far this month: 1,292 BDT. In this simulated data, this goes with higher risk."
      },
      {
        "feature": "total_inflow_d1_20",
        "value": 35552,
        "unit": "BDT",
        "direction": "up",
        "text": "Money received so far this month: 35,552 BDT. In this simulated data, this goes with higher risk."
      },
      {
        "feature": "days_since_last_inflow",
        "value": 7,
        "unit": "count",
        "direction": "down",
        "text": "Money last came in 7 days ago. In this simulated data, this goes with lower risk."
      }
    ],
    "suggestions": [
      {
        "type": "buffer",
        "amount_bdt": 3000,
        "days_of_spend": 3,
        "capped_by_balance": true,
        "text": "Idea: keep about 3,000 BDT, close to your current balance, unspent until the month ends.",
        "requires_user_confirmation": true,
        "auto_action": false
      }
    ],
    "notes": [
      {
        "type": "shortfall_warning",
        "text": "Our estimate is that your balance could drop below 500 BDT before the month ends. You can plan for this now."
      },
      {
        "type": "savings_blocked_alert",
        "text": "Because your balance may run low this month, we are not suggesting savings right now. You may want to keep a buffer first."
      }
    ]
  },
  "whatif": {
    "risk_band": "low",
    "risk_band_text": "Low risk: your balance looks on track for the rest of the month.",
    "alert": false,
    "floor_bdt": 500,
    "predicted_min_balance": null,
    "reasons": [
      {
        "feature": "avg_daily_spend_d1_20",
        "value": 1292,
        "unit": "BDT",
        "direction": "up",
        "text": "Your average spending per day so far this month: 1,292 BDT. In this simulated data, this goes with higher risk."
      },
      {
        "feature": "balance_day20",
        "value": 6000,
        "unit": "BDT",
        "direction": "down",
        "text": "Your current balance: 6,000 BDT. In this simulated data, this goes with lower risk."
      },
      {
        "feature": "total_inflow_d1_20",
        "value": 35552,
        "unit": "BDT",
        "direction": "up",
        "text": "Money received so far this month: 35,552 BDT. In this simulated data, this goes with higher risk."
      }
    ],
    "suggestions": [],
    "notes": []
  },
  "note": "A what-if only changes the inputs you entered. It does not re-simulate the month.",
  "disclaimer": "This is an estimate from simulated data, not a guarantee. You decide."
}
```

### Bangla (same request with `"lang": "bn"`)

```json
{
  "user_id": 1,
  "month": 4,
  "lang": "bn",
  "changed_inputs": {
    "balance_day20": 6000
  },
  "risk_change": "lower",
  "risk_change_text": "এই পরিবর্তনগুলো হলে ঝুঁকি কম হবে।",
  "original": {
    "risk_band": "medium",
    "risk_band_text": "মাঝারি ঝুঁকি: মাস শেষ হওয়ার আগে আপনার ব্যালেন্স কমে যেতে পারে।",
    "alert": true,
    "floor_bdt": 500,
    "predicted_min_balance": null,
    "reasons": [
      {
        "feature": "avg_daily_spend_d1_20",
        "value": 1292,
        "unit": "BDT",
        "direction": "up",
        "text": "এই মাসে এ পর্যন্ত আপনার দৈনিক গড় খরচ: ১,২৯২ টাকা। এই সিমুলেটেড ডেটায় এটি বেশি ঝুঁকির সাথে দেখা যায়।"
      },
      {
        "feature": "total_inflow_d1_20",
        "value": 35552,
        "unit": "BDT",
        "direction": "up",
        "text": "এই মাসে এ পর্যন্ত আসা টাকা: ৩৫,৫৫২ টাকা। এই সিমুলেটেড ডেটায় এটি বেশি ঝুঁকির সাথে দেখা যায়।"
      },
      {
        "feature": "days_since_last_inflow",
        "value": 7,
        "unit": "count",
        "direction": "down",
        "text": "শেষবার টাকা এসেছে ৭ দিন আগে। এই সিমুলেটেড ডেটায় এটি কম ঝুঁকির সাথে দেখা যায়।"
      }
    ],
    "suggestions": [
      {
        "type": "buffer",
        "amount_bdt": 3000,
        "days_of_spend": 3,
        "capped_by_balance": true,
        "text": "পরামর্শ: মাস শেষ হওয়া পর্যন্ত প্রায় ৩,০০০ টাকা, যা আপনার বর্তমান ব্যালেন্সের কাছাকাছি, খরচ না করে হাতে রাখতে পারেন।",
        "requires_user_confirmation": true,
        "auto_action": false
      }
    ],
    "notes": [
      {
        "type": "shortfall_warning",
        "text": "আমাদের অনুমান, মাস শেষ হওয়ার আগে আপনার ব্যালেন্স ৫০০ টাকার নিচে নেমে যেতে পারে। আপনি এখন থেকেই এর জন্য পরিকল্পনা করতে পারেন।"
      },
      {
        "type": "savings_blocked_alert",
        "text": "এই মাসে আপনার ব্যালেন্স কমে যেতে পারে, তাই এখন আমরা সঞ্চয়ের পরামর্শ দিচ্ছি না। আগে কিছু টাকা হাতে রাখার কথা ভাবতে পারেন।"
      }
    ]
  },
  "whatif": {
    "risk_band": "low",
    "risk_band_text": "কম ঝুঁকি: মাসের বাকি সময়ের জন্য আপনার ব্যালেন্স ঠিক পথে আছে বলে মনে হচ্ছে।",
    "alert": false,
    "floor_bdt": 500,
    "predicted_min_balance": null,
    "reasons": [
      {
        "feature": "avg_daily_spend_d1_20",
        "value": 1292,
        "unit": "BDT",
        "direction": "up",
        "text": "এই মাসে এ পর্যন্ত আপনার দৈনিক গড় খরচ: ১,২৯২ টাকা। এই সিমুলেটেড ডেটায় এটি বেশি ঝুঁকির সাথে দেখা যায়।"
      },
      {
        "feature": "balance_day20",
        "value": 6000,
        "unit": "BDT",
        "direction": "down",
        "text": "আপনার বর্তমান ব্যালেন্স: ৬,০০০ টাকা। এই সিমুলেটেড ডেটায় এটি কম ঝুঁকির সাথে দেখা যায়।"
      },
      {
        "feature": "total_inflow_d1_20",
        "value": 35552,
        "unit": "BDT",
        "direction": "up",
        "text": "এই মাসে এ পর্যন্ত আসা টাকা: ৩৫,৫৫২ টাকা। এই সিমুলেটেড ডেটায় এটি বেশি ঝুঁকির সাথে দেখা যায়।"
      }
    ],
    "suggestions": [],
    "notes": []
  },
  "note": "'যদি এমন হয়' শুধু আপনার দেওয়া তথ্যগুলো বদলায়। এটি পুরো মাসটি নতুন করে হিসাব করে না।",
  "disclaimer": "এটি সিমুলেটেড ডেটা থেকে করা একটি অনুমান, কোনো নিশ্চয়তা নয়। সিদ্ধান্ত আপনার।"
}
```

Errors (all 422 with the generic message): unknown key, text value, `NaN`, `Infinity`, negative, above the
limit, non-whole count, empty `overrides`, extra body fields. 404 for an unknown user.

---

## GET /users/{user_id}/months/{month}/summary?lang=en|bn

"Why do I run short before month-end?": spending on days 1-20 by category and by week (days 1-7, 8-14, 15-20),
with a sentence about the biggest week. Cash-out amounts include their fees.

Request: `GET /users/1/months/4/summary?lang=en`

```json
{
  "user_id": 1,
  "month": 4,
  "lang": "en",
  "total_spent_bdt": 44392,
  "by_category": [
    {
      "category": "merchant",
      "amount_bdt": 2390,
      "label": "shop payments"
    },
    {
      "category": "bills",
      "amount_bdt": 20926,
      "label": "bills"
    },
    {
      "category": "recharge",
      "amount_bdt": 283,
      "label": "mobile recharge"
    },
    {
      "category": "family",
      "amount_bdt": 2231,
      "label": "money sent to family"
    },
    {
      "category": "cashout",
      "amount_bdt": 18562,
      "label": "cash-out"
    }
  ],
  "by_week": [
    {
      "start_day": 1,
      "end_day": 7,
      "amount_bdt": 11556
    },
    {
      "start_day": 8,
      "end_day": 14,
      "amount_bdt": 31914
    },
    {
      "start_day": 15,
      "end_day": 20,
      "amount_bdt": 922
    }
  ],
  "biggest_week": {
    "start_day": 8,
    "end_day": 14,
    "amount_bdt": 31914
  },
  "text": "Your biggest spending week so far was days 8 to 14, with 31,914 BDT out of 44,392 BDT spent so far this month. The largest category was bills (20,926 BDT).",
  "disclaimer": "This is an estimate from simulated data, not a guarantee. You decide."
}
```

Bangla (`?lang=bn`):

```json
{
  "user_id": 1,
  "month": 4,
  "lang": "bn",
  "total_spent_bdt": 44392,
  "by_category": [
    {
      "category": "merchant",
      "amount_bdt": 2390,
      "label": "দোকানে পেমেন্ট"
    },
    {
      "category": "bills",
      "amount_bdt": 20926,
      "label": "বিল"
    },
    {
      "category": "recharge",
      "amount_bdt": 283,
      "label": "মোবাইল রিচার্জ"
    },
    {
      "category": "family",
      "amount_bdt": 2231,
      "label": "পরিবারে পাঠানো টাকা"
    },
    {
      "category": "cashout",
      "amount_bdt": 18562,
      "label": "ক্যাশ আউট"
    }
  ],
  "by_week": [
    {
      "start_day": 1,
      "end_day": 7,
      "amount_bdt": 11556
    },
    {
      "start_day": 8,
      "end_day": 14,
      "amount_bdt": 31914
    },
    {
      "start_day": 15,
      "end_day": 20,
      "amount_bdt": 922
    }
  ],
  "biggest_week": {
    "start_day": 8,
    "end_day": 14,
    "amount_bdt": 31914
  },
  "text": "এ পর্যন্ত আপনার সবচেয়ে বেশি খরচের সপ্তাহ ছিল ৮ থেকে ১৪ তারিখ; এই মাসে মোট ৪৪,৩৯২ টাকার মধ্যে ৩১,৯১৪ টাকা খরচ হয়েছে। সবচেয়ে বড় খাত ছিল বিল (২০,৯২৬ টাকা)।",
  "disclaimer": "এটি সিমুলেটেড ডেটা থেকে করা একটি অনুমান, কোনো নিশ্চয়তা নয়। সিদ্ধান্ত আপনার।"
}
```

Errors: as for the forecast.

---

## GET /model-results

Everything for a results tab: `metrics` (metrics.json), `fairness` (fairness.json), `shap_global`
(shap_global.json), and the honest summary and disclaimer in both languages. This is the only response that
contains fairness numbers.

Request: `GET /model-results` (cut here: `metrics` keeps 3 sections and `fairness` keeps one group; the real
response has the full files)

```json
{
  "metrics": {
    "settings": {
      "learned_threshold": 0.277504,
      "oof_model_f1": 0.745527,
      "oof_rows": 2000.0,
      "oof_rule_f1": 0.741525,
      "rule_x": 2151.0,
      "threshold_used": 0.277504
    },
    "view2_not_below_day20": {
      "counts": {
        "caught_model": 98,
        "caught_rule": 78,
        "only_model": 29,
        "only_rule": 9,
        "shortfalls": 259
      },
      "equal_volume": {
        "alerts": 170,
        "model_precision": 0.4941,
        "model_recall": 0.3243,
        "rule_precision": 0.4588,
        "rule_recall": 0.3012
      },
      "model": {
        "f1": 0.4025,
        "pr_auc": 0.4217,
        "precision": 0.4298,
        "recall": 0.3784,
        "roc_auc": 0.7445
      },
      "persistence": {
        "f1": 0.3096,
        "pr_auc": 0.1866,
        "precision": 0.2399,
        "recall": 0.4363,
        "roc_auc": 0.6007
      },
      "rule": {
        "f1": 0.3636,
        "pr_auc": 0.392,
        "precision": 0.4588,
        "recall": 0.3012,
        "roc_auc": 0.7274
      }
    },
    "bootstrap_95ci": {
      "view2_equal_volume_recall_diff": [
        -0.0103,
        0.0608
      ],
      "view2_pr_auc_diff": [
        -0.0015,
        0.069
      ]
    }
  },
  "fairness": {
    "region": {
      "groups": {
        "Dhaka": {
          "alert_rate": 0.2127,
          "fpr": 0.0952,
          "low_sample": false,
          "recall": 0.6405,
          "rows": 710,
          "shortfall_rate": 0.2155
        }
      }
    }
  },
  "shap_global": {
    "mean_abs_shap": {
      "avg_daily_spend_d1_20": 0.3508,
      "balance_day20": 1.7415,
      "bill_payments_d1_20": 0.2483,
      "cashout_amount_d1_20": 0.1699,
      "cashout_count_d1_20": 0.0585,
      "days_since_last_inflow": 0.1348,
      "inflow_vs_prev_month": 0.1649,
      "min_balance_d1_20": 0.1726,
      "prev_month_shortfall": 0.0181,
      "total_inflow_d1_20": 0.3097,
      "total_outflow_d1_20": 0.1088
    },
    "method": "shap.TreeExplainer"
  },
  "honest_summary": {
    "en": "The model has a small lead over a simple balance rule, but it is not statistically clear.",
    "bn": "একটি সহজ ব্যালেন্স নিয়মের চেয়ে মডেলটি সামান্য এগিয়ে, তবে পরিসংখ্যানগতভাবে তা স্পষ্ট নয়।"
  },
  "disclaimer": {
    "en": "This is an estimate from simulated data, not a guarantee. You decide.",
    "bn": "এটি সিমুলেটেড ডেটা থেকে করা একটি অনুমান, কোনো নিশ্চয়তা নয়। সিদ্ধান্ত আপনার।"
  }
}
```

Errors: none in normal use.

---

## GET /results

Results for the judges' tab, **English only**. A trimmed copy of `/model-results` (values copied from the
artifacts, never recomputed) plus `impact`, the cash-out fee base of alerted users. No probabilities
(`calibration_bins` and `settings` are left out), no per-user data.

- `metrics`: `view2_not_below_day20`, `bootstrap_95ci`, `min_balance_mae_bdt`, `lead_time_days`, `sanity`, exactly as in
  `metrics.json`. `lead_time_days` covers only the shortfalls the model caught (`n`): days from day 20 to the first dip.
- `fairness`, `shap_global`: exactly as in `fairness.json` and `shap_global.json`.
- `impact`: test months (`months`) only. `alerted_user_months` = user-months where the app alerts (same threshold as the
  forecast). `saver_shown_user_months` = those where the cash-out saver would show. `fees_bdt` = the saver's
  `fees_paid_bdt` summed over those. `avg_fees_per_alerted_bdt` divides by `alerted_user_months`,
  `avg_fees_per_saver_shown_bdt` by `saver_shown_user_months` (null if the count is 0). Fees are ones already paid on
  days 1-20 at the placeholder `fee_rate_pct`. This is a fee base, not savings achieved.
- Computed on the first call (about 0.6 s) and cached; later calls are instant.

Request: `GET /results` (cut here: `metrics` keeps 2 sections, `fairness` keeps one group, `shap_global` keeps 2 features)

```json
{
  "simulated": true,
  "metrics": {
    "bootstrap_95ci": {
      "view2_equal_volume_recall_diff": [-0.0103, 0.0608],
      "view2_pr_auc_diff": [-0.0015, 0.069]
    },
    "lead_time_days": {"mean": 2.05, "median": 1.0, "n": 303}
  },
  "fairness": {
    "income_band": {
      "groups": {
        "low": {"alert_rate": 0.2367, "fpr": 0.0992, "low_sample": false, "recall": 0.6635, "rows": 866, "shortfall_rate": 0.2436}
      },
      "largest_gaps": {"fpr": 0.0378, "recall": 0.0502}
    }
  },
  "shap_global": {
    "mean_abs_shap": {"balance_day20": 1.7415, "avg_daily_spend_d1_20": 0.3508},
    "method": "shap.TreeExplainer"
  },
  "impact": {
    "months": [4, 5],
    "alerted_user_months": 445,
    "saver_shown_user_months": 213,
    "fees_bdt": 12001,
    "avg_fees_per_alerted_bdt": 27.0,
    "avg_fees_per_saver_shown_bdt": 56.3,
    "fee_rate_pct": 1.5
  },
  "disclaimer": "This is an estimate from simulated data, not a guarantee. You decide."
}
```

Errors: none in normal use.

---

## Common errors

Every error has the same shape: a short generic message in English and Bangla. It never echoes the input and
never contains a stack trace.

```json
{
  "error": "We could not find that.",
  "error_bn": "এটি খুঁজে পাওয়া যায়নি।"
}
```

- `404`: unknown user or month data, unknown route. `error`: "We could not find that."
- `405`: wrong HTTP method. Same message as 404. Tested: `DELETE /health` and `PUT /savings-plan` return 405.
- `422`: input fails validation (bad month, bad `lang`, bad body, bad what-if value, bad JSON).
  `error`: "Some details are not valid. Please check them and try again."
- `500`: anything unexpected. `error`: "Something went wrong on our side. Please try again later." **Not tested.**
