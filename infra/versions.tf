###############################################################################
# aws-migration-planner / infra
# Version pinning, matching the sibling repository on purpose: today's plan
# should be the same plan six months from now.
###############################################################################

terraform {
  required_version = ">= 1.6.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project   = var.project_name
      ManagedBy = "terraform"
      Repo      = "aws-migration-planner"
      Issue     = "IA-39"
    }
  }
}
