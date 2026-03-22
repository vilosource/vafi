.PHONY: provision k3s os build push deploy seed all help

ANSIBLE_DIR := ansible
INVENTORY := $(ANSIBLE_DIR)/inventory/dev.yml

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

# --- Server Provisioning ---

provision: ## Full server provisioning (OS + k3s)
	cd $(ANSIBLE_DIR) && ansible-playbook playbooks/site.yml -i inventory/dev.yml

k3s: ## k3s install/update only
	cd $(ANSIBLE_DIR) && ansible-playbook playbooks/k3s.yml -i inventory/dev.yml

os: ## OS configuration only
	cd $(ANSIBLE_DIR) && ansible-playbook playbooks/os.yml -i inventory/dev.yml

# --- Container Images ---

build: ## Build all container image layers
	./scripts/build-images.sh

push: ## Import images to k3s host
	./scripts/push-images.sh

# --- Kubernetes ---

deploy: ## Apply k8s manifests to cluster
	./scripts/deploy.sh

seed: ## Seed vtf with admin user and test data
	./scripts/seed-vtf.sh

# --- Combo ---

all: build push deploy seed ## Build, push, deploy, and seed everything
