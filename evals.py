"""
Eval harness for the Migration Planner.

  python evals.py --selftest   # validate the checks themselves. No network,
                               # no credentials, no cost.

Families are kept separate on purpose, and the reason is not tidiness. A
flawless inventory can still produce a terrible plan, and a broken inventory
says nothing about the planner's logic. Mixing the two makes the selftest
dishonest: it starts passing for reasons nobody intended.

  CONTRACT_CHECKS — is the INPUT usable at all.

Later stories add the plan and negative families (IA-36 to IA-38). They extend
this file rather than adding a second test script: two copies of the same test
drift apart, which is the lesson this project already paid for once.
"""
import json
import sys

from inventory_contract import validate_inventory

CONTRACT_CHECKS = ("contract-ok",)


def check_inventory(inventory):
    return {"contract-ok": not validate_inventory(inventory)}


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

    print("self-test OK: the valid fixture passes; a dependency on a missing id is RED;")
    print("              duplicate ids and unknown roles are reported by name;")
    print("              the shipped example inventory satisfies its own contract.")
    print("  valid        :", good)
    print("  broken_deps  :", bad)
    print("               ->", broken_problems[0])
    print("  duplicate_id ->", duplicate_problems[0])
    print("  unknown_role ->", role_problems[0])
    print("  inventory/servers.json: %d servers, 0 violations" % len(real))
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    print("Nothing to run yet: the live gate arrives with the plan family (IA-38).")
    print("Use: python evals.py --selftest")
    sys.exit(0)
