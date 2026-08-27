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


if __name__ == "__main__":
    servers = load_inventory()
    print("Inventory loaded: %d servers, contract satisfied.\n" % len(servers))

    waves = plan_waves(servers)
    role_of = {server["id"]: server["role"] for server in servers}
    needs_of = {server["id"]: server["dependencies"] for server in servers}

    catalog = load_catalog()
    sized = size_plan(servers, waves, catalog)

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

    # The plan is checked before it is presented, using the same verifiers the
    # eval gate uses. Printing a plan without checking it is how a planner
    # starts being trusted for the wrong reasons.
    problems = verify_waves(servers, waves) + verify_sizing(servers, sized, catalog)
    print("Invariants: dependencies migrate first, and no target is smaller "
          "than its source — %s" % ("HOLD" if not problems else "VIOLATED"))
    for problem in problems:
        print("  - %s" % problem)

    if not catalog["verified"]:
        print("")
        print("WARNING: the price catalog declares verified=false. The figure above is")
        print("         arithmetic over numbers nobody has checked yet. See")
        print("         %s" % catalog["source"])
