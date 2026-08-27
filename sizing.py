"""
Target sizing and monthly cost, derived from the inventory.

Two honesty notes belong in the open, not in a footnote, because they are the
difference between an estimate and a number someone made up:

1. **The prices are a snapshot, not a live query.** The catalog file carries its
   own region, date, source and a `verified` flag. A cost figure whose prices
   have no date has nothing behind it.

2. **Sizing from declared CPU and RAM is a starting point, not a final
   recommendation.** Without real utilisation data this sizes against what was
   *provisioned*, and on-prem estimates are habitually generous. The number this
   module produces is "the same shape, in the cloud" — which is the right
   baseline for a migration, and the wrong number to stop at.

   That second limit is exactly what the FinOps Guardian addresses from the
   other side: it reads actual CloudWatch utilisation from a live account. The
   pair is the interesting part — this module predicts, that one measures.

The headroom rule, stated once and applied everywhere:

    The recommended instance must have at least as many vCPU and at least as
    much RAM as the source server. Never less. Among the types that satisfy
    that, the cheapest wins.
"""
import json

HOURS_PER_MONTH_DEFAULT = 730


class SizingError(Exception):
    """Raised when a server cannot be sized against the catalog."""


def load_catalog(path="pricing/ec2-us-east-1.json"):
    with open(path, encoding="utf-8") as handle:
        catalog = json.load(handle)
    for field in ("region", "snapshot_date", "source", "verified",
                  "instance_types", "storage"):
        if field not in catalog:
            raise SizingError("the price catalog is missing '%s'" % field)
    return catalog


def satisfies_headroom(instance_type, server):
    """The rule, in one place. Everything else refers to this."""
    return (instance_type["vcpu"] >= server["cpu"]
            and instance_type["ram_gib"] >= server["ram"])


def recommend_instance(server, catalog):
    """
    Cheapest type that satisfies the headroom rule.

    Ties are broken by name so the same inventory always yields the same plan.
    """
    candidates = [t for t in catalog["instance_types"]
                  if satisfies_headroom(t, server)]
    if not candidates:
        raise SizingError(
            "%s needs %d vCPU and %d GiB and no type in the catalog offers both"
            % (server["id"], server["cpu"], server["ram"]))
    candidates.sort(key=lambda t: (t["usd_per_hour"], t["name"]))
    return candidates[0]


def monthly_cost(server, instance_type, catalog):
    """Compute plus storage. Rounded once, at the end."""
    hours = catalog.get("hours_per_month", HOURS_PER_MONTH_DEFAULT)
    compute = instance_type["usd_per_hour"] * hours
    storage = server["storage"] * catalog["storage"]["gp3_usd_per_gb_month"]
    return {
        "compute_usd": round(compute, 2),
        "storage_usd": round(storage, 2),
        "total_usd": round(compute + storage, 2),
    }


def size_plan(inventory, waves, catalog, errors=None):
    """
    Attach a target type and a cost to every server, grouped by wave.

    Every figure here is computed. None of them is written by hand, and none of
    them comes from anywhere but the inventory and the dated catalog.

    If `errors` is a list, a server the catalog cannot host is appended to it
    with its cause and left out of the plan, instead of aborting the whole run.
    With `errors=None` the behaviour is the original one: the first unsizeable
    server raises.

    Partial is not the same as silent. A server left out of the plan MUST turn
    up in `errors` — that pairing is what `verify_report` checks, and it is what
    stops a planner from quietly losing a server.
    """
    by_id = {server["id"]: server for server in inventory}
    sized_waves = []
    total = 0.0

    for index, wave in enumerate(waves):
        entries = []
        wave_total = 0.0
        for server_id in wave:
            server = by_id[server_id]
            try:
                instance_type = recommend_instance(server, catalog)
            except SizingError as error:
                if errors is None:
                    raise
                errors.append({"id": server_id, "stage": "sizing",
                               "reason": str(error)})
                continue
            cost = monthly_cost(server, instance_type, catalog)
            entries.append({
                "id": server_id,
                "role": server["role"],
                "source": {"cpu": server["cpu"], "ram": server["ram"],
                           "storage": server["storage"]},
                "target": instance_type["name"],
                "target_vcpu": instance_type["vcpu"],
                "target_ram_gib": instance_type["ram_gib"],
                "cost": cost,
            })
            wave_total += cost["total_usd"]
        sized_waves.append({"wave": index, "servers": entries,
                            "wave_total_usd": round(wave_total, 2)})
        total += wave_total

    return {
        "region": catalog["region"],
        "pricing_snapshot_date": catalog["snapshot_date"],
        "pricing_verified": catalog["verified"],
        "waves": sized_waves,
        "total_monthly_usd": round(total, 2),
    }


