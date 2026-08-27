"""
Eval harness for the Migration Planner.

  python evals.py --selftest   # validate the checks themselves. No network,
                               # no credentials, no cost.

Families are kept separate on purpose, and the reason is not tidiness. A
flawless inventory can still produce a terrible plan, and a broken inventory
says nothing about the planner's logic. Mixing the two makes the selftest
dishonest: it starts passing for reasons nobody intended.

  CONTRACT_CHECKS — is the INPUT usable at all.
  PLAN_CHECKS     — does a produced plan hold up against the inventory.
  SIZING_CHECKS   — does the sized plan respect the headroom rule and add up.
  PROVENANCE_CHECKS — does the price catalog say where its numbers came from.
  REPORT_CHECKS   — is every server in the inventory accounted for: planned, or
                    failed with a named reason. Never neither, never both.

The rule that governs a family: a deliberately corrupted artifact must turn
EVERY check of its family RED. A check that cannot fail for the reason its
family exists does not belong in it — that is why provenance was moved out of
SIZING_CHECKS, and it is the defect IA-30 found the last time it happened.

Later stories extend this file rather than adding a second test script: two
copies of the same test drift apart, which is the lesson this project already
paid for once.
"""
import json
import sys

from inventory_contract import validate_inventory
from planner import build_report, verify_report
from sizing import (
    SizingError,
    load_catalog,
    recommend_instance,
    satisfies_headroom,
    size_plan,
    verify_sizing,
)
from waves import CycleError, find_cycle, plan_waves, verify_waves

CONTRACT_CHECKS = ("contract-ok",)
PLAN_CHECKS = ("plan-valid",)
SIZING_CHECKS = ("sizing-valid",)
PROVENANCE_CHECKS = ("pricing-declared",)
REPORT_CHECKS = ("report-valid", "every-server-accounted")

PROVENANCE_FIELDS = ("region", "snapshot_date", "source", "verified")


def check_inventory(inventory):
    return {"contract-ok": not validate_inventory(inventory)}


def check_plan(inventory, waves):
    """
    Score a plan. Note what this does NOT do: it never calls plan_waves.

    The plan comes in from outside and is measured against the inventory alone.
    A checker that regenerates the plan to compare would only ever confirm that
    the generator agrees with itself.
    """
    return {"plan-valid": not verify_waves(inventory, waves)}


def check_sizing(inventory, sized, catalog, excused=()):
    """
    Score a sized plan. Like check_plan, it never regenerates what it measures:
    the recommendation comes in from outside and is judged against the source
    server and the catalog.
    """
    return {
        "sizing-valid": not verify_sizing(inventory, sized, catalog,
                                          excused=excused),
    }


def check_provenance(catalog):
    """
    Does the catalog say where its numbers came from?

    This does NOT assert the prices are correct — nothing in this repo can know
    that. It asserts the file declares its region, its date, its source, and
    whether a human has checked it. An undated price is not an estimate.

    It has its own family on purpose. Left inside SIZING_CHECKS it could never
    go RED for the reason that family exists, which silently breaks the rule
    that a corrupted plan turns its whole family RED.
    """
    return {
        "pricing-declared": all(field in catalog for field in PROVENANCE_FIELDS)
                            and isinstance(catalog["verified"], bool),
    }


def check_report(inventory, report, catalog):
    """
    Score a whole report: plan, sizing, and the servers that could not be sized.

    `every-server-accounted` is computed here from the sets themselves instead
    of being delegated to verify_report. Two independent routes to the same
    property is the point — if one of them is wrong, the selftest says so
    instead of agreeing with itself.
    """
    planned = {entry["id"] for wave in report["sizing"]["waves"]
               for entry in wave["servers"]}
    failed = {entry.get("id") for entry in report["errors"]}
    expected = {server["id"] for server in inventory}
    return {
        "report-valid": not verify_report(inventory, report, catalog),
        "every-server-accounted": (planned | failed) == expected
                                  and not (planned & failed),
    }


