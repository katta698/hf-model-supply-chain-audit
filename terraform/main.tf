#
# The network half of the model supply chain control.
#
# The goal is that an inference workload CANNOT reach huggingface.co, even if
# someone writes from_pretrained("org/model") by habit. The usual approach is
# a NAT gateway plus firewall rules -- about $32/month and a ruleset somebody
# has to maintain. This does it by routing instead:
#
#   * a VPC with no internet gateway and no NAT, so there is no route out
#   * an S3 Gateway Endpoint (free) as the only way traffic leaves the subnet
#   * an endpoint policy allowing only the mirror bucket
#
# The control is the absence of a route, not a rule. Nothing to misconfigure,
# nothing to pay for, and it cannot be bypassed by editing a security group.
#
# Everything here is free tier or genuinely free. No NAT, no Interface
# endpoints (those bill ~$7/month each), no compute left running.
#

terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = "hf-model-supply-chain"
      ManagedBy = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}

locals {
  name        = "hf-model-mirror"
  bucket_arn  = "arn:aws:s3:::${var.bucket_name}"
  objects_arn = "arn:aws:s3:::${var.bucket_name}/*"
}

# ---------------------------------------------------------------------------
# Network: deliberately isolated. No IGW, no NAT, no route to anywhere.
# ---------------------------------------------------------------------------

resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = local.name }
}

resource "aws_subnet" "private" {
  vpc_id            = aws_vpc.this.id
  cidr_block        = var.subnet_cidr
  availability_zone = "${var.region}a"
  tags              = { Name = "${local.name}-private" }
}

# This route table has exactly one entry Terraform does not write: the
# implicit local route. No 0.0.0.0/0 exists, so there is no path to the
# internet from this subnet at all.
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = "${local.name}-private-no-egress" }
}

resource "aws_route_table_association" "private" {
  subnet_id      = aws_subnet.private.id
  route_table_id = aws_route_table.private.id
}

# ---------------------------------------------------------------------------
# The only way out: S3, and only the mirror bucket.
# A Gateway Endpoint is free; an Interface Endpoint would bill hourly.
# ---------------------------------------------------------------------------

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]

  # Defence in depth: even if an IAM policy were widened, the network path
  # only carries requests for this one bucket.
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = "*"
      Action    = ["s3:GetObject", "s3:ListBucket"]
      Resource  = [local.bucket_arn, local.objects_arn]
    }]
  })

  tags = { Name = "${local.name}-s3" }
}

# Egress is wide open on purpose. The demonstration is that the *routing*
# blocks the Hub -- tightening the security group would hide which control is
# actually doing the work.
resource "aws_security_group" "lambda" {
  name        = "${local.name}-lambda"
  description = "Allow all egress; the route table is what blocks the internet"
  vpc_id      = aws_vpc.this.id

  egress {
    description = "All egress permitted by the SG, and unroutable anyway"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${local.name}-lambda" }
}

# ---------------------------------------------------------------------------
# A Lambda in that subnet, to prove both halves of the claim.
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda" {
  name               = "${local.name}-prover"
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

# Managed policy for the ENI lifecycle a VPC Lambda needs.
resource "aws_iam_role_policy_attachment" "vpc" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

data "aws_iam_policy_document" "read_mirror" {
  statement {
    actions   = ["s3:GetObject"]
    resources = [local.objects_arn]
  }
  statement {
    actions   = ["s3:ListBucket"]
    resources = [local.bucket_arn]
  }
}

resource "aws_iam_role_policy" "read_mirror" {
  name   = "read-mirror"
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.read_mirror.json
}

data "archive_file" "handler" {
  type        = "zip"
  source_file = "${path.module}/lambda/handler.py"
  output_path = "${path.module}/.build/handler.zip"
}

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${local.name}-prover"
  retention_in_days = 1 # evidence only; nothing to keep
}

resource "aws_lambda_function" "prover" {
  function_name    = "${local.name}-prover"
  role             = aws_iam_role.lambda.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.13"
  filename         = data.archive_file.handler.output_path
  source_code_hash = data.archive_file.handler.output_base64sha256
  timeout          = 120
  memory_size      = 1024 # Lambda CPU scales with memory; hashing 90 MB at 256 MB is slow

  vpc_config {
    subnet_ids         = [aws_subnet.private.id]
    security_group_ids = [aws_security_group.lambda.id]
  }

  environment {
    variables = {
      MIRROR_BUCKET = var.bucket_name
      MODEL_REPO    = var.model_repo
    }
  }

  depends_on = [
    aws_iam_role_policy_attachment.vpc,
    aws_cloudwatch_log_group.lambda,
  ]
}

# ---------------------------------------------------------------------------
# Project B: actually serve the model from inside the boundary.
#
# P1 proved an approved model could get in. This proves it can do useful work
# there -- embeddings, on CPU, from the mirror, in a subnet with no route out.
# No GPU, no NAT, no Interface endpoints: Lambda reaches S3 over the gateway
# endpoint and nothing else.
# ---------------------------------------------------------------------------

data "archive_file" "serve" {
  type        = "zip"
  output_path = "${path.module}/.build/serve.zip"

  # Lambda layers must place packages under python/ -- at the zip root the
  # runtime simply will not find them.
  source_dir = "${path.module}/lambda-serve/layer"
}

# The handler is small and changes often; the dependency bundle is 123 MB and
# does not. Keeping them in one archive means a 40 MB upload for a one-line
# edit, so the handler ships as its own file layered on top.
data "archive_file" "serve_handler" {
  type        = "zip"
  source_file = "${path.module}/lambda-serve/handler.py"
  output_path = "${path.module}/.build/serve-handler.zip"
}

resource "aws_lambda_layer_version" "deps" {
  layer_name          = "${local.name}-onnx-deps"
  filename            = data.archive_file.serve.output_path
  source_code_hash    = data.archive_file.serve.output_base64sha256
  compatible_runtimes = ["python3.13"]
  description         = "onnxruntime, numpy, tokenizers. No HTTP client, no Hub client."
}

resource "aws_cloudwatch_log_group" "serve" {
  name              = "/aws/lambda/${local.name}-embed"
  retention_in_days = 1
}

resource "aws_lambda_function" "embed" {
  function_name    = "${local.name}-embed"
  role             = aws_iam_role.lambda.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.13"
  filename         = data.archive_file.serve_handler.output_path
  source_code_hash = data.archive_file.serve_handler.output_base64sha256
  layers           = [aws_lambda_layer_version.deps.arn]
  timeout          = 120
  memory_size      = 2048 # >1769 MB gives a full vCPU; ONNX is CPU-bound

  vpc_config {
    subnet_ids         = [aws_subnet.private.id]
    security_group_ids = [aws_security_group.lambda.id]
  }

  environment {
    variables = {
      MIRROR_BUCKET = var.bucket_name
      MODEL_REPO    = var.model_repo
      MODEL_FILE    = var.model_file
    }
  }

  depends_on = [
    aws_iam_role_policy_attachment.vpc,
    aws_cloudwatch_log_group.serve,
  ]
}
