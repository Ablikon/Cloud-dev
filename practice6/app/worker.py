"""cad-p6-worker — the Practice 5 consumer, now as a long-running container.

Two jobs in one process, because a Fargate service behind an ALB needs both:
  * an HTTP listener, so the target group has something to health-check;
  * a polling loop, because nothing hands us a batch any more. Lambda's event
    source mapping did the long polling, the batching and the deletes. Here
    they are ours.

A task can be stopped at any second (week 10's constraint), so the loop holds
no state worth losing: every message is either deleted after a successful
transaction or left to reappear after the visibility timeout.
"""
import json, logging, os, signal, socket, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import boto3
from botocore.exceptions import ClientError

logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(message)s")
log = logging.getLogger("worker")

CODE_VERSION = os.environ.get("CODE_VERSION", "dev")
QUEUE_URL = os.environ["QUEUE_URL"]
PROCESSED_TABLE = os.environ["PROCESSED_TABLE"]
ACCOUNTS_TABLE = os.environ["ACCOUNTS_TABLE"]
PORT = int(os.environ.get("PORT", "8080"))
POLL_THREADS = int(os.environ.get("POLL_THREADS", "2"))
DEDUP_TTL_DAYS = int(os.environ.get("DEDUP_TTL_DAYS", "30"))

ddb = boto3.client("dynamodb")
sqs = boto3.client("sqs")

TASK = os.environ.get("ECS_CONTAINER_METADATA_URI_V4", "").rsplit("/", 1)[-1][:12] or socket.gethostname()
STOP = threading.Event()
STATS = {"received": 0, "applied": 0, "duplicates": 0, "failed": 0, "startedAt": time.time()}
_lock = threading.Lock()


def emit(level, event_name, **fields):
    log.log(level, json.dumps({"event": event_name, "codeVersion": CODE_VERSION,
                               "task": TASK, **fields}))


def bump(key, n=1):
    with _lock:
        STATS[key] += n


def apply_order(detail, message_id):
    """Same transaction as Practice 5: dedup marker and balance, or neither."""
    order_id = detail["orderId"]
    ddb.transact_write_items(TransactItems=[
        {"Put": {"TableName": PROCESSED_TABLE,
                 "Item": {"dedupKey": {"S": order_id},
                          "firstSeenAt": {"S": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
                          "messageId": {"S": message_id},
                          "consumer": {"S": f"fargate:{TASK}"},
                          "ttl": {"N": str(int(time.time()) + DEDUP_TTL_DAYS * 86400)}},
                 "ConditionExpression": "attribute_not_exists(dedupKey)"}},
        {"Update": {"TableName": ACCOUNTS_TABLE,
                    "Key": {"accountId": {"S": detail["account"]}},
                    "UpdateExpression": "ADD balance :a SET lastOrderId = :o",
                    "ExpressionAttributeValues": {":a": {"N": str(detail["total"])},
                                                  ":o": {"S": order_id}}}}])


def is_duplicate(err):
    reasons = err.response.get("CancellationReasons") or []
    return bool(reasons) and reasons[0].get("Code") == "ConditionalCheckFailed"


def poll_loop(n):
    emit(logging.INFO, "poller.started", thread=n)
    while not STOP.is_set():
        try:
            # 20 s long poll: one empty API call per 20 s per thread instead of
            # a busy loop. This is what the event source mapping used to do.
            resp = sqs.receive_message(QueueUrl=QUEUE_URL, MaxNumberOfMessages=10,
                                       WaitTimeSeconds=20, VisibilityTimeout=60)
        except Exception as e:                      # network blip, keep polling
            emit(logging.ERROR, "poller.receive.failed", thread=n, error=type(e).__name__)
            STOP.wait(2)
            continue

        msgs = resp.get("Messages", [])
        if msgs:
            bump("received", len(msgs))
            emit(logging.INFO, "batch.received", thread=n, batchSize=len(msgs))

        for m in msgs:
            mid = m["MessageId"]
            try:
                env = json.loads(m["Body"])
                detail = env.get("detail", env)
                detail["orderId"], detail["account"]
                float(detail["total"])
            except Exception as e:
                # Unparseable: leave it. It will reappear and, after
                # maxReceiveCount, the redrive policy moves it to the DLQ.
                emit(logging.ERROR, "record.unparseable", messageId=mid, error=type(e).__name__)
                bump("failed")
                continue
            try:
                apply_order(detail, mid)
                bump("applied")
                emit(logging.INFO, "order.applied", dedupKey=detail["orderId"],
                     account=detail["account"], amount=str(detail["total"]), messageId=mid)
            except ClientError as e:
                if e.response["Error"]["Code"] == "TransactionCanceledException" and is_duplicate(e):
                    bump("duplicates")
                    emit(logging.INFO, "order.duplicate.skipped",
                         dedupKey=detail["orderId"], messageId=mid)
                else:
                    bump("failed")
                    emit(logging.ERROR, "order.failed", dedupKey=detail["orderId"],
                         messageId=mid, error=e.response["Error"]["Code"],
                         cancellationReasons=[r.get("Code") for r in
                                              (e.response.get("CancellationReasons") or [])])
                    continue    # not deleted: let it reappear
            # Deleted only after the transaction committed.
            try:
                sqs.delete_message(QueueUrl=QUEUE_URL, ReceiptHandle=m["ReceiptHandle"])
            except Exception as e:
                # The transaction already committed, so a redelivery is harmless:
                # the dedup marker makes the second attempt a no-op.
                emit(logging.ERROR, "delete.failed", messageId=mid, error=type(e).__name__)
    emit(logging.INFO, "poller.stopped", thread=n)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code, payload):
        body = json.dumps(payload, indent=1).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/healthz"):
            # Healthy means the pollers are alive. A target that answers 200
            # while its pollers have died is the failure mode worth catching.
            alive = sum(1 for t in threading.enumerate() if t.name.startswith("poll-"))
            ok = alive == POLL_THREADS and not STOP.is_set()
            self._send(200 if ok else 503,
                       {"status": "ok" if ok else "unhealthy",
                        "pollers": alive, "expected": POLL_THREADS,
                        "task": TASK, "codeVersion": CODE_VERSION})
        elif self.path == "/":
            with _lock:
                s = dict(STATS)
            s["uptimeSeconds"] = round(time.time() - s.pop("startedAt"), 1)
            self._send(200, {"service": "cad-p6-worker", "codeVersion": CODE_VERSION,
                             "task": TASK, "stats": s})
        else:
            self._send(404, {"error": "not found", "path": self.path})

    def log_message(self, fmt, *args):
        # The ALB health check would otherwise write two lines a second.
        if not self.path.startswith("/healthz"):
            emit(logging.INFO, "http", path=self.path, status=args[1] if len(args) > 1 else None)


def shutdown(signum, _frame):
    # ECS sends SIGTERM, then SIGKILL after stopTimeout. Stop polling, let
    # in-flight messages finish; anything unfinished simply reappears.
    emit(logging.INFO, "signal.received", signal=signum)
    STOP.set()


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    for i in range(POLL_THREADS):
        threading.Thread(target=poll_loop, args=(i,), name=f"poll-{i}", daemon=True).start()
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    srv.daemon_threads = True
    emit(logging.INFO, "http.listening", port=PORT, pollThreads=POLL_THREADS)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    while not STOP.is_set():
        STOP.wait(1)
    srv.shutdown()
    emit(logging.INFO, "service.stopped", stats=STATS)
