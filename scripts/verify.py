"""Quick isolated smoke check; no API key required."""
from goalfault.fixtures import seed_scenarios
from goalfault.quality import quality_report
from goalfault.simulator import fixture_run,minimize_failure
from goalfault.spec import registry

total=0
for spec in registry().values():
    for scenario in seed_scenarios(spec):
        baseline=fixture_run(scenario.kind,spec=spec)
        guarded=fixture_run(scenario.kind,True,spec)
        assert not baseline["evaluation"]["passed"]
        assert guarded["evaluation"]["passed"]
        assert minimize_failure(scenario.kind,baseline["trace"],spec)
        print(f"OK {scenario.id}: baseline violates, guarded passes")
        total+=1
    report=quality_report(spec)
    for check in report["checks"]:
        print(f"   {'pass' if check['ok'] else 'FAIL'}  {check['name']}: {check['detail']}")
    print(f"{spec.name}: quality bar {'met' if report['passed'] else 'NOT met (hidden from the dashboard)'}")
print(f"{total} deterministic environments verified across {len(registry())} domain(s) (not live Muse tests).")
