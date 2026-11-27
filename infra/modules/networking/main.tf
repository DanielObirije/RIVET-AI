resource "aws_vpc" "main" {
  cidr_block = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support = true
  tags = {
    Name = "${var.project_name}-vpc"
  }
}

resource "aws_internet_gateway" "igw" {
    vpc_id = aws_vpc.main.id
    tags = {
       Name = "${var.project_name}-igw"
  }
}

resource "aws_subnet" "public_subnets" {
  count = 2
  vpc_id = aws_vpc.main.id
  cidr_block =[
    var.public_subnet_1_cidr,
    var.public_subnet_2_cidr
   ]
  map_public_ip_on_launch = true

  tags = {
    Name = "${var.project_name}-public-subnet-${count.index + 1}-cidr"
  }
}

resource "aws_subnet" "public_subnets" {
  count = 5
  vpc_id = aws_vpc.main.id
  cidr_block =[
    var.private_app_subnet_1_cidr,
    var.private_app_subnet_2_cidr,
    var.private_data_subnet_1_cidr,
    var.private_data_subnet_2_cidr,
    var.private_ops_subnet_2_cidr,
   ]
  map_public_ip_on_launch = false

  tags = {
    Name = "${var.project_name}-public-subnet-${count.index + 1}-cidr"
  }
}
