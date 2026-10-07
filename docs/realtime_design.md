# Real-time design: how this would run at upay scale

All data in this prototype is simulated. **No real upay API was available**, and nothing connects to upay.
Each part below is marked **Exists today** (in this repository, on one machine) or **Design only**.

## Flow

```
upay transaction events ──> event stream ──> scoring consumers ──> wallet API / app
                                │                 │
                                │                 ├─ feature store (per user-month running features)
                                │                 ├─ model service (XGBoost + SHAP, versioned)
                                └─ raw archive    └─ database (consents, budgets, logs, audit)
```

| Part | Today | At upay scale |
|---|---|---|
| Transaction source | **Exists today:** `SimulatedSource` reads the simulated CSVs (`src/integration/upay_adapter.py`). | **Design only:** `UpayApiSource` lists the fields a real feed needs and raises `NotImplementedError`. |
| Event stream | **Exists today:** `InProcessBus`, a `queue.Queue` with one worker thread (`src/integration/event_bus.py`). `POST /integration/events` (API key) answers 202 with a batch id. | **Design only:** Kafka or RabbitMQ behind the same `EventBus` methods. Partition by customer, so one customer's events stay in order. |
| Validation | **Exists today:** the same checks for page and batch: type, amount limit, day, balance never below zero, idempotency key, consent, feature switch. | Same rules, run in the consumer. The idempotency key becomes the upay transaction id. |
| Features | **Exists today:** rebuilt per user-month with the unchanged `build_features` on the simulated month plus the live rows. | **Design only:** a feature store that keeps day 1-20 running totals per user-month and updates them per event (no full rebuild). |
| Model | **Exists today:** the saved XGBoost model, loaded once and scored in the API process. Timing is in `artifacts/load_test.json`. | **Design only:** a separate model service with versioned models, shadow scoring for a challenger, and monitoring of input drift. |
| Database | **Exists today:** SQLite in WAL mode, one process. | **Design only:** a managed relational database with encryption at rest, replicas and backups. |
| Limits and auth | **Exists today:** sessions, API keys, an in-memory rate limit. | **Design only:** an API gateway with mTLS between services, and a shared rate-limit store. |

## What the load test shows

`scripts/load_test.py` measures, on one laptop:
- forecast reads
- live transaction writes
- one queued batch through the event bus
- batch scoring of 100,000 feature rows

It shows the parts work together under concurrent use. It is not a production benchmark.
