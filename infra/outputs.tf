###############################################################################
# Outputs. Every one of these refers to a resource defined in main.tf.
#
# That sentence is the whole point of this file. The starting MVP exported
# `aws_s3_bucket.files_bucket` and `aws_db_instance.postgres_rds`, neither of
# which existed anywhere in its configuration -- so the module could not even
# reach `plan`. It failed at the first layer, before anything interesting.
#
# Both were dropped rather than defined. Standing up RDS to satisfy an output
# would burn credits on this account for no argument gained, and the account
# has an expiry date (IA-25). A file, a print server and a database still
# appear in the planner's inventory, where they cost nothing and prove the
# same point.
###############################################################################

output "vpc_id" {
  description = "Id of the target VPC."
  value       = aws_vpc.target.id
}

output "public_subnet_id" {
  description = "Id of the public subnet. Associated to its route table, which is what makes it public in fact and not just in name."
  value       = aws_subnet.public.id
}

output "route_table_id" {
  description = "Id of the public route table."
  value       = aws_route_table.public.id
}

output "security_group_id" {
  description = "Id of the target Security Group."
  value       = aws_security_group.target.id
}

output "instance_id" {
  description = "Id of the demonstrative target instance."
  value       = aws_instance.target.id
}

output "instance_public_ip" {
  description = "Public IP of the target."
  value       = aws_instance.target.public_ip
}

output "ami_id" {
  description = "AMI resolved at plan time. Printed so the plan records which image it was going to use."
  value       = data.aws_ami.al2023.id
}
