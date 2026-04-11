REGISTRY ?= vafi

.PHONY: build build-base build-claude build-mempalace build-agent-mempalace push test helm-template helm-lint help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

# --- Container Images ---

build: ## Build agent image (fast — uses pinned base/claude)
	./scripts/build-images.sh

build-base: ## Rebuild base image layer (Node + system tools)
	./scripts/build-images.sh --base-only

build-claude: ## Rebuild claude image layer (Claude CLI + cxtx)
	./scripts/build-images.sh --claude-only

build-mempalace: ## Build mempalace image layer (Claude + MemPalace)
	docker build --build-arg REGISTRY=$(REGISTRY) \
		-t $(REGISTRY)/vafi-claude-mempalace:latest \
		images/mempalace

build-agent-mempalace: build-mempalace ## Build agent image with mempalace
	docker build --build-arg REGISTRY=$(REGISTRY) \
		--build-arg HARNESS_IMAGE=$(REGISTRY)/vafi-claude-mempalace:latest \
		-t $(REGISTRY)/vafi-agent-mempalace:latest \
		-f images/agent/Dockerfile .

push: ## Push images to registry
	./scripts/push-images.sh

# --- Testing ---

test: ## Run controller unit tests
	python -m pytest tests/ -v

# --- Helm Chart ---

helm-template: ## Render chart with default values
	helm template vafi charts/vafi/

helm-lint: ## Validate chart
	helm lint charts/vafi/
