"""
Migration Planner — the loader.

Right now this module only loads and validates. The dependency graph, the wave
ordering, the rightsizing and the cost estimate arrive in later stories; each
of them will read the inventory through `load_inventory`, so none of them can
ever run on data that does not meet the contract.
"""
import json

from inventory_contract import (
    InventoryContractError,
    describe_problems,
    validate_inventory,
)

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
    print("Inventory loaded: %d servers, contract satisfied." % len(servers))
    for server in servers:
        depends_on = ", ".join(server["dependencies"]) or "-"
        print("  %-8s %-6s depends on: %s" % (server["id"], server["role"], depends_on))