def _load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def selftest():
    valid = _load("fixtures/valid.json")
    broken_deps = _load("fixtures/broken_deps.json")
    duplicate_id = _load("fixtures/duplicate_id.json")
    unknown_role = _load("fixtures/unknown_role.json")
    real = _load("inventory/servers.json")

    good = check_inventory(valid)
    bad = check_inventory(broken_deps)

    assert all(good.values()), "self-test failed: the valid fixture should pass -> %s" % good
    assert not any(bad.values()), \
        "self-test failed: a dependency on a non-existent id must be RED -> %s" % bad

    # The message has to name the offender. A contract that reports "invalid
    # inventory" and nothing else forces whoever reads it to go hunting.
    broken_problems = validate_inventory(broken_deps)
    assert any("srv-b" in p and "db-001" in p for p in broken_problems), \
        "self-test failed: the violation must name the server and the missing id -> %s" % broken_problems

    duplicate_problems = validate_inventory(duplicate_id)
    assert any("duplicate id" in p for p in duplicate_problems), \
        "self-test failed: a duplicate id must be reported -> %s" % duplicate_problems

    role_problems = validate_inventory(unknown_role)
    assert any("unknown role" in p for p in role_problems), \
        "self-test failed: an unknown role must be reported -> %s" % role_problems

    # The shipped example inventory is part of the repo's claims. If it does not
    # meet its own contract, the README is lying to whoever clones it.
    real_problems = validate_inventory(real)
    assert not real_problems, \
        "self-test failed: the example inventory must satisfy its own contract -> %s" % real_problems

    # ---- plan family (IA-36) ----
    waves = plan_waves(real)

    good_plan = check_plan(real, waves)
    assert all(good_plan.values()), \
        "self-test failed: the generated plan should satisfy the invariant -> %s" % good_plan

    # Swap one server with a dependency of its own across waves. Nothing else
    # changes: same servers, same count, only the order is wrong. That is the
    # failure the invariant exists to catch.
    corrupted = [list(wave) for wave in waves]
    corrupted[0].remove("srv-002")
    corrupted[1].remove("srv-001")
    corrupted[0].append("srv-001")
    corrupted[1].append("srv-002")

    swapped = check_plan(real, corrupted)
    assert not any(swapped.values()), \
        "self-test failed: a swapped plan must be RED, otherwise the check proves nothing -> %s" % swapped

    swap_problems = verify_waves(real, corrupted)
    assert any("srv-001" in p and "srv-002" in p for p in swap_problems), \
        "self-test failed: the violation must name both servers -> %s" % swap_problems

    # A plan that simply forgets a server is also invalid. Coverage is part of
    # the property, not a separate nicety.
    missing = [list(wave) for wave in waves]
    missing[-1] = [s for s in missing[-1] if s != "srv-007"]
    assert not any(check_plan(real, missing).values()), \
        "self-test failed: a plan that drops a server must be RED"

    # Determinism: same inventory, same plan, byte for byte.
    assert json.dumps(plan_waves(real)) == json.dumps(waves), \
        "self-test failed: two runs produced different plans"

    # And the file order must not decide anything.
    assert json.dumps(plan_waves(list(reversed(real)))) == json.dumps(waves), \
        "self-test failed: reversing the inventory changed the plan; the file order is deciding"

    # A cycle is reported by name, and never loops forever.
    cycle_inventory = _load("fixtures/cycle.json")
    assert not validate_inventory(cycle_inventory), \
        "self-test failed: the cycle fixture should satisfy the CONTRACT — cycles are the planner's problem"
    cycle_path = find_cycle(cycle_inventory)
    assert cycle_path, "self-test failed: the cycle was not detected"
    try:
        plan_waves(cycle_inventory)
        raise AssertionError("self-test failed: planning a cyclic graph should raise CycleError")
    except CycleError as error:
        assert "srv-a" in str(error), \
            "self-test failed: the cycle error must name the servers involved -> %s" % error

    # ---- sizing family (IA-37) ----
    catalog = load_catalog()
    sized = size_plan(real, waves, catalog)

    good_sizing = check_sizing(real, sized, catalog)
    good_provenance = check_provenance(catalog)
    assert all(good_sizing.values()), \
        "self-test failed: the generated sizing should hold up -> %s" % good_sizing
    assert all(good_provenance.values()), \
        "self-test failed: the catalog must declare its provenance -> %s" % good_provenance

    # Provenance has its own negative: strip the date and the family must go RED.
    undated = json.loads(json.dumps(catalog))
    undated.pop("snapshot_date")
    assert not any(check_provenance(undated).values()), \
        "self-test failed: a catalog with no date must be RED"

    # The negative test the story asks for: a target smaller than the source.
    # Nothing else is touched — same servers, same waves, one wrong instance type.
    undersized = json.loads(json.dumps(sized))
    undersized["waves"][0]["servers"][0]["target"] = "t3.micro"
    assert not any(check_sizing(real, undersized, catalog).values()), \
        "self-test failed: a target smaller than the source must turn the WHOLE sizing family RED"

    headroom_problems = verify_sizing(real, undersized, catalog)
    assert any("must never be smaller" in p for p in headroom_problems), \
        "self-test failed: the violation must name the headroom rule -> %s" % headroom_problems

    # Arithmetic is part of the property too. A plan whose numbers do not add up
    # is not a cheaper plan, it is a wrong one.
    tampered = json.loads(json.dumps(sized))
    tampered["waves"][0]["servers"][0]["cost"]["total_usd"] = 1.0
    assert not any(check_sizing(real, tampered, catalog).values()), \
        "self-test failed: a tampered total must turn the WHOLE sizing family RED"

    # Separate claim, separate assertion: the recommender picks the CHEAPEST
    # type that satisfies headroom. verify_sizing deliberately does not check
    # this — it would have to re-run the recommender to do so.
    for server in real:
        chosen = recommend_instance(server, catalog)
        cheaper = [t for t in catalog["instance_types"]
                   if satisfies_headroom(t, server)
                   and t["usd_per_hour"] < chosen["usd_per_hour"]]
        assert not cheaper, \
            "self-test failed: %s got %s but %s also fits and costs less" \
            % (server["id"], chosen["name"], cheaper[0]["name"])

    # A server nothing in the catalog can host is a finding, not a crash.
    try:
        recommend_instance({"id": "srv-huge", "cpu": 4096, "ram": 8192,
                            "storage": 10}, catalog)
        raise AssertionError("self-test failed: an unsatisfiable server should raise SizingError")
    except SizingError as error:
        assert "srv-huge" in str(error), \
            "self-test failed: the sizing error must name the server -> %s" % error

    # ---- report family (IA-38) ----
    # The whole plan as data, including the servers that could not be sized.
    report = build_report(real, catalog)
    good_report = check_report(real, report, catalog)
    assert all(good_report.values()), \
        "self-test failed: the report over a healthy inventory should hold -> %s" % good_report
    assert report["complete"] and not report["errors"], \
        "self-test failed: the example inventory should produce no errors"

    # An inventory the catalog cannot fully host. It meets the CONTRACT — being
    # too big for every instance type is the planner's problem, not the
    # contract's, the same way a cycle is.
    unsizeable = _load("fixtures/unsizeable.json")
    assert not validate_inventory(unsizeable), \
        "self-test failed: the unsizeable fixture must satisfy the contract"

    partial = build_report(unsizeable, catalog)
    assert partial["errors"], \
        "self-test failed: a server no type can host must produce an error, not a crash"
    assert not partial["complete"], \
        "self-test failed: a report carrying errors must not claim to be complete"
    assert any(e["id"] == "srv-db-01" for e in partial["errors"]), \
        "self-test failed: the error must name the offending server -> %s" % partial["errors"]

    # A PARTIAL report is still a VALID report: the other two servers are
    # planned, the third is explained, and nothing is lost.
    assert all(check_report(unsizeable, partial, catalog).values()), \
        "self-test failed: a partial report is still valid if every server is accounted for -> %s" \
        % check_report(unsizeable, partial, catalog)

    # The negative that makes `errors` load-bearing instead of decorative:
    # drop the failure record and keep the truncated plan. Nothing else changes.
    # This is exactly what the starting MVP did — a report that always looked
    # perfect because it could not report a problem.
    silent = json.loads(json.dumps(partial))
    silent["errors"] = []
    silent["complete"] = True
    silent_scores = check_report(unsizeable, silent, catalog)
    assert not any(silent_scores.values()), \
        "self-test failed: a server dropped with no error recorded must turn the WHOLE report family RED -> %s" \
        % silent_scores

    print("self-test OK: the valid fixture passes; a dependency on a missing id is RED;")
    print("              duplicate ids and unknown roles are reported by name;")
    print("              the shipped example inventory satisfies its own contract;")
    print("              the plan satisfies the wave invariant, a swapped plan is RED,")
    print("              the plan is deterministic and independent of file order,")
    print("              a cyclic graph is reported by name instead of looping,")
    print("              no target is ever smaller than the server it replaces,")
    print("              and every server is either planned or explained by name.")
    print("  valid        :", good)
    print("  broken_deps  :", bad)
    print("               ->", broken_problems[0])
    print("  duplicate_id ->", duplicate_problems[0])
    print("  unknown_role ->", role_problems[0])
    print("  inventory/servers.json: %d servers, 0 violations" % len(real))
    print("  waves        :", " | ".join("w%d: %s" % (i, ", ".join(w))
                                         for i, w in enumerate(waves)))
    print("  good plan    :", good_plan)
    print("  swapped plan :", swapped, " <- must be False; it is what proves the check works")
    print("               ->", swap_problems[0])
    print("  cycle        ->", " -> ".join(cycle_path))
    print("  sizing       :", good_sizing)
    print("  undersized   -> %s" % headroom_problems[0])
    print("  provenance   :", good_provenance)
    print("  report       :", good_report)
    print("  partial      : %d planned, %d reported -> %s"
          % (len(unsizeable) - len(partial["errors"]), len(partial["errors"]),
             partial["errors"][0]["reason"]))
    print("  silent drop  :", silent_scores, " <- both must be False")
    print("  total        : $%s USD/month, region %s, prices dated %s"
          % (sized["total_monthly_usd"], sized["region"], sized["pricing_snapshot_date"]))
    if not catalog["verified"]:
        print("")
        print("  !! PRICES NOT VERIFIED. The catalog declares verified=false, so the")
        print("     total above is arithmetic over unchecked numbers. Check every value")
        print("     against %s," % catalog["source"])
        print("     set verified=true and update snapshot_date before presenting this")
        print("     as a costing figure.")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    print("Nothing to run against live data yet. Use: python evals.py --selftest")
    sys.exit(0)
