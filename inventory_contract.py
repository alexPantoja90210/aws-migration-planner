"""
The inventory contract, defined once, with no dependencies.

An inventory that does not meet this contract must never reach the planner.
The reason is concrete: the starting MVP shipped an inventory where four of ten
servers declared dependencies on ids that did not exist (`db-001` .. `db-004`).
Nothing checked them. Any wave order built on that inventory would have been
fiction with a plausible shape — the planner would have carefully respected
dependencies that corresponded to nothing.

Same defect class as IA-27, in a different domain: a reference the consumer
accepts without checking it against the source.
"""

KNOWN_ROLES = ("web", "db", "file", "print", "app")

REQUIRED_FIELDS = {
    "id": str,
    "os": str,
    "cpu": int,
    "ram": int,
    "storage": int,
    "role": str,
    "dependencies": list,
}

KNOWN_OS = ("linux", "windows")


class InventoryContractError(Exception):
    """Raised when an inventory is loaded that does not meet the contract."""


def _server_label(index, server):
    """Name a server by its id when it has one, by position when it does not."""
    if isinstance(server, dict) and isinstance(server.get("id"), str) and server["id"]:
        return server["id"]
    return "servers[%d]" % index


def validate_inventory(inventory):
    """
    Return a list of contract violations. An empty list means the inventory is
    usable. Never raises: the caller decides what to do with the problems.
    """
    problems = []

    if not isinstance(inventory, list):
        return ["the inventory must be a list, got %s" % type(inventory).__name__]
    if not inventory:
        return ["the inventory is empty"]

    seen_ids = set()
    duplicates = set()

    for index, server in enumerate(inventory):
        label = _server_label(index, server)

        if not isinstance(server, dict):
            problems.append("%s: must be an object, got %s" % (label, type(server).__name__))
            continue

        for field, expected in REQUIRED_FIELDS.items():
            if field not in server:
                problems.append("%s: missing '%s'" % (label, field))
                continue
            value = server[field]
            # bool is a subclass of int in Python; a boolean cpu is not a cpu.
            if expected is int and (isinstance(value, bool) or not isinstance(value, int)):
                problems.append("%s: '%s' must be an integer, got %s"
                                % (label, field, type(value).__name__))
            elif expected is not int and not isinstance(value, expected):
                problems.append("%s: '%s' must be %s, got %s"
                                % (label, field, expected.__name__, type(value).__name__))

        server_id = server.get("id")
        if isinstance(server_id, str) and server_id:
            if server_id in seen_ids:
                duplicates.add(server_id)
            seen_ids.add(server_id)

        role = server.get("role")
        if isinstance(role, str) and role not in KNOWN_ROLES:
            problems.append("%s: unknown role '%s'. Known roles: %s"
                            % (label, role, ", ".join(KNOWN_ROLES)))

        operating_system = server.get("os")
        if isinstance(operating_system, str) and operating_system not in KNOWN_OS:
            problems.append("%s: unknown os '%s'. Known: %s"
                            % (label, operating_system, ", ".join(KNOWN_OS)))

        for field in ("cpu", "ram", "storage"):
            value = server.get(field)
            if isinstance(value, int) and not isinstance(value, bool) and value <= 0:
                problems.append("%s: '%s' must be greater than zero, got %s"
                                % (label, field, value))

    for duplicate in sorted(duplicates):
        problems.append("duplicate id '%s': ids must be unique, they are what "
                        "dependencies point at" % duplicate)

    # The check this contract exists for. It runs last on purpose: it needs the
    # full set of ids, so it cannot be decided one server at a time.
    for index, server in enumerate(inventory):
        if not isinstance(server, dict):
            continue
        label = _server_label(index, server)
        dependencies = server.get("dependencies")
        if not isinstance(dependencies, list):
            continue
        for dependency in dependencies:
            if not isinstance(dependency, str):
                problems.append("%s: dependency must be a string id, got %s"
                                % (label, type(dependency).__name__))
            elif dependency == server.get("id"):
                problems.append("%s: depends on itself" % label)
            elif dependency not in seen_ids:
                problems.append("%s: depends on '%s', which is not in the inventory"
                                % (label, dependency))

    return problems


def describe_problems(source, problems):
    """One readable block, for an exception message or a log line."""
    return "%s does not meet the inventory contract:\n  - %s" % (
        source, "\n  - ".join(problems))