def verify_sizing(inventory, sized, catalog, excused=()):
    """
    Check a sized plan. Never calls recommend_instance.

    `excused` lists the ids that failed sizing and were recorded as errors. They
    are allowed to be absent from the plan — but they must not ALSO appear in
    it. Being both planned and failed is a contradiction, and it is checked.

    It takes the plan as given and asks two questions the plan must answer on
    its own terms: does every recommendation respect the headroom rule, and does
    every figure add up. A checker that re-ran the recommender would only prove
    the recommender agrees with itself.
    """
    problems = []
    by_id = {server["id"]: server for server in inventory}
    types_by_name = {t["name"]: t for t in catalog["instance_types"]}
    hours = catalog.get("hours_per_month", HOURS_PER_MONTH_DEFAULT)
    per_gb = catalog["storage"]["gp3_usd_per_gb_month"]
    running_total = 0.0

    for wave in sized["waves"]:
        wave_sum = 0.0
        for entry in wave["servers"]:
            server = by_id.get(entry["id"])
            if server is None:
                problems.append("wave %d sizes '%s', which is not in the inventory"
                                % (wave["wave"], entry["id"]))
                continue

            instance_type = types_by_name.get(entry["target"])
            if instance_type is None:
                problems.append("%s targets '%s', which is not in the catalog"
                                % (entry["id"], entry["target"]))
                continue

            if not satisfies_headroom(instance_type, server):
                problems.append(
                    "%s has %d vCPU / %d GiB on-prem but targets %s with "
                    "%d vCPU / %d GiB — the target must never be smaller"
                    % (entry["id"], server["cpu"], server["ram"], entry["target"],
                       instance_type["vcpu"], instance_type["ram_gib"]))

            expected_compute = round(instance_type["usd_per_hour"] * hours, 2)
            expected_storage = round(server["storage"] * per_gb, 2)
            expected_total = round(instance_type["usd_per_hour"] * hours
                                   + server["storage"] * per_gb, 2)
            if entry["cost"]["compute_usd"] != expected_compute:
                problems.append("%s: compute cost is %s, expected %s"
                                % (entry["id"], entry["cost"]["compute_usd"], expected_compute))
            if entry["cost"]["storage_usd"] != expected_storage:
                problems.append("%s: storage cost is %s, expected %s"
                                % (entry["id"], entry["cost"]["storage_usd"], expected_storage))
            if entry["cost"]["total_usd"] != expected_total:
                problems.append("%s: total is %s, expected %s"
                                % (entry["id"], entry["cost"]["total_usd"], expected_total))
            wave_sum += entry["cost"]["total_usd"]

        if round(wave_sum, 2) != wave["wave_total_usd"]:
            problems.append("wave %d totals %s but its servers add up to %s"
                            % (wave["wave"], wave["wave_total_usd"], round(wave_sum, 2)))
        running_total += wave_sum

    if round(running_total, 2) != sized["total_monthly_usd"]:
        problems.append("the plan totals %s but its waves add up to %s"
                        % (sized["total_monthly_usd"], round(running_total, 2)))

    sized_ids = {entry["id"] for wave in sized["waves"] for entry in wave["servers"]}
    excused_ids = set(excused)
    for server_id in sorted(set(by_id) - sized_ids - excused_ids):
        problems.append("%s is in the inventory but was never sized" % server_id)
    for server_id in sorted(sized_ids & excused_ids):
        problems.append("%s is reported as a sizing error and also appears in "
                        "the plan — a server cannot be both" % server_id)

    return problems
