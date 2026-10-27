import pytest
from goalfault.rules import RuleSyntaxError,evaluate,names_used,parse_expression,parse_rule

STATE={"actor":"CUST-001","approvals":[{"order_id":"ORD-1","verified":True,"max_amount":200},{"order_id":"ORD-2","verified":1}],
       "orders":{"ORD-1":{"owner":"CUST-001","amount":180.0},"ORD-2":{"owner":"CUST-999","amount":74.0}},"roles":["agent"]}

def ev(source,**args):
    return evaluate(parse_expression(source),{"state":STATE,"args":args})

def test_comparisons_and_logic():
    assert ev("args.amount > 100 and args.amount <= 180",amount=180.0)
    assert not ev("args.amount > 100 or args.id == 'x'",amount=5,id="y")
    assert ev("not (1 == 2)") and ev("'a' < 'b'") and ev("-2 + 5 - 1 == 2")
    assert ev("state.orders[args.id].amount - 6 == 174",id="ORD-1")

def test_missing_values_are_null_not_errors():
    assert ev("state.orders[args.id] == null",id="NOPE")
    assert ev("state.orders[args.id].owner == null",id="NOPE")
    assert ev("state.nothing.deeper[3].x == null")
    assert ev("args.amount + 1 == null",amount="ten")

def test_mismatched_types_never_compare_true():
    assert not ev("args.amount > 100",amount=None)
    assert not ev("args.amount > 100",amount="500")
    assert not ev("'5' < 6")

def test_true_is_not_one():
    assert ev("count(state.approvals, item.verified == true)")==1
    assert not ev("1 == true") and ev("1 != true") and ev("1 == 1.0")

def test_collection_functions():
    assert ev("exists(state.approvals, item.order_id == args.id and item.verified == true and item.max_amount >= 150)",id="ORD-1")
    assert not ev("exists(state.approvals, item.order_id == args.id and item.verified == true)",id="ORD-2")
    assert ev("count(state.orders)")==2 and ev("count(state.orders, item.amount > 100)")==1
    assert ev("sum(state.orders, item.amount)")==254.0
    assert ev("all(state.orders, item.amount > 50)") and ev("len(state.roles)")==1
    assert not ev("exists(state.missing, true)") and ev("all(null, false)")

def test_membership():
    assert ev("'agent' in state.roles") and ev("args.id in state.orders",id="ORD-2")
    assert ev("args.role in ['admin', 'manager']",role="manager") and not ev("true in [1]")
    assert ev("'ORD' in args.id",id="ORD-9") and not ev("1 in 'abc'")

def test_nested_item_shadows_outer():
    assert ev("exists(state.orders, exists(state.approvals, item.order_id == 'ORD-1'))")

def test_parse_rule():
    rule=parse_rule("deny issue_refund when args.amount > 100")
    assert rule.tool=="issue_refund" and rule.source.startswith("deny")

@pytest.mark.parametrize("source,message",[
    ("args.amount >",                 "ended early"),
    ("args.amount > 100 100",         "Unexpected 100"),
    ("1 < 2 < 3",                     "Chained comparisons"),
    ("open('x')",                     "Unknown function 'open'"),
    ("__import__('os').system('x')",  "Unknown function '__import__'"),
    ("exists(state.orders)",          "takes 2 argument"),
    ("args.amount ** 2",              "Unexpected"),
    ("args; drop",                    "Unexpected character ';'"),
    ("lambda: 1",                     "Unexpected character ':'"),
    ("",                              "empty"),
])
def test_syntax_errors_are_reported_not_guessed(source,message):
    with pytest.raises(RuleSyntaxError,match=message):
        parse_expression(source)

def test_error_points_at_column():
    with pytest.raises(RuleSyntaxError) as err:
        parse_rule("deny refund when args.amount >> 1")
    assert err.value.position==30 and "column 31" in str(err.value)

def test_rule_needs_deny_and_when():
    for source in ("allow refund when true","deny refund if true","deny when true"):
        with pytest.raises(RuleSyntaxError): parse_rule(source)

def test_limits():
    with pytest.raises(RuleSyntaxError,match="longer than"):
        parse_expression("1 == 1 and "*300+"true")
    with pytest.raises(RuleSyntaxError,match="nested too deeply"):
        parse_expression("("*60+"1"+")"*60)

def test_names_used_skips_item_inside_collections():
    node=parse_expression("args.amount > 1 and exists(state.approvals, item.order_id == order.id)")
    assert names_used(node)==[("args",("amount",)),("state",("approvals",)),("order",("id",))]
    assert names_used(parse_expression("item.x"))==[("item",("x",))]
