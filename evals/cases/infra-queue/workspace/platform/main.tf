# Shared platform for the exports service.
resource "aws_ecs_service" "exports_api" {
  name          = "exports-api"
  desired_count = 2
}

resource "aws_s3_bucket" "exports" {
  bucket = "acme-exports"
}
