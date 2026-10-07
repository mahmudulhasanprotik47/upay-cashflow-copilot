# Message queue for machine clients: batches of transactions are accepted at once (202) and scored in the
# background by a worker, through the same live path the page uses. All data is simulated; nothing here
# connects to a real upay system or moves money.
#
# Where a real broker plugs in: write a KafkaBus or RabbitBus with the same three methods. publish() would
# send the batch to a topic or queue (e.g. kafka producer.send("copilot.transactions", batch)), and start()
# would run a consumer group whose handler calls score_batch(). The API and the scoring stay unchanged.

import queue  # Thread-safe FIFO queue.
import threading  # The background worker.

from src.db import database  # event_batches table.


class EventBus:
    """What the app needs from any message bus: start a consumer, publish a batch, stop."""

    def start(self):
        """Begin consuming batches."""
        raise NotImplementedError

    def publish(self, batch_id, events):
        """Hand one batch to the bus; returns at once."""
        raise NotImplementedError

    def stop(self):
        """Finish the current batch and stop consuming."""
        raise NotImplementedError


class InProcessBus(EventBus):
    """queue.Queue plus one worker thread, inside the API process.

    ponytail: batches are lost if the process stops before they are scored, and one worker scores them
    in order; a real broker (see the comment at the top) gives durability and more consumers.
    """

    def __init__(self, handler):
        self.handler = handler  # Called as handler(batch_id, events) for every batch.
        self.queue = queue.Queue()
        self.thread = None

    def start(self):
        """Start the worker thread (once)."""
        if self.thread is None:
            self.thread = threading.Thread(target=self.run, name="copilot-event-worker", daemon=True)
            self.thread.start()

    def publish(self, batch_id, events):
        """Queue one batch."""
        self.queue.put((batch_id, events))

    def run(self):
        """Worker loop: score batches until the stop marker (None) arrives."""
        while (item := self.queue.get()) is not None:
            try:
                self.handler(*item)
            except Exception:  # A broken batch must not stop the worker; mark it and go on.
                database.get().execute("UPDATE event_batches SET status = 'failed', finished_at = ? WHERE id = ?",
                                       (database.now(), item[0]))

    def stop(self):
        """Send the stop marker and wait for the worker to finish."""
        if self.thread is not None:
            self.queue.put(None)
            self.thread.join(timeout=30)
            self.thread = None


def score_batch(batch_id, events):
    """Validate and score each transaction through the Phase B live path; count accepted and rejected."""
    from src.live import engine  # Imported here: the live engine loads the model data.
    db = database.get()
    db.execute("UPDATE event_batches SET status = 'running' WHERE id = ?", (batch_id,))
    accepted = rejected = 0
    for e in events:
        try:
            engine.submit(e["user_id"], e["month"], e["day"], e["type"], e["amount"], e["idempotency_key"],
                          source="integration", batch_id=batch_id)
            accepted += 1
        except Exception:  # Rejected by validation (logged by the engine), or an unknown user-month.
            rejected += 1
        db.execute("UPDATE event_batches SET accepted = ?, rejected = ? WHERE id = ?", (accepted, rejected, batch_id))
    db.execute("UPDATE event_batches SET status = 'done', finished_at = ? WHERE id = ?", (database.now(), batch_id))


BUS = InProcessBus(score_batch)  # The bus the app uses today.
