resource "aws_vpc" "main" {
  cidr_block = "10.0.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support = true
  tags = {
    Name = "main-vpc"
  }
}


resource "aws_subnet" "public_subnet_tier_0" {
  vpc_id = aws_vpc.main.id
  cidr_block = "10.0.0.0/24"
  availability_zone = "us-east-1a"
  map_public_ip_on_launch = true
  tags = {
    Name = "public-subnet-tier-0"
  }
}


resource "aws_subnet" "public_subnet_tier_1" {
  vpc_id = aws_vpc.main.id
  cidr_block = "10.0.1.0/24"
  availability_zone = "us-east-1b"
  map_public_ip_on_launch = true
  tags = {
    Name = "public-subnet-tier-1"
  }
}

resource "aws_subnet" "private_subnet_app_tier_0" {
  vpc_id = aws_vpc.main.id
  cidr_block = "10.0.10.0/24"
  availability_zone = "us-east-1a"
  map_public_ip_on_launch = false
  tags = {
    Name = "private-subnet-app-tier-0"
  }
}

resource "aws_subnet" "private_subnet_app_tier_1" {
  vpc_id = aws_vpc.main.id
  cidr_block = "10.0.11.0/24"
  availability_zone = "us-east-1b"
  map_public_ip_on_launch = false
  tags = {
    Name = "private-subnet-app-tier-1"
  }
}
 

resource "aws_subnet" "private_subnet_data_tier_0" {
  vpc_id = aws_vpc.main.id
  cidr_block = "10.0.20.0/24"
  availability_zone = "us-east-1a"
  map_public_ip_on_launch = false
  tags = {
    Name = "private-subnet-data-tier-0"
  }
}
 

 resource "aws_subnet" "private_subnet_data_tier_1" {
  vpc_id = aws_vpc.main.id
  cidr_block = "10.0.21.0/24"
  availability_zone = "us-east-1b"
  map_public_ip_on_launch = false
  tags = {
    Name = "private-subnet-data-tier-0"
  }
}


 resource "aws_subnet" "private_subnet_ops_tier_0" {
  vpc_id = aws_vpc.main.id
  cidr_block = "10.0.30.0/24"
  availability_zone = "us-east-1a"
  map_public_ip_on_launch = false
  tags = {
    Name = "private-subnet-data-tier-0"
  }
}