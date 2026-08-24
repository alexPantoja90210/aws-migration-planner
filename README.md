# Migration Planner — on-prem → AWS, with the decisions derived in code

Takes an inventory of on-prem servers and produces the plan a migration
engineer needs **before** moving a single byte: waves ordered by dependency,
a sized target, an estimated cost, and a gate that can be shown to go red.

> **The pattern:** validated input → **decisions derived in code from the
> source** → **eval gate with negative tests** → a human approves.

## What this is not

This project **does not simulate AWS MGN or DMS**, and does not claim to.
Those services replicate disk blocks and run change data capture against live
databases; with no on-prem source there is nothing to replicate, and anyone
who has run a migration can tell the difference immediately.

What is entirely real, and is what this project does:

| Layer | Status |
|---|---|
| Inventory validated against a contract | this story |
| Dependency graph, cycle detection, wave ordering | next |
| Target sizing and monthly cost estimate | next |
| GREEN/RED gate wired into CI | next |

**The line: the decision layer is real. The data-movement layer is not
promised.** Stating that up front is the point, not a disclaimer.

## The inventory contract

`inventory_contract.py` defines the shape of a usable inventory in one place,
with no dependencies. `validate_inventory(inventory)` returns a list of
violations; an empty list means the planner may proceed.

It checks required fields and their types, unique ids, known roles and
operating systems, positive CPU/RAM/storage — and the one it exists for:

> **every id listed in `dependencies` must exist in the inventory.**

`load_inventory` refuses to load anything that violates the contract. It fails
loudly, naming the server and the missing id.

### Why that check earns its place

The inventory this project started from declared `srv-001` as depending on
`db-001`. There is no `db-001`. Four of ten servers pointed at ids that did not
exist, and nothing checked.

An inventory like that does not produce an obviously broken plan — it produces
a plan with a perfectly plausible shape, built around dependencies that
correspond to nothing. That is the expensive kind of wrong.

Note what the contract deliberately does **not** check: dependency *cycles*. A
cycle is made of ids that all exist, so it satisfies the contract. Detecting it
is the planner's job, and it belongs with the graph.

## The example inventory

`inventory/servers.json` holds **10 servers** across three dependency levels:
six with no dependencies, three web servers on top of them, and one app server
on top of those. The count in this sentence and the count in the file are the
same number, and the selftest asserts the file satisfies its own contract.

## Run it

```bash
python evals.py --selftest   # free: validates the checks themselves
python planner.py            # loads the inventory and prints what it found
```

The selftest makes no network calls and needs no credentials, so it runs in CI
at no cost.

## Related projects

The planner estimates what the target **will** cost. The
[AWS FinOps Guardian](https://github.com/alexPantoja90210/aws-finops-guardian)
measures what it **does** cost, read-only, from the real account. Prediction
against invoice.

The eval-gate pattern — invariant in code, negative test that must go red — is
the same one used in
[agentic-copilots](https://github.com/alexPantoja90210/agentic-copilots).
