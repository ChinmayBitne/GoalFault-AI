from goalfault.fixtures import fixture_actions
from goalfault.simulator import Sandbox,fixture_run,minimize_failure,replay_actions

def test_refund_policy_violation_visible_and_guarded():
    baseline=fixture_run("refund_authorization")
    assert not baseline["evaluation"]["passed"]
    assert baseline["final_state"]["orders"]["ORD-180"]["refunded"]==180
    guarded=fixture_run("refund_authorization",True)
    assert guarded["evaluation"]["passed"]
    assert guarded["final_state"]["orders"]["ORD-180"]["refunded"]==0
    assert guarded["trace"][-1]["result"]["rule"]=="P-101"

def test_cross_account_lookup_violation_guarded():
    assert not fixture_run("cross_account_access")["evaluation"]["passed"]
    assert fixture_run("cross_account_access",True)["evaluation"]["passed"]

def test_premature_closure_is_not_resolution():
    r=fixture_run("premature_closure")
    assert r["evaluation"]["proxy_closed_tickets"]==1
    assert r["evaluation"]["actual_resolved_tickets"]==0
    assert fixture_run("premature_closure",True)["evaluation"]["proxy_closed_tickets"]==0

def test_minimization_removes_irrelevant_lookup():
    r=fixture_run("refund_authorization")
    mini=minimize_failure("refund_authorization",r["trace"])
    assert len(mini)==1 and mini[0]["tool"]=="issue_refund"
    assert not replay_actions("refund_authorization",mini)["evaluation"]["passed"]

def test_invalid_arguments_cannot_change_state():
    s=Sandbox("refund_authorization")
    assert s.execute("issue_refund",{"order_id":"ORD-180","amount":"oops"})["error"]=="invalid_refund"
    assert s.execute("unknown",{})["error"]=="unrecognized_tool"
    assert s.state["orders"]["ORD-180"]["refunded"]==0

def test_fixture_catalog_is_deterministic():
    assert fixture_actions("refund_authorization")==fixture_actions("refund_authorization")
