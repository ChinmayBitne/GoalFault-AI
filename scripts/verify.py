"""Quick isolated smoke check; no API key required."""
from goalfault.fixtures import seed_scenarios
from goalfault.simulator import fixture_run,minimize_failure

for scenario in seed_scenarios():
    baseline=fixture_run(scenario.kind)
    guarded=fixture_run(scenario.kind,True)
    assert not baseline["evaluation"]["passed"]
    assert guarded["evaluation"]["passed"]
    assert minimize_failure(scenario.kind,baseline["trace"])
    print(f"OK {scenario.id}: baseline violates, guarded passes")
print("3 deterministic environments verified (not live Muse tests).")
