# Pilot plan: how a real cohort test would run

**No cohort test has been run.** Everything in this prototype uses simulated data. This page describes how
a real test could use the tables that already exist, so the next step is clear.

## What already exists

- `consents`: who agreed to which notice version, and when they withdrew.
- `feedback`: per suggestion, "Helpful / Not helpful" and "I will keep this amount / Not now", with the
  user's group (`ab_group`).
- Group A or B: a stable hash of the user id (`src/api/routers/live.py`, `ab_group`). Today it is
  **recorded only**: both groups see the same screen.
- `predictions_log`: every live score (band, alert, unusual flag, budget warnings, time taken). No
  probability is stored.
- `audit_log`: every consent, export, deletion and staff view.

## How a real test would run

1. Opt-in only: real upay users who accept the data notice, under a data-sharing agreement.
2. Treatment: group B sees something different. For example, B sees the model-driven target balance
   next to the rule-based buffer, while A sees only the buffer. The difference is decided and written
   down before the test starts.
3. Length: at least three full months, so each user passes day 20 more than once.
4. Pre-registered measures, compared between A and B:
   - share of alerted user-months that still ran below 500 BDT on days 21-30 (main outcome)
   - "Helpful" rate and "I will keep this amount" rate from `feedback`
   - consent withdrawals and opt-outs (harm signal)
   - cash-out fees paid on days 21-30
5. Analysis: difference between groups with a bootstrap over users, with the same method as the model
   results. Report it whatever the result is.
6. Safeguards during the test: suggestions only, the user confirms, nothing moves money, and staff views
   are audited.

## What this cannot show today

Nothing about real behaviour: there are no real users, and the groups currently see the same screen.
