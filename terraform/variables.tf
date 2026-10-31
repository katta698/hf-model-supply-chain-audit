variable "region" {
  description = "AWS region. Gateway endpoints are regional."
  type        = string
  default     = "us-east-1"
}

variable "bucket_name" {
  description = "Existing mirror bucket, created by scripts/mirror_model.py"
  type        = string
}

variable "model_repo" {
  description = "Mirrored model the prover Lambda should read"
  type        = string
  default     = "sentence-transformers/all-MiniLM-L6-v2"
}

variable "vpc_cidr" {
  type    = string
  default = "10.80.0.0/16"
}

variable "subnet_cidr" {
  type    = string
  default = "10.80.1.0/24"
}

variable "model_file" {
  description = "Exact weight file to serve, as mirrored"
  type        = string
  default     = "onnx/model_quint8_avx2.onnx"
}
