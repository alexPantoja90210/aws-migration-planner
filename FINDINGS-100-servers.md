# Running the Migration Planner against a real 100-server inventory

**9 September 2026.** A sanitised inventory from a real on-prem to AWS migration
project — 100 servers, agreed across several IT teams through repeated review —
was run through the planner. The inventory arrived with a wave plan already
drawn by people. This is what the planner said about it.

---

## Headline

| | |
| --- | --- |
| Servers | 100 |
| Declared dependency edges | 44 |
| Cycles in the graph | none |
| Waves the humans drew | 4 |
| Waves the dependencies support | **2** |
| **Edges the human plan violates** | **44 of 44 — 100%** |
| Target cost | **$11,976.85 / month · $143,722 / year** |

Prices: us-east-1, on-demand, Linux, snapshot dated 2026-08-26, `verified: true`
(checked by hand against the AWS pricing pages, specs as well as rates).

---

## 1. The dependency column holds three different relations

Only **44 of 100** rows use `Dependencias` to mean *what this server needs*.
The rest use the same column for the opposite relation, or for something that is
not a server at all:

| Rows | What they wrote | What it actually means |
| --- | --- | --- |
| 40 Web/App, 4 Batch | `SRV-DB-PG-03` | **depends on** — usable |
| 10 Postgres | `Web 21–22` | *consumed by* — the same edge, backwards |
| 5 Oracle, 5 SQLite | `Web ERP`, `Dev` | *consumed by*, informally |
| 20 FileServer | `Finanzas`, `RH`, `Ventas` | *used by a department* — not a server |
| 4 Monitoring, 4 Logging | `Todos Web` | *watches* — a pattern, not an id |

Only the first row is a dependency. The other 48 values were **dropped, not
guessed at**, and the conversion records every one of them.

### The duplicate is where the data drifted

Because the relationship was written twice — once from each side — the two
copies stopped agreeing:

| Database | Its own row claims | Servers that actually declare it |
| --- | --- | --- |
| `SRV-DB-PG-01` … `PG-10` | 2 consumers | **4** |
| `SRV-DB-PG-03` | 2 consumers | **8** |

**Every database understates its own coupling by half. `PG-03` understates it by
four times**, and four of its eight dependents are not web servers at all —
they are the nightly batch processes.

Read the database row to plan a cutover window, which is the natural thing to
do, and you take down twice what you expected. On `PG-03`, four times, including
batch jobs nobody mentioned.

**This is the same defect as two others found in this project the same week:**
a permission list maintained in two places that drifted (IA-46), and an IAM
policy whose description promised more than the code enforced (IA-75). The fix
is identical in all three — *state the relationship once, from one side, so it
cannot drift from itself*.

---

## 2. The human plan violates every dependency it has

The four waves group servers **by type**: infrastructure, then applications,
then databases, then file servers. Grouping by type is what a spreadsheet does
well. The problem is that the one real coupling in this estate runs the other
way.

`verify_waves` knows nothing about how a plan was produced. Given the four waves
as drawn, it returns:

```
44 violations

SRV-UTIL-03 is in wave 0 but depends on SRV-DB-PG-03, which is in wave 2
SRV-UTIL-04 is in wave 0 but depends on SRV-DB-PG-03, which is in wave 2
SRV-UTIL-11 is in wave 0 but depends on SRV-DB-PG-03, which is in wave 2
SRV-UTIL-12 is in wave 0 but depends on SRV-DB-PG-03, which is in wave 2
SRV-WEB-01  is in wave 1 but depends on SRV-DB-PG-01, which is in wave 2
... 39 more
```

* **40 application servers** move in wave 2, one wave **before** the databases
  they query.
* **4 batch servers** move in **wave 1 — the very first** — depending on a
  database that does not move until wave 3.

Not some of the dependencies. **All forty-four.**

The consequence is not academic: each of those servers either runs against
on-prem across a hybrid link nobody budgeted, or does not run.

---

## 3. What the dependencies actually support

| Wave | Servers | Contents | Cost |
| --- | --- | --- | --- |
| 0 | 56 | all 20 databases, 20 file servers, monitoring, logging, tools, utility | $6,660.57 / mo |
| 1 | 44 | 40 Web/App, 4 Batch | $5,316.28 / mo |

**Two waves, not four** — because only one kind of coupling exists in this
estate. The extra structure in the four-wave plan is real operational judgement
(blast radius, team availability, change windows) and the planner does not
model it. What the planner does say is that *whatever* the wave count, the
databases have to move before the applications, and today they do not.

Nothing declares a dependency on the 20 file servers or on the Oracle and
SQLite instances: their listed "dependencies" are departments and informal
labels. From a migration-ordering standpoint those 30 machines are free to move
in any wave — which is useful scheduling slack the four-wave plan does not use.

---

## 4. Target sizing and cost

| Target | Count |
| --- | --- |
| `t3.xlarge` | 70 |
| `t3.medium` | 25 |
| `t3.2xlarge` | 5 |

Compute $10,476.85 (87%) · Storage $1,500.00 (13%) · **Total $11,976.85 / month**.

### Two limits stated, not buried

1. **The prices are a dated snapshot**, not a live pricing API query. Re-verify
   before presenting this to anyone as a costing figure.
2. **Sizing comes from declared CPU/RAM, not measured utilisation.** On-prem is
   usually over-provisioned, so this figure is a **ceiling**. With real
   utilisation data it would very likely come down — which makes it a
   conservative estimate, and that is the point.

There is no saving claimed here. This is the cost of the target. A saving needs
what the current estate costs today, and that figure was not available.

---

## Reproducing it

```
python convert_inventory.py     # Excel -> servers-100.json, dropped values logged
python planner.py               # contract, graph, waves, sizing, TCO
```

The conversion keeps only edges that resolve to a server in the inventory. Every
discarded value is counted and named, so the 48 dropped entries are a visible
decision rather than a silent one.
