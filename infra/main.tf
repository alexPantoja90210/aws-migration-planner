###############################################################################
# A demonstrative migration target: the smallest landing zone a wave-0 server
# could actually be moved into.
#
# What this module is FOR: showing that the planner points at infrastructure
# that exists, compiles and plans cleanly. The five defects the starting MVP
# carried are fixed here, and each fix is commented where it lives.
#
# What this module is NOT: the real destination. It provisions one instance,
# not ten. It has no RDS and no S3 -- see outputs.tf for why that matters.
###############################################################################

# Resolved at plan time instead of hardcoded. AMI ids differ per region and go
# stale; the MVP pinned one and paired it with the wrong package manager.
data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "target" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name = "${var.project_name}-vpc"
  }
}

resource "aws_internet_gateway" "target" {
  vpc_id = aws_vpc.target.id

  tags = {
    Name = "${var.project_name}-igw"
  }
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.target.id
  cidr_block              = var.public_subnet_cidr
  availability_zone       = data.aws_availability_zones.available.names[0]
  map_public_ip_on_launch = true

  tags = {
    Name = "${var.project_name}-public"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.target.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.target.id
  }

  tags = {
    Name = "${var.project_name}-public-rt"
  }
}

# The association the MVP was missing, and the reason it mattered: a route
# table that exists but is attached to nothing routes nothing. The subnet was
# "public" in its name and in the diagram, and had no way out in reality.
# Nothing in `validate` catches that -- the configuration is perfectly valid,
# it is just wrong.
resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

# The MVP had no security group at all, which means the default one: open to
# everything inside the VPC and dependent on nobody ever noticing.
# ASCII only in the description -- EC2 rejects anything else at apply time, and
# neither validate nor plan will warn you (IA-23).
resource "aws_security_group" "target" {
  name        = "${var.project_name}-sg"
  description = "Minimal ingress for the demonstrative migration target"
  vpc_id      = aws_vpc.target.id

  tags = {
    Name = "${var.project_name}-sg"
  }
}

resource "aws_vpc_security_group_ingress_rule" "http" {
  security_group_id = aws_security_group.target.id
  description       = "HTTP from the operator IP only, never 0.0.0.0/0"
  cidr_ipv4         = var.ingress_cidr
  from_port         = 80
  to_port           = 80
  ip_protocol       = "tcp"
}

# Egress stays open, deliberately. Restricting it would require VPC endpoints,
# which cost money and would break the zero-spend premise of this account.
# A conscious trade-off, not an oversight.
resource "aws_vpc_security_group_egress_rule" "all" {
  security_group_id = aws_security_group.target.id
  description       = "Outbound to the AWS APIs and package repositories"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

resource "aws_instance" "target" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = var.instance_type
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.target.id]

  # dnf, not apt-get. The MVP pinned an Amazon Linux AMI and then ran Debian
  # package commands on it: the apply succeeds, the instance boots, and the
  # provisioning silently does nothing. A failure that looks like success is
  # the worst kind, and it is invisible to both validate and plan.
  user_data = <<-EOT
    #!/bin/bash
    dnf -y update
    dnf -y install nginx
    systemctl enable --now nginx
  EOT

  # Closes the classic SSRF path to the instance credentials. The right posture
  # should not depend on the blast radius happening to be small.
  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = var.root_volume_size_gb
    encrypted   = true
  }

  tags = {
    Name = "${var.project_name}-target"
  }
}
