terraform {
  required_version = ">= 1.10"

  backend "s3" {
    bucket       = "nana-terraform-state"
    key          = "namazu.tfstate"
    region       = "ap-northeast-1"
    use_lockfile = true
    encrypt      = true
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project = var.project
    }
  }
}

# CloudFront 用証明書などは us-east-1 が必要になる場面向けのエイリアス
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
  default_tags {
    tags = {
      Project = var.project
    }
  }
}
