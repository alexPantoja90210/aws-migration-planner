# Benchmarking the Migration Planner against a real 100-server estate

**9 September 2026.** A sanitised, flattened extract from a real on-prem to AWS
migration project — 100 servers, agreed across several IT teams through repeated
review — was run through the planner. It arrived with the wave plan drawn during
that project.

**Why this run exists.** A planning tool that only ever runs on a fixture proves
nothing. Deciding whether it is worth anything needs a real estate and a decision
already made by people who had context the tool does not. That is what this is:
a benchmark, not an audit.

**What this file is about.** It reports on *this extract*. The dependency mapping
for that migration was done in the system of record, which this project has never
seen. Nothing here is a statement about those records (IA-82).

---

## Headline

| | |
| --- | --- |
| Servers | 100 |
| Declared dependency edges | 44 |
| Cycles in the graph | none |
| **Contract violations** — a dependency on a server absent from the inventory | **0** |
| Waves in the drawn plan | 4 |
| Waves the documented dependencies alone support | **2** |
| **Documented dependencies the two orderings disagree on** | **44 of 44** |
| Target cost **at public list prices** | **$11,976.85 / month · $143,722 / year** |

Prices: us-east-1, on-demand, Linux, snapshot dated 2026-08-26, `verified: true`.

**What that flag certifies, precisely (IA-81):** the rates and the instance specs
were checked by hand against the AWS pricing pages, so nothing was transcribed
wrong. **It does not certify that the figure is what anyone pays.** These are
public list prices. An estate of this size sits under a negotiated agreement, so
the number is an upper bound on the target, not a quote.

---

## 1. First result — the documented dependencies held

The contract check ran before anything else, and it passed clean:

| Check | Result |
| --- | --- |
| Servers ingested | 100 |
| Dependencies resolving to a server that exists | **44 of 44** |
| Contract violations | **0** |
| Cycles in the graph | **none** |

**This is a validation, and it is not a low bar.** The contract exists because
the MVP audit of this same planner found *its own* graph pointing at 4 servers
absent from the inventory. It is the class of problem this check hunts, and
against this data it found none. The dependency mapping had been done in the
system of record and it stood up to an instrument built to break it.

### A note on reading a flattened extract — claimed about nothing else

A CMDB stores a relationship once and derives both directions from it. A
spreadsheet cannot: flattening a graph into rows means the same relationship has
to be written from each side, and the written copies can disagree. In this
extract the `Dependencias` column carries several relations at once:

| Rows | What they wrote | How the converter reads it |
| --- | --- | --- |
| 40 Web/App, 4 Batch | `SRV-DB-PG-03` | **depends on** — resolves to a server, kept |
| 10 Postgres | `Web 21–22` | the reverse direction, written from the other side |
| 5 Oracle, 5 SQLite | `Web ERP`, `Dev` | reverse direction, informal |
| 20 FileServer | `Finanzas`, `RH`, `Ventas` | a department, not a server |
| 4 Monitoring, 4 Logging | `Todos Web` | a pattern, not an id |

The converter keeps only values that resolve to a server in the inventory and
**drops the other 48 rather than guessing at them**, counting and naming every
one. That is a decision about how to read an export, recorded so it can be
argued with.

**It is not a finding about the estate.** The shape of a flattened column says
nothing about the records it was flattened from, and this project has not seen
them (IA-82).

---

## 2. Second result — two orderings, two different objectives

The four waves group servers **by type**: infrastructure, then applications,
then databases, then file servers. That is what a spreadsheet holds well — a
**schedule**. The planner orders by dependency, which is what a graph holds — an
**invariant**. The two are not competing answers to one question; they are
answers to different ones.

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

Not some of the documented dependencies. **All forty-four.**

**What that does and does not mean.** `verify_waves` reports against one rule and
one rule only: nothing moves before what it depends on. It is blind to blast
radius, team availability, change windows and internal policy — all of which a
real wave plan carries and none of which exist in an inventory. So this is a
disagreement between two orderings with different objectives, not a verdict on
either.

What it does establish is that the invariant is checkable in seconds, by a
machine, against whatever plan people draw.

---

## 3. What the dependencies actually support

| Wave | Servers | Contents | Cost |
| --- | --- | --- | --- |
| 0 | 56 | all 20 databases, 20 file servers, monitoring, logging, tools, utility | $6,660.57 / mo |
| 1 | 44 | 40 Web/App, 4 Batch | $5,316.28 / mo |

**Two waves, not four** — because the documented dependencies describe one kind
of coupling. The extra structure in the four-wave plan is real operational
judgement the planner does not model, and two waves would be a worse plan to
execute. What the planner contributes is narrower: *whatever* the wave count,
the databases have to precede the applications that query them.

No dependency in this extract resolves onto the 20 file servers or the Oracle
and SQLite instances. From a migration-ordering standpoint those 30 machines
carry no ordering constraint *in this data*, which is schedulable slack — the
kind of thing worth confirming against the source records before acting on it.

---

## 4. Target sizing and cost

| Target | Count |
| --- | --- |
| `t3.xlarge` | 70 |
| `t3.medium` | 25 |
| `t3.2xlarge` | 5 |

Compute $10,476.85 (87%) · Storage $1,500.00 (13%) · **Total $11,976.85 / month**.

### Three limits stated, not buried

1. **These are public list prices, not negotiated rates (IA-81).** Any
   organisation running an estate this size pays less, by an amount this project
   does not know. The figure is an upper bound, not a costing. **No discount is
   modelled or estimated here** — inventing a percentage to make the number look
   defensible would be a worse defect than the one it papers over.
2. **The prices are a dated snapshot**, not a live pricing API query. Re-verify
   before presenting this to anyone as a costing figure.
3. **Sizing comes from declared CPU/RAM, not measured utilisation.** On-prem is
   usually over-provisioned, so this figure is a **ceiling**. With real
   utilisation data it would very likely come down — which makes it a
   conservative estimate, and that is the point.

Limits 1 and 3 push the same way: list price is the highest price anyone pays
and declared specs are the highest sizing anyone needs, so the figure is a
**ceiling on both axes**.

There is no saving claimed here. This is the cost of the target at list. A saving
needs what the current estate costs today, and that figure was not available.

---

## What this run concludes

**Neither ordering alone.** People keep owning the schedule, because the
judgement in it is real and the planner is blind to it. A machine checks the
invariant before anyone signs — seconds, and it fits in CI.

That is a product recommendation. *"The plan violates 44 dependencies"* would
not have been one, and stating it that way would have been a claim about people's
work that this data does not support.

---

## Reproducing it

```
python convert_inventory.py     # Excel -> servers-100.json, dropped values logged
python planner.py               # contract, graph, waves, sizing, TCO
```

The conversion keeps only edges that resolve to a server in the inventory. Every
discarded value is counted and named, so the 48 dropped entries are a visible
decision rather than a silent one.
