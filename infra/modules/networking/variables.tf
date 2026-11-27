variable "project_name" {
  description = "RIVET-AI"
  type        = string
  default     = "RIVET-AI"
}

variable "vpc_cidr" {
  description = "VPC CIDR"
  type        = string
  default     = "10.0.0.0/16"
}

variable "public_subnet_1_cidr" {
  description = "Public subnet 1 CIDR"
  type        = string
  default     = "10.0.0.0/24"
}

variable "public_subnet_2_cidr" {
  description = "Public subnet 2 CIDR"
  type        = string
  default     = "10.0.1.0/24"
}

variable "private_app_subnet_1_cidr" {
  description = "Private  app subnet 1 CIDR"
  type        = string
  default     = "10.0.10.0/24"
}

variable "private_app_subnet_2_cidr" {
  description = "Private app subnet 2 CIDR"
  type        = string
  default     = "10.0.11.0/24"
}

variable "private_data_subnet_1_cidr" {
  description = "Private data subnet 1 CIDR"
  type        = string
  default     = "10.0.20.0/24"
}

variable "private_data_subnet_2_cidr" {
  description = "Private data subnet 2 CIDR"
  type        = string
  default     = "10.0.21.0/24"
}

variable "private_ops_subnet_2_cidr" {
  description = "Private ops subnet a CIDR"
  type        = string
  default     = "10.0.30.0/24"
}