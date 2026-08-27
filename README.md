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
| Inventory validated against a contract | done |
| Dependency graph, cycle detection, wave ordering | done |
| Target sizing and monthly cost estimate | done |
| GREEN/RED gate wired into CI | done |

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

## Migration waves

The planner groups servers into ordered waves. The invariant, stated exactly as
the code implements it:

> **For every server S placed in wave N, every dependency of S sits in a wave
> strictly earlier than N.**

Two functions are kept deliberately apart:

* `plan_waves(inventory)` **builds** the plan — a topological layering, with
  ties inside a wave broken by id so the same inventory always yields the same
  plan, whatever order the file happens to be in.
* `verify_waves(inventory, waves)` **checks** a plan — any plan, from anywhere —
  against the inventory alone. It never calls `plan_waves`.

That separation is the point. A checker that regenerates the plan to compare
against would only ever confirm that the generator agrees with itself. The
selftest hands `verify_waves` a deliberately corrupted plan — two servers
swapped across waves, nothing else changed — and requires it to go red.

### Cycles

A cycle is made of ids that all exist, so it satisfies the inventory contract
without trouble. It is the planner's problem, not the contract's.

`find_cycle` returns the actual path, and `plan_waves` refuses to produce a plan:

```
CycleError: the dependency graph has a cycle and cannot be laid out in waves:
srv-a -> srv-c -> srv-b -> srv-a
```

Naming the path matters. "The graph has a cycle" sends whoever reads it hunting.

## Target sizing and cost

Every server gets a target instance type and an estimated monthly cost, both
derived from the inventory and a dated price catalog. The rule, stated once and
applied everywhere:

> **The recommended instance must have at least as many vCPU and at least as
> much RAM as the source server. Never less. Among the types that satisfy that,
> the cheapest wins.**

`verify_sizing` checks a sized plan without ever re-running the recommender: it
takes each recommendation as given and asks whether it respects headroom and
whether the arithmetic adds up. The selftest hands it a plan with one target
swapped for something smaller, and requires it to go red.

That the recommender picks the *cheapest* fitting type is a separate claim, and
it gets a separate assertion — checking it inside the verifier would mean
re-running the very thing under test.

### Two limits, stated plainly

**The prices are a snapshot, not a live query.** `pricing/ec2-us-east-1.json`
carries its region, its date, its source URL and a `verified` flag. The gate
does not check whether the prices are *correct* — nothing in this repo can know
that. It checks that the file says where they came from and whether a human has
confirmed them. **A price with no date is not an estimate.**

**Sizing from declared CPU and RAM is a starting point, not a final
recommendation.** With no real utilisation data this sizes against what was
*provisioned*, and on-prem provisioning is habitually generous. The figure means
"the same shape, in the cloud" — the right baseline to begin a migration from,
and the wrong number to stop at.

That second limit is the seam with the sibling project: the
[FinOps Guardian](https://github.com/alexPantoja90210/aws-finops-guardian)
reads actual CloudWatch utilisation from a live account. **This one predicts,
that one measures.**

## The example inventory

`inventory/servers.json` holds **10 servers** across three dependency levels:
six with no dependencies, three web servers on top of them, and one app server
on top of those. The count in this sentence and the count in the file are the
same number, and the selftest asserts the file satisfies its own contract.

The depth is not decoration. **On a flat graph the wave invariant holds
trivially, and a test that checks it would prove nothing** — the same trap that
hid a defect in the sibling project until a fixture with more than one item
exposed it.

## The evals gate

`evals.py --selftest` scores five families. They are kept apart deliberately: a
flawless inventory can still produce a terrible plan, and a plan can be correct
while the prices behind its cost figure have no provenance at all. Collapsing
those questions into one score makes the gate stop being honest.

| Family | Question it answers |
|---|---|
| `contract` | Is the input usable at all? |
| `plan` | Do the waves respect the dependency invariant, and is every server covered? |
| `sizing` | Does every target respect the headroom rule, and do the figures add up? |
| `provenance` | Does the price catalog say where its numbers came from? |
| `report` | Is every server accounted for — planned, or failed with a named reason? |

**The rule that governs a family:** a deliberately corrupted artifact must turn
**every** check in its family RED. A check that cannot fail for the reason its
family exists does not belong in it.

That rule has teeth here. `pricing-declared` used to sit inside the sizing
family, where a corrupted plan left it cheerfully GREEN — it measures the
catalog, not the plan. It now has its own family. The same defect, in the same
shape, is what IA-30 found in the sibling repository.

### The negative tests

Each family has an artifact built to fail, and the selftest requires it to:

* **contract** — a server depending on an id that is not in the inventory.
* **plan** — two servers swapped across waves, nothing else changed; and separately, a plan that simply forgets a server.
* **sizing** — a target smaller than its source; and a total edited by hand.
* **provenance** — a catalog with its `snapshot_date` removed.
* **report** — a server dropped from the plan with **no error recorded for it**.

That last one is the point of the whole family. The engine this project started
from could not fail: its `try/except` caught nothing and its error list was dead
code, so the report always came out perfect. **A report that cannot report a
problem is evidence of nothing.**

So a server the catalog cannot host is neither a crash nor a silent omission —
it is recorded with its cause, the rest of the plan still gets built, and the
report declares itself incomplete:

```
Reported, not dropped — 1 server(s) the catalog cannot host:
  - srv-db-01 (sizing): srv-db-01 needs 16 vCPU and 64 GiB and no type in the catalog offers both
```

**Partial is not the same as silent.** A planner that dies on one impossible
server tells you nothing about the others; one that quietly drops it is worse
than both.

### In CI

The gate runs on every push and pull request. It **needs no secrets** — the
planner never calls a model, so there is nothing here for a credential to
unlock. The workflow also runs `planner.py` end to end, because a plan that
imports cleanly and crashes on execution is not a working planner.

## Run it

```bash
python evals.py --selftest   # free: validates the checks themselves, both directions
python planner.py            # waves, target sizing and estimated monthly cost
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
