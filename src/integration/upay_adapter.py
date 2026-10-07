# Where transactions come from. Today: the simulated data. A real upay connection is only a documented
# stub: no real upay API was available to this project, and nothing here connects to upay.

from src.api import service  # The simulated data the app already loads.


class TransactionSource:
    """Gives one user's transactions for one month as plain dicts."""

    def transactions(self, user_id, month):
        """List of {day, type, direction, amount, fee}."""
        raise NotImplementedError


class SimulatedSource(TransactionSource):
    """The simulated transactions (data/transactions.csv), as the app uses them today."""

    def transactions(self, user_id, month):
        """The simulated month for one user."""
        rows = service.tx_for(user_id, month)
        return [{"day": int(r.day), "type": r.type, "direction": r.direction, "amount": int(r.amount), "fee": int(r.fee)}
                for r in rows.itertuples()]


class UpayApiSource(TransactionSource):
    """Stub for a real upay transaction feed. Not implemented: no upay API was available.

    Fields a real feed would need per transaction: customer reference (pseudonymous id), transaction id
    (used as the idempotency key), timestamp with time zone, type mapped to the 7 types in
    config.LIVE_TYPES, direction, amount in BDT, fee in BDT, channel (app / agent), status
    (completed / reversed), and the balance after the transaction (to check the running balance).
    It would also need the customer's consent state and a signed, rate-limited server-to-server channel.
    """

    def transactions(self, user_id, month):
        """Always raises: there is no real upay connection in this prototype."""
        raise NotImplementedError("No upay API is available to this prototype; data is simulated.")
