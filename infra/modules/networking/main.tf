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

resource "aws_eip" "nat_eip" {
  domain = "vpc"
   tags = {
       Name = "${var.project_name}-nat-eip"
  }
}

resource "aws_nat_gateway" "nat_gateway" {
  count = 2
  allocation_id = aws_eip.nat_eip.id
  subnet_id = aws_subnet.public_subnets[count.index].id

   tags = {
       Name = "${var.project_name}-nat"
  }

  depends_on = [ aws_internet_gateway.igw ]
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

resource "aws_subnet" "private_subnets" {
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

resource "aws_route_table" "public_route_table" {
   vpc_id = aws_vpc.main.id

   route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.igw.id
   }

    tags = {
      Name = "${var.project_name}-public-rt"
  }
}

resource "aws_route_table_association" "public_rt_association" {
    count = 2
    subnet_id = aws_subnet.public_subnets[count.index].id
    route_table_id = aws_route_table.public_route_table.id
}


resource "aws_route_table" "private_route_table" {
   vpc_id = aws_vpc.main.id

   route {
    cidr_block = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.nat_gateway.id
   }

    tags = {
      Name = "${var.project_name}-private-rt"
  }
}

resource "aws_route_table_association" "private_rt_association" {
    count = 5
    subnet_id = aws_subnet.private_subnets[count.index].id
    route_table_id = aws_route_table.private_route_table
}

resource "aws_security_group" "web" {
  name = "webpubsg"
  description = "security group for web tier"
  vpc_id = aws_vpc.main.id

  ingress{
    description = "HTTP"
    from_port = 80
    to_port = 80
    protocol = "tcp"
    cidr_blocks = [ "0.0.0.0/0" ]
  }

  ingress{
    description = "SSH"
    from_port = 22
    to_port = 22
    protocol = "tcp"
    cidr_blocks = [ "0.0.0.0/0" ]
  } 

  egress {
    from_port = 0
    to_port = 0
    protocol = "-1"
    cidr_blocks = [ "0.0.0.0/0" ]
  }

  tags = {
      Name = "${var.project_name}-webpubsg"
  }
}

resource "aws_security_group" "app" {
  name = "apppubsg"
  description = "security group for app tier"
  vpc_id = aws_vpc.main.id

   ingress{
    description = "HTTP"
    from_port = 80
    to_port = 80
    protocol = "tcp"
     security_groups = [
       aws_security_group.web
    ]
  }

  ingress{
    description = "SSH"
    from_port = 22
    to_port = 22
    protocol = "tcp"
    security_groups = [
       aws_security_group.web
    ]
  } 

   ingress {
    description = "ICMP from Web tier"
    from_port = -1
    to_port   = -1
    protocol  = "icmp"

    security_groups = [
       aws_security_group.web
    ]
  }

egress {
    description = "Internet through NAT"
    from_port = 0
    to_port = 0
    protocol = "-1"
    cidr_blocks = [ "0.0.0.0/0" ]
  }

  tags = {
      Name = "${var.project_name}-appprisg"
  }
}

resource "aws_security_group" "db" {
  name = "dbprisg"
  description = "security group for db"
  vpc_id =  aws_vpc.main.id

  ingress {
    description = "MySQL from Application tier"
    from_port = 5432
    to_port   = 5432
    protocol  = "tcp"

    security_groups = [
        aws_security_group.app.id
    ]
  }

 egress {
    from_port = 0
    to_port = 0
    protocol = "-1"
    cidr_blocks = ["0.0.0.0/0"]
 }
 tags ={
    Name = "${var.project_name}-dbprisg"
  }
}