# `infra/` — a demonstrative migration target

The smallest landing zone a wave-0 server could actually be moved into.

This module exists so the planner does not point at infrastructure that only
exists in a diagram. It is deliberately small: **it is meant to be planned and
read, not to accumulate spend.**

---

## What it provisions

| Resource | Purpose |
|---|---|
| VPC + internet gateway | The address space the target lands in |
| Public subnet, **associated to its route table** | Somewhere with an actual way out |
| Security group | HTTP/80 from the operator's IP only; egress open to the AWS APIs |
| EC2 `t3.micro` + encrypted 8 GB gp3 | One migrated server, standing in for the wave |

## What it does not

**No RDS and no S3.** Both appeared in the starting MVP's outputs without
existing anywhere in its configuration. They were dropped rather than defined:
standing up a database to satisfy an output would burn credits on an account
that already has an expiry date (IA-25), and gains no argument. A `db`, a
`file` and a `print` server still appear in the planner's inventory, where they
cost nothing and demonstrate the same thing.

**No ten instances.** The planner computes waves for ten servers. This module
provisions one. Sizing the whole inventory for real is a spend decision, not a
code decision, and it is not this story's to make.

---

## The five defects this module fixes

Each one came from the starting MVP, and each is commented where it lives.

| # | Defect | Why it matters |
|---|---|---|
| 1 | `outputs.tf` referenced `aws_s3_bucket.files_bucket` and `aws_db_instance.postgres_rds`, which existed nowhere | The module could not reach `plan`. It failed at the first layer. |
| 2 | Hardcoded Amazon Linux AMI with `apt-get` in `user_data` | The apply succeeds, the instance boots, and provisioning silently does nothing. **A failure that looks like success.** |
| 3 | `t2.micro` | Not free-tier eligible on this account. Cost the sibling stack a broken apply — IA-24. |
| 4 | No `aws_route_table_association` | A route table attached to nothing routes nothing. The subnet was "public" in its name and in the diagram only. |
| 5 | No security group at all | Which means the default one, and dependence on nobody ever noticing. |

### Which layer catches which

| Defect | `validate` | `plan` | `apply` | Runtime |
|---|---|---|---|---|
| 1 · outputs referencing nothing | **caught** | — | — | — |
| 3 · `t2.micro` | passes | passes | **fails** | — |
| 5 · no security group | passes | passes | succeeds | **found by review, or by an incident** |
| 2 · `apt-get` on Amazon Linux | passes | passes | succeeds | **silently does nothing** |
| 4 · no route table association | passes | passes | succeeds | **unreachable subnet** |

Only **one** of the five stops at the first layer — and it is the one that made
the module look broken, which is the good case: it failed loudly and early.

The other four pass `validate` untouched. Two of them pass `apply` as well and
only appear once something is running: an instance that boots, reports healthy,
and was never provisioned; a subnet called public with no way out. **A green
check is evidence that the layer you ran had nothing to say — not that the
configuration is right.**

---

## Usage

### Requirements

- Terraform >= 1.6
- AWS credentials able to create VPC and EC2 resources

### Plan-first

```bash
cp terraform.tfvars.example terraform.tfvars
curl -s https://checkip.amazonaws.com          # your public IP
# edit terraform.tfvars: your IP as a /32

terraform init
terraform fmt -check
terraform validate
terraform plan -out=tfplan
```

`plan` creates nothing and costs nothing. **Review it before applying.**

### What to check in the plan

1. `cidr_ipv4` in the ingress rule — it must be your `/32`. If you see `0.0.0.0/0`, stop.
2. `aws_route_table_association.public` is present. Its absence is defect 4, and the plan is the last place it is visible.
3. `instance_type` is `t3.micro`.
4. The resolved `ami_id` is an `al2023` image, and `user_data` uses `dnf`.
5. The final count — all `to add`. Any unexpected `destroy` means the state is not clean.

### Applying

**Not part of IA-39.** This story delivers a module that validates and plans
cleanly; whether it is ever applied is a separate decision, made against the
credit balance and the account's expiry date. If it is applied, it is applied
plan-first with the evidence attached to its issue — the standard IA-7 set.

---

## Files that are never committed

`terraform.tfvars` · `terraform.tfstate*` · `.terraform/` · `tfplan` · `plan-*.txt`

The last two matter more than they look: **they contain the operator's public
IP** inside the security group rule. This is a public repository. Plan evidence
lives in Jira attachments, not here.

Verify the rules are live rather than assuming them:

```bash
git check-ignore -v terraform.tfvars tfplan
```

---

## References

- Origin issue: **IA-39** · Epic: **IA-34**
- Defects inherited from the MVP and inventoried in IA-34
- Lessons reused from the sibling stack: **IA-23** (ASCII in `GroupDescription`), **IA-24** (free-tier eligibility), **IA-25** (account expiry)
- The general rule, learned the hard way in `aws-finops-guardian`: **`validate` checks shape, `plan` checks the diff against state, and only `apply` checks that the provider accepts the values.**
