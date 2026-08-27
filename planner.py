"""
Migration Planner — the loader.

Loads the inventory, requires it to meet the contract, lays it out in migration
waves, and sizes the target with an estimated monthly cost.

Everything downstream reads the inventory through `load_inventory`, so nothing
can ever run on data that does not meet the contract.
"""
import json

from inventory_contract import (
    InventoryContractError,
    describe_problems,
    validate_inventory,
)
from sizing import load_catalog, size_plan, verify_sizing
from waves import plan_waves, verify_waves

INVENTORY = []


def load_inventory(path="inventory/servers.json"):
    """
    Load the inventory and REQUIRE it to meet the contract.

    It fails loudly and immediately. The alternative — accepting whatever JSON
    shows up and letting each consumer cope — is how the starting MVP ended up
    ordering migration waves around servers that did not exist.
    """
    global INVENTORY
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    problems = validate_inventory(data)
    if problems:
        raise InventoryContractError(describe_problems(path, problems))
    INVENTORY = data
    return INVENTORY


def build_report(servers, catalog):
    """
    Build the whole plan as data, collecting per-server failures instead of
    aborting on the first one.

    A planner that dies on one impossible server tells you nothing about the
    other nine. One that quietly drops it is worse than both. So a failure is
    recorded, named and counted — and `verify_report` refuses any report where
    a server is neither planned nor explained.
    """
    errors = []
    waves = plan_waves(servers)
    sized = size_plan(servers, waves, catalog, errors=errors)
    return {
        "server_count": len(servers),
        "waves": waves,
        "sizing": sized,
        "errors": errors,
        "complete": not errors,
    }


def verify_report(servers, report, catalog):
    """
    Check a report without rebuilding it.

    The property this exists for, stated once:

        Every server in the inventory is accounted for — either it is in the
        plan, or it is in `errors` with a reason that names it. Never neither,
        never both.

    Like every verifier in this repo, it never calls the builder. It also
    refuses a report whose own summary contradicts its contents: claiming to be
    complete while carrying errors is a lie a report should not be able to tell.
    """
    excused = [entry.get("id") for entry in report["errors"]]
    problems = verify_waves(servers, report["waves"])
    problems += verify_sizing(servers, report["sizing"], catalog, excused=excused)

    for entry in report["errors"]:
        for field in ("id", "stage", "reason"):
            if not entry.get(field):
                problems.append("an error entry is missing '%s': %r"
                                % (field, entry))
        if entry.get("id") and entry.get("reason") and entry["id"] not in entry["reason"]:
            problems.append("the error recorded for %s does not name it in its "
                            "reason: %r" % (entry["id"], entry["reason"]))

    if report["complete"] != (not report["errors"]):
        problems.append("the report claims complete=%s while carrying %d error(s)"
                        % (report["complete"], len(report["errors"])))

    if report["server_count"] != len(servers):
        problems.append("the report claims %d servers, the inventory has %d"
                        % (report["server_count"], len(servers)))

    return problems


if __name__ == "__main__":
    servers = load_inventory()
    print("Inventory loaded: %d servers, contract satisfied.\n" % len(servers))

    role_of = {server["id"]: server["role"] for server in servers}
    needs_of = {server["id"]: server["dependencies"] for server in servers}

    catalog = load_catalog()
    report = build_report(servers, catalog)
    sized = report["sizing"]

    for wave in sized["waves"]:
        print("Wave %d — %d server(s), $%s/month"
              % (wave["wave"], len(wave["servers"]), wave["wave_total_usd"]))
        for entry in wave["servers"]:
            source = entry["source"]
            depends_on = ", ".join(needs_of[entry["id"]]) or "nothing"
            print("  %-8s %-6s %dvCPU/%dGiB/%dGB -> %-11s $%7.2f   after: %s"
                  % (entry["id"], role_of[entry["id"]], source["cpu"], source["ram"],
                     source["storage"], entry["target"], entry["cost"]["total_usd"],
                     depends_on))
        print("")

    print("Estimated target cost: $%s USD/month  (%s, on-demand, prices dated %s)"
          % (sized["total_monthly_usd"], sized["region"], sized["pricing_snapshot_date"]))

    if report["errors"]:
        print("Reported, not dropped — %d server(s) the catalog cannot host:"
              % len(report["errors"]))
        for entry in report["errors"]:
            print("  - %s (%s): %s" % (entry["id"], entry["stage"], entry["reason"]))
        print("")

    # The report is checked before it is presented, using the same verifiers the
    # eval gate uses. Printing a plan without checking it is how a planner
    # starts being trusted for the wrong reasons.
    problems = verify_report(servers, report, catalog)
    print("Invariants: dependencies migrate first, no target is smaller than "
          "its source, and every server is either planned or explained — %s"
          % ("HOLD" if not problems else "VIOLATED"))
    for problem in problems:
        print("  - %s" % problem)

    if not catalog["verified"]:
        print("")
        print("WARNING: the price catalog declares verified=false. The figure above is")
        print("         arithmetic over numbers nobody has checked yet. See")
        print("         %s" % catalog["source"])
