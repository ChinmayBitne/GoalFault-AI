"""Block the recorded $180 refund with the exported guard. No server.

Run from the repo root: python -m scripts.guard_example
"""
from goalfault.guard import PolicyBlocked, guard

@guard("domains/customer_support.yaml")
def issue_refund(order_id, amount):
    raise SystemExit("the refund function ran")

try:
    issue_refund(order_id="ORD-180", amount=180)
except PolicyBlocked as exc:
    if exc.rule != "P-101":
        raise SystemExit(f"blocked by {exc.rule}")
else:
    raise SystemExit("the refund was not blocked")
print("blocked by P-101")
