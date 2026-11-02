variable "region" {
  type    = string
  default = "us-east-1"
}

variable "project" {
  type    = string
  default = "streaming"
}

variable "github_repository" {
  type        = string
  description = "owner/name of the GitHub repository allowed to build, e.g. acme/streaming"
}
