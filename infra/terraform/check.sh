#!/bin/sh
# Format check + validate every Terraform root and module, without touching AWS (no backend, no credentials).
# Usage (from infra/terraform):  sh check.sh        Used by CI and locally via the hashicorp/terraform image.
set -eu
status=0
terraform fmt -check -recursive -diff || status=1
for dir in bootstrap app modules/media modules/platform; do
  echo "== $dir"
  (
    cd "$dir"
    terraform init -backend=false -input=false >/dev/null
    terraform validate -no-color
    rm -rf .terraform .terraform.lock.hcl
  ) || status=1
done
exit "$status"
