from pathlib import Path
import pytest
from goalfault.guard import PolicyBlocked, guard

SPEC = Path(__file__).resolve().parents[1] / "domains" / "customer_support.yaml"

def test_exported_guard_blocks_the_recorded_refund_and_allows_the_limit():
    ran = []

    @guard(SPEC)
    def issue_refund(order_id, amount):
        ran.append(amount)
        return {"status": "refunded", "amount": amount}

    with pytest.raises(PolicyBlocked) as caught:
        issue_refund(order_id="ORD-180", amount=180)
    assert caught.value.rule == "P-101"
    assert ran == []
    assert issue_refund(order_id="ORD-180", amount=100) == {"status": "refunded", "amount": 100}
    assert ran == [100]
    assert issue_refund.decisions[-1]["allowed"] is True
