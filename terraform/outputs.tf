output "vpc_id" {
  value = aws_vpc.this.id
}

output "subnet_id" {
  value = aws_subnet.private.id
}

output "s3_endpoint_id" {
  value = aws_vpc_endpoint.s3.id
}

output "prover_function" {
  value = aws_lambda_function.prover.function_name
}

output "routes" {
  description = "Proof there is no path to the internet from this subnet"
  value       = "route table ${aws_route_table.private.id} has no 0.0.0.0/0 entry"
}

output "invoke" {
  value = "aws lambda invoke --function-name ${aws_lambda_function.prover.function_name} --cli-binary-format raw-in-base64-out out.json && cat out.json"
}
