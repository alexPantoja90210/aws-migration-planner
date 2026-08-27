"""
Dependency graph and migration waves.

The invariant this module exists to guarantee:

    For every server S placed in wave N, every dependency of S sits in a wave
    strictly earlier than N.

Two things are kept deliberately apart:

  * `plan_waves` BUILDS the plan.
  * `verify_waves` CHECKS a plan — any plan, however it was produced.

The tests use the verifier. That separation is the whole point: checking an
algorithm with itself proves only that it is consistent with its own mistakes.
The verifier reads the inventory and the plan, and knows nothing about how the
plan came to be.

Cycles are this module's business, not the contract's. A cycle is made of ids
that all exist, so it satisfies the inventory contract without trouble. What a
cycle means is that the inventory describes something that cannot be migrated
in pieces — a real finding, reported by name.
"""

class CycleError(Exception):
    """Raised when the dependency graph cannot be laid out in waves."""


def build_graph(inventory):
    """
    Return (dependencies, dependents).

    `dependencies[s]` — what s needs before it can move.
    `dependents[d]`   — who is waiting on d.
    """
    dependencies = {server["id"]: list(server.get("dependencies", []) or [])
                    for server in inventory}
    dependents = {server_id: [] for server_id in dependencies}
    for server_id, needs in dependencies.items():
        for needed in needs:
            dependents[needed].append(server_id)
    return dependencies, dependents


def find_cycle(inventory):
    """
    Return one concrete cycle as a list of ids, or None.

    Returning the actual path matters. "The graph has a cycle" sends whoever
    reads it hunting; "srv-a -> srv-b -> srv-a" tells them where to look.
    """
    dependencies, _ = build_graph(inventory)
    UNVISITED, IN_PROGRESS, DONE = 0, 1, 2
    state = {server_id: UNVISITED for server_id in dependencies}
    stack = []

    def walk(node):
        state[node] = IN_PROGRESS
        stack.append(node)
        for needed in sorted(dependencies.get(node, [])):
            if needed not in state:
                continue  # the contract already rejects unknown ids
            if state[needed] == IN_PROGRESS:
                start = stack.index(needed)
                return stack[start:] + [needed]
            if state[needed] == UNVISITED:
                found = walk(needed)
                if found:
                    return found
        stack.pop()
        state[node] = DONE
        return None

    for server_id in sorted(state):
        if state[server_id] == UNVISITED:
            found = walk(server_id)
            if found:
                return found
    return None


def plan_waves(inventory):
    """
    Group the servers into ordered waves.

    Wave 0 holds everything with no dependencies. Wave N holds the servers whose
    dependencies all sit in earlier waves. Ties inside a wave are broken by id,
    so the same inventory always produces the same plan.
    """
    cycle = find_cycle(inventory)
    if cycle:
        raise CycleError(
            "the dependency graph has a cycle and cannot be laid out in waves: "
            + " -> ".join(cycle))

    dependencies, dependents = build_graph(inventory)
    pending = {server_id: len(needs) for server_id, needs in dependencies.items()}
    waves = []
    placed = set()

    while len(placed) < len(pending):
        ready = sorted(server_id for server_id, count in pending.items()
                       if count == 0 and server_id not in placed)
        if not ready:
            # Unreachable: find_cycle already ran. Kept as a guard so a future
            # change cannot turn this into a silent infinite loop.
            raise CycleError("no server is ready and not every server is placed; "
                             "the graph is not a DAG")
        waves.append(ready)
        placed.update(ready)
        for server_id in ready:
            for waiting in dependents[server_id]:
                pending[waiting] -= 1

    return waves


def verify_waves(inventory, waves):
    """
    Check a plan against the inventory. Returns a list of violations.

    Knows nothing about `plan_waves`. Give it a plan from anywhere — a hand
    written one, a corrupted one — and it will say whether the invariant holds.
    """
    problems = []
    known = {server["id"] for server in inventory}
    dependencies = {server["id"]: list(server.get("dependencies", []) or [])
                    for server in inventory}

    wave_of = {}
    for index, wave in enumerate(waves):
        for server_id in wave:
            if server_id in wave_of:
                problems.append("%s appears twice, in wave %d and wave %d"
                                % (server_id, wave_of[server_id], index))
            else:
                wave_of[server_id] = index
            if server_id not in known:
                problems.append("wave %d contains '%s', which is not in the inventory"
                                % (index, server_id))

    for server_id in sorted(known - set(wave_of)):
        problems.append("%s is in the inventory but in no wave" % server_id)

    for server_id, needs in sorted(dependencies.items()):
        if server_id not in wave_of:
            continue
        for needed in sorted(needs):
            if needed not in wave_of:
                problems.append("%s depends on '%s', which is in no wave"
                                % (server_id, needed))
            elif wave_of[needed] >= wave_of[server_id]:
                problems.append(
                    "%s is in wave %d but depends on %s, which is in wave %d — "
                    "a dependency must migrate first"
                    % (server_id, wave_of[server_id], needed, wave_of[needed]))

    return problems
