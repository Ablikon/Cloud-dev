"""Unit tests for the parts of the consumer that decide correctness.

No AWS calls: these cover the two decisions that make the consumer safe to run
twice — what counts as an applicable message, and what counts as a duplicate
rather than a failure.
"""
import json, os, sys, unittest

os.environ.setdefault("AWS_DEFAULT_REGION", "eu-north-1")
os.environ.setdefault("QUEUE_URL", "https://example.invalid/q")
os.environ.setdefault("PROCESSED_TABLE", "t-processed")
os.environ.setdefault("ACCOUNTS_TABLE", "t-accounts")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

import worker                                                   # noqa: E402


def cancelled(*codes):
    """A ClientError shaped like a cancelled DynamoDB transaction."""
    from botocore.exceptions import ClientError
    return ClientError(
        {"Error": {"Code": "TransactionCanceledException", "Message": "cancelled"},
         "CancellationReasons": [{"Code": c} for c in codes]},
        "TransactWriteItems")


class ParseDetail(unittest.TestCase):
    def test_eventbridge_envelope(self):
        body = json.dumps({"source": "kbtu.shop.orders", "detail-type": "OrderPlaced",
                           "detail": {"orderId": "o-1", "account": "a-1", "total": 100}})
        self.assertEqual(worker.parse_detail(body)["orderId"], "o-1")

    def test_bare_payload(self):
        body = json.dumps({"orderId": "o-2", "account": "a-1", "total": 10})
        self.assertEqual(worker.parse_detail(body)["account"], "a-1")

    def test_decimal_total_as_string(self):
        body = json.dumps({"orderId": "o-3", "account": "a-1", "total": "129.50"})
        self.assertEqual(worker.parse_detail(body)["total"], "129.50")

    def test_missing_account_is_rejected(self):
        body = json.dumps({"detail": {"orderId": "o-4", "total": 100}})
        with self.assertRaises(KeyError):
            worker.parse_detail(body)

    def test_empty_order_id_is_rejected(self):
        # "" is falsy but present; a missing-field check written as `in detail`
        # would let it through and write a marker under an empty key.
        body = json.dumps({"detail": {"orderId": "", "account": "a-1", "total": 100}})
        with self.assertRaises(KeyError):
            worker.parse_detail(body)

    def test_non_numeric_total_is_rejected(self):
        body = json.dumps({"detail": {"orderId": "o-5", "account": "a-1", "total": "free"}})
        with self.assertRaises(ValueError):
            worker.parse_detail(body)

    def test_malformed_json_is_rejected(self):
        with self.assertRaises(json.JSONDecodeError):
            worker.parse_detail("{not json")


class IsDuplicate(unittest.TestCase):
    def test_conditional_check_failed_is_a_duplicate(self):
        # The marker already exists: the order was applied before. Reporting
        # success is correct; the message must be deleted, not retried forever.
        self.assertTrue(worker.is_duplicate(cancelled("ConditionalCheckFailed", "None")))

    def test_transaction_conflict_is_not_a_duplicate(self):
        # Two consumers touched the same account item at once. The work has NOT
        # been done. Treating this as a duplicate would silently lose an order.
        self.assertFalse(worker.is_duplicate(cancelled("None", "TransactionConflict")))

    def test_throttling_is_not_a_duplicate(self):
        self.assertFalse(worker.is_duplicate(cancelled("ThrottlingError", "None")))

    def test_no_reasons_is_not_a_duplicate(self):
        self.assertFalse(worker.is_duplicate(cancelled()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
