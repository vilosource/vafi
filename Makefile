.PHONY: build build-base build-claude push test helm-template helm-lint \
        setup-dev build-dev-images install-dev help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# --- Developer environment ---

setup-dev: ## Install developer launchers into ~/.claude and wire ~/.bashrc
	./scripts/setup-developer-env.sh

build-dev-images: ## Build vafi-developer image family (base + claude + pi + gemini)
	./scripts/build-developer-images.sh

install-dev: setup-dev build-dev-images ## Full developer setup: launchers + images (new machine)

# --- Fleet container images ---

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
