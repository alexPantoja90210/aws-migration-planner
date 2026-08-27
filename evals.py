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
  SIZING_CHECKS   — does the sized plan respect the headroom rule and add up,
                    and does the price catalog say where its numbers came from.

Later stories extend this file rather than adding a second test script: two
copies of the same test drift apart, which is the lesson this project already
paid for once.
"""
import json
import sys

from inventory_contract import validate_inventory
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
SIZING_CHECKS = ("sizing-valid", "pricing-declared")

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


def check_sizing(inventory, sized, catalog):
    """
    Score a sized plan. Like check_plan, it never regenerates what it measures:
    the recommendation comes in from outside and is judged against the source
    server and the catalog.

    `pricing-declared` does NOT assert that the prices are right — nothing in
    this repo can know that. It asserts the file says where they came from and
    whether a human has checked them. An undated price is not an estimate.
    """
    return {
        "sizing-valid": not verify_sizing(inventory, sized, catalog),
        "pricing-declared": all(field in catalog for field in PROVENANCE_FIELDS)
                            and isinstance(catalog["verified"], bool),
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
    assert all(good_sizing.values()), \
        "self-test failed: the generated sizing should hold up -> %s" % good_sizing

    # The negative test the story asks for: a target smaller than the source.
    # Nothing else is touched — same servers, same waves, one wrong instance type.
    undersized = json.loads(json.dumps(sized))
    undersized["waves"][0]["servers"][0]["target"] = "t3.micro"
    assert not check_sizing(real, undersized, catalog)["sizing-valid"], \
        "self-test failed: a target smaller than the source must be RED"

    headroom_problems = verify_sizing(real, undersized, catalog)
    assert any("must never be smaller" in p for p in headroom_problems), \
        "self-test failed: the violation must name the headroom rule -> %s" % headroom_problems

    # Arithmetic is part of the property too. A plan whose numbers do not add up
    # is not a cheaper plan, it is a wrong one.
    tampered = json.loads(json.dumps(sized))
    tampered["waves"][0]["servers"][0]["cost"]["total_usd"] = 1.0
    assert not check_sizing(real, tampered, catalog)["sizing-valid"], \
        "self-test failed: a tampered total must be RED"

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

    print("self-test OK: the valid fixture passes; a dependency on a missing id is RED;")
    print("              duplicate ids and unknown roles are reported by name;")
    print("              the shipped example inventory satisfies its own contract;")
    print("              the plan satisfies the wave invariant, a swapped plan is RED,")
    print("              the plan is deterministic and independent of file order,")
    print("              a cyclic graph is reported by name instead of looping,")
    print("              and no target is ever smaller than the server it replaces.")
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
