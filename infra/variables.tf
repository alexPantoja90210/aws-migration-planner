###############################################################################
# Variables for the demonstrative migration target.
# No sensitive value lives here. Real values go in terraform.tfvars, which is
# in .gitignore and is never committed.
###############################################################################

variable "aws_region" {
  description = "Region the target lands in. Must match the region of the price catalog the planner used."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Name and tag prefix for every resource in the stack."
  type        = string
  default     = "migration-target"

  validation {
    condition     = can(regex("^[a-z0-9-]{3,32}$", var.project_name))
    error_message = "project_name must be lowercase letters, digits or hyphens, 3 to 32 characters long."
  }
}

variable "instance_type" {
  description = <<-EOT
    EC2 type for the demonstrative target. Restricted to free tier because this
    module exists to be planned and read, not to accumulate spend.

    Note what this is NOT: it is not the type the planner recommends. The
    planner sizes each server from its own CPU and RAM, and its answers range
    well beyond the free tier. This value is the demo's own choice.
  EOT
  type        = string
  default     = "t3.micro"

  validation {
    condition     = contains(["t2.micro", "t3.micro"], var.instance_type)
    error_message = "Only free-tier types are allowed here. IA-24 is the record of what t2.micro cost the sibling stack; t3.micro is the safe default."
  }
}

variable "ingress_cidr" {
  description = <<-EOT
    CIDR allowed to reach the target over HTTP. It must be the operator's own
    public IP as a /32. There is no default on purpose: leaving it unset forces
    an explicit decision instead of letting an oversight open the port.

    Find yours with: curl -s https://checkip.amazonaws.com
  EOT
  type        = string

  validation {
    condition     = can(cidrhost(var.ingress_cidr, 0))
    error_message = "ingress_cidr must be a valid CIDR, for example 203.0.113.17/32."
  }

  validation {
    condition     = var.ingress_cidr != "0.0.0.0/0"
    error_message = "0.0.0.0/0 opens the target to the whole internet. Use your own IP as a /32."
  }
}

variable "vpc_cidr" {
  description = "Address space of the target VPC."
  type        = string
  default     = "10.20.0.0/16"

  validation {
    condition     = can(cidrhost(var.vpc_cidr, 0))
    error_message = "vpc_cidr must be a valid CIDR."
  }
}

variable "public_subnet_cidr" {
  description = "Address space of the public subnet, inside vpc_cidr."
  type        = string
  default     = "10.20.1.0/24"

  validation {
    condition     = can(cidrhost(var.public_subnet_cidr, 0))
    error_message = "public_subnet_cidr must be a valid CIDR."
  }
}

variable "root_volume_size_gb" {
  description = "Root volume size. The free tier covers up to 30 GB of gp3 EBS per month."
  type        = number
  default     = 8

  validation {
    condition     = var.root_volume_size_gb >= 8 && var.root_volume_size_gb <= 30
    error_message = "Stay between 8 and 30 GB to remain inside the EBS free tier."
  }
}
