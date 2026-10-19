"""
SIS 2 — the orders read path, reimplemented as a Lambda function.

Design notes that the week 7 anti-pattern slide asks to be named explicitly:

  * TWO RELATED ROUTES IN ONE FUNCTION, not one function per route. Both answer
    "list orders"; they differ only in which key they query. One function means
    one role, one log group and one deployment, and the shared code is the part
    that would otherwise be copy-pasted twelve times. The cost of this choice is
    that the two routes cannot be scaled, throttled or permissioned separately —
    if the status listing ever needed different limits, it would have to split.

  * NEVER Scan. Both access patterns are served by Query: the base table for a
    customer's orders, the GSI for a status. The execution role does not even
    carry dynamodb:Scan, so the anti-pattern is impossible rather than merely
    discouraged.

  * The whole event is never logged. print(event) ships whatever a caller sent —
    tokens, emails — into CloudWatch, and ingestion is billed per GB. Only the
    fields this function acts on are logged, as structured JSON.
"""
import json, os, logging, time
import boto3
from boto3.dynamodb.conditions import Key

CODE_VERSION = "1.1.0"
TABLE_NAME = os.environ["TABLE_NAME"]
INDEX_NAME = os.environ["INDEX_NAME"]
MAX_LIMIT = 50

log = logging.getLogger()
log.setLevel(logging.INFO)
_table = boto3.resource("dynamodb").Table(TABLE_NAME)   # created once per environment, reused


def _emit(level, event_name, **fields):
    """One structured line. Never the raw event."""
    log.log(level, json.dumps({"event": event_name, "codeVersion": CODE_VERSION, **fields}))


def _params(event):
    """Function URL, API Gateway and a direct invoke all arrive differently."""
    if isinstance(event, dict):
        qs = event.get("queryStringParameters")
        if qs:
            return qs
        if "customer" in event or "status" in event:
            return event
    return {}


def _reply(status, body):
    return {"statusCode": status,
            "headers": {"content-type": "application/json"},
            "body": json.dumps(body, default=str)}


def handler(event, context):
    started = time.time()
    p = _params(event)
    customer = p.get("customer")
    status = p.get("status")
    try:
        limit = min(int(p.get("limit", 25)), MAX_LIMIT)
    except (TypeError, ValueError):
        limit = 25

    if bool(customer) == bool(status):
        _emit(logging.WARNING, "bad_request", hasCustomer=bool(customer), hasStatus=bool(status))
        return _reply(400, {"error": "supply exactly one of ?customer= or ?status="})

    if customer:
        route = "ordersByCustomer"
        kw = dict(KeyConditionExpression=Key("PK").eq(f"CUSTOMER#{customer}")
                                         & Key("SK").begins_with("ORDER#"))
    else:
        route = "ordersByStatus"
        kw = dict(IndexName=INDEX_NAME,
                  KeyConditionExpression=Key("status").eq(status))

    resp = _table.query(ScanIndexForward=False, Limit=limit,
                        ReturnConsumedCapacity="TOTAL", **kw)

    items = [{"orderId": i.get("orderId"), "customerId": i.get("customerId"),
              "status": i.get("status"), "createdAt": i.get("createdAt"),
              "totalKzt": int(i["totalKzt"]) if "totalKzt" in i else None}
             for i in resp.get("Items", [])]

    rcu = float(resp.get("ConsumedCapacity", {}).get("CapacityUnits", 0))
    _emit(logging.INFO, "query_served", route=route,
          returned=len(items), scanned=resp.get("ScannedCount"),
          consumedRcu=rcu, ms=round((time.time() - started) * 1000, 1))

    total = sum(o["totalKzt"] for o in items if o["totalKzt"] is not None)
    return _reply(200, {"route": route, "codeVersion": CODE_VERSION,
                        "count": len(items), "scannedCount": resp.get("ScannedCount"),
                        "consumedRcu": rcu, "totalValueKzt": total, "orders": items})
