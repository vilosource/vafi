.PHONY: build build-base build-claude push test helm-template helm-lint help

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
