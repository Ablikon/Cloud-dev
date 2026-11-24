#!/usr/bin/env python3
"""Publish an OrderPlaced fact to an environment's bus.

    python3 publish_event.py dev o-1042 acct-1 129.50 KZ
"""
import json, sys
import boto3

def main():
    if len(sys.argv) < 6:
        print(__doc__); return 2
    env, order_id, account, total, country = sys.argv[1:6]
    ev = boto3.client("events")
    resp = ev.put_events(Entries=[{
        "EventBusName": f"cad-sis3-{env}-orders",
        "Source": "kbtu.shop.orders",
        "DetailType": "OrderPlaced",
        "Detail": json.dumps({"orderId": order_id, "account": account,
                              "total": float(total), "country": country}),
    }])
    # PutEvents answers 200 even when an entry was rejected. The count is the
    # only thing that says whether the fact was actually accepted.
    if resp["FailedEntryCount"]:
        print("FAILED:", json.dumps(resp["Entries"], indent=1)); return 1
    print(f"accepted  orderId={order_id}  eventId={resp['Entries'][0]['EventId']}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
