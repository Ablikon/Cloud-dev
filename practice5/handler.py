"""cad-p5-consumer — idempotent SQS consumer for the OrderPlaced domain event.

Two rules this file exists to honour:
  1. The deduplication key is the BUSINESS key (orderId). A client retry produces
     a brand-new SQS message with a brand-new messageId but the same order, so
     messageId would not deduplicate anything.
  2. The dedup marker and the balance change are written in ONE transaction.
     Writing the balance first and the marker second leaves a window where a
     timeout credits the account twice.
"""
import json, logging, os, time
import boto3
from botocore.exceptions import ClientError

log = logging.getLogger()
log.setLevel(logging.INFO)

CODE_VERSION = "1.1.0"
PROCESSED_TABLE = os.environ["PROCESSED_TABLE"]
ACCOUNTS_TABLE = os.environ["ACCOUNTS_TABLE"]
DEDUP_TTL_DAYS = int(os.environ.get("DEDUP_TTL_DAYS", "30"))

ddb = boto3.client("dynamodb")


def _emit(level, event_name, **fields):
    """One structured line per decision. Never the raw event body."""
    log.log(level, json.dumps({"event": event_name, "codeVersion": CODE_VERSION, **fields}))


def _is_duplicate(err):
    """True when the transaction was cancelled *because the marker already existed*.

    TransactionCanceledException is also raised for throttling and for validation
    errors. Treating all of them as duplicates would silently drop real work, so
    the first cancellation reason has to say ConditionalCheckFailed.
    """
    reasons = err.response.get("CancellationReasons") or []
    return bool(reasons) and reasons[0].get("Code") == "ConditionalCheckFailed"


def _reasons(err):
    """The per-item cancellation codes, so a failure names itself in the log."""
    return [r.get("Code") for r in (err.response.get("CancellationReasons") or [])]


def handler(event, context):
    failed = []
    records = event.get("Records", [])
    _emit(logging.INFO, "batch.received", batchSize=len(records))

    for r in records:
        message_id = r["messageId"]
        try:
            envelope = json.loads(r["body"])
            # EventBridge wraps the payload; the business fields live in detail.
            detail = envelope.get("detail", envelope)
            order_id = detail["orderId"]          # the deduplication key
            account = detail["account"]
            amount = str(detail["total"])
            float(amount)                          # reject a non-numeric total here
        except (KeyError, ValueError, TypeError, json.JSONDecodeError) as e:
            _emit(logging.ERROR, "record.unparseable",
                  messageId=message_id, error=type(e).__name__, detail=str(e))
            failed.append({"itemIdentifier": message_id})
            continue

        try:
            ddb.transact_write_items(TransactItems=[
                {"Put": {
                    "TableName": PROCESSED_TABLE,
                    "Item": {
                        "dedupKey": {"S": order_id},
                        "firstSeenAt": {"S": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
                        "messageId": {"S": message_id},
                        "ttl": {"N": str(int(time.time()) + DEDUP_TTL_DAYS * 86400)},
                    },
                    "ConditionExpression": "attribute_not_exists(dedupKey)",
                }},
                {"Update": {
                    "TableName": ACCOUNTS_TABLE,
                    "Key": {"accountId": {"S": account}},
                    "UpdateExpression": "ADD balance :a SET lastOrderId = :o",
                    "ExpressionAttributeValues": {":a": {"N": amount}, ":o": {"S": order_id}},
                }},
            ])
            _emit(logging.INFO, "order.applied",
                  dedupKey=order_id, account=account, amount=amount, messageId=message_id)

        except ClientError as e:
            if e.response["Error"]["Code"] == "TransactionCanceledException" and _is_duplicate(e):
                # Already applied. Returning success deletes the message; retrying
                # it forever would be the real bug.
                _emit(logging.INFO, "order.duplicate.skipped",
                      dedupKey=order_id, messageId=message_id)
            else:
                _emit(logging.ERROR, "order.failed",
                      dedupKey=order_id, messageId=message_id,
                      error=e.response["Error"]["Code"],
                      cancellationReasons=_reasons(e))
                failed.append({"itemIdentifier": message_id})

    _emit(logging.INFO, "batch.done",
          succeeded=len(records) - len(failed), failed=len(failed),
          failedIds=[f["itemIdentifier"] for f in failed])
    # Only these records come back. Without ReportBatchItemFailures the whole
    # batch would be redelivered and every good record processed twice.
    return {"batchItemFailures": failed}
