resource "aws_s3_bucket" "bucket" {
  bucket = "${var.project_name}_bucket"
  tags = {
       Name = "${var.project_name}-bucket"
  }
}

resource "aws_s3_bucket_versioning" "bucket_versioning" {
  bucket = aws_s3_bucket.terraform_state.id

  versioning_configuration {
    status = "Enabled"
  }
}


resource "aws_s3_bucket_server_side_encryption_configuration" "bucket_encription" {
   bucket = aws_s3_bucket.terraform_state.id

   rule {
     apply_server_side_encryption_by_default {
       sse_algorithm = "AES256"
     }
   }
}

resource "aws_s3_bucket_public_access_block" "bucket_security" {
  bucket = aws_s3_bucket.terraform_state.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}