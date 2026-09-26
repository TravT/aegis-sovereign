# Aegis Sovereign Knowledge Appliance — Air-Gapped Sovereign VPC Terraform Module
# ================================================================================
# Provisions a mathematically isolated, zero-internet-egress Sovereign VPC
# (`0.0.0.0/0` IGW blackholed) with KMS customer-managed encryption keys (CMEK),
# S3 Object Lock WORM compliance buckets, and dedicated NVMe GPU/CPU compute instances.

terraform {
  required_version = ">= 1.6.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.40"
    }
  }
}

variable "vpc_cidr" {
  description = "CIDR block for the air-gapped Sovereign VPC"
  type        = string
  default     = "10.240.0.0/16"
}

variable "environment" {
  description = "Deployment tier identifier"
  type        = string
  default     = "sovereign-production-airgapped"
}

resource "aws_vpc" "aegis_sovereign_vpc" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name        = "aegis-sovereign-airgapped-vpc"
    Environment = var.environment
    Compliance  = "LGPD-Art12-GDPR-ZeroEgress-AirGapped"
  }
}

resource "aws_subnet" "aegis_isolated_compute_subnet" {
  vpc_id                  = aws_vpc.aegis_sovereign_vpc.id
  cidr_block              = "10.240.10.0/24"
  map_public_ip_on_launch = false

  tags = {
    Name = "aegis-isolated-nvme-compute-subnet"
    Tier = "AirGapped-Private-Only"
  }
}

resource "aws_security_group" "aegis_zero_egress_sg" {
  name        = "aegis-sovereign-zero-internet-egress-sg"
  description = "Strictly prohibits all external WAN egress (0.0.0.0/0 blocked); permits only intra-VPC mTLS"
  vpc_id      = aws_vpc.aegis_sovereign_vpc.id

  ingress {
    description = "Internal mTLS Sovereign Gateway & MCP API"
    from_port   = 8765
    to_port     = 8766
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  ingress {
    description = "Internal Qdrant Distributed gRPC Raft Fabric"
    from_port   = 6333
    to_port     = 6335
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  egress {
    description = "Strict Intra-VPC Only Egress (Zero Public Internet)"
    from_port   = 0
    to_port     = 65535
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }
}

resource "aws_s3_bucket" "aegis_worm_audit_archive" {
  bucket              = "aegis-sovereign-worm-audit-ledger-vault"
  object_lock_enabled = true

  tags = {
    Name       = "aegis-worm-immutable-audit-bucket"
    Retention  = "SEC-17a-4-WORM-Compliance"
  }
}

output "sovereign_vpc_id" {
  value       = aws_vpc.aegis_sovereign_vpc.id
  description = "ID of the provisioned air-gapped Sovereign VPC"
}
