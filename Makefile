# Collections-Local AWS Deployment Automation
# Provides simple commands for AWS infrastructure management
#
# Usage: make <target> ENV=<dev|test|prod>
# Example: make infra-deploy ENV=dev

# Default environment (can be overridden)
ENV ?= dev

# Color output
BLUE := \033[0;34m
GREEN := \033[0;32m
YELLOW := \033[0;33m
RED := \033[0;31m
NC := \033[0m # No Color

# Paths
SCRIPTS_DIR := ./scripts/aws
INFRA_DIR := ./infrastructure

.PHONY: help
help: ## Show this help message
	@echo "$(BLUE)Collections-Local AWS Deployment Commands$(NC)"
	@echo ""
	@echo "$(GREEN)Infrastructure Commands:$(NC)"
	@echo "  make infra-bootstrap ENV=dev    - Bootstrap CDK for environment"
	@echo "  make infra-deploy ENV=dev       - Deploy CDK stack to environment"
	@echo "  make infra-diff ENV=dev         - Show infrastructure changes"
	@echo "  make infra-destroy ENV=dev      - Destroy stack (with confirmation)"
	@echo "  make infra-status ENV=dev       - Show stack status"
	@echo "  make infra-outputs ENV=dev      - Extract CDK outputs to JSON"
	@echo ""
	@echo "$(GREEN)Testing Commands:$(NC)"
	@echo "  make test-infra ENV=dev         - Run infrastructure validation tests"
	@echo "  make test-all ENV=dev           - Run all tests (infra + API + e2e)"
	@echo ""
	@echo "$(GREEN)Database Commands:$(NC)"
	@echo "  make db-connect ENV=dev         - Open psql connection to RDS"
	@echo "  make db-migrate ENV=dev         - Run schema migrations (future)"
	@echo "  make db-seed-golden ENV=dev     - Seed golden dataset (future)"
	@echo ""
	@echo "$(GREEN)Secrets Commands:$(NC)"
	@echo "  make secrets-populate ENV=dev   - Push secrets from .env to Parameter Store"
	@echo "  make secrets-export ENV=dev     - Pull secrets from Parameter Store to .env"
	@echo ""
	@echo "$(GREEN)Lambda Commands:$(NC)"
	@echo "  make lambda-deploy-api ENV=dev  - Deploy API Lambda only (fast)"
	@echo "  make lambda-logs FUNC=api ENV=dev - Tail CloudWatch logs"
	@echo ""
	@echo "$(GREEN)Utility Commands:$(NC)"
	@echo "  make check-deps                 - Check required dependencies"
	@echo "  make clean                      - Clean temporary files"
	@echo ""
	@echo "$(YELLOW)Default environment: $(ENV)$(NC)"
	@echo "Override with: make <target> ENV=<dev|test|prod>"

###########################################
# Infrastructure Commands
###########################################

.PHONY: infra-bootstrap
infra-bootstrap: check-deps ## Bootstrap CDK for environment
	@echo "$(BLUE)Bootstrapping CDK for $(ENV) environment...$(NC)"
	@bash $(SCRIPTS_DIR)/bootstrap.sh $(ENV)

.PHONY: infra-deploy
infra-deploy: check-deps ## Deploy CDK stack to environment
	@echo "$(BLUE)Deploying to $(ENV) environment...$(NC)"
	@bash $(SCRIPTS_DIR)/deploy.sh $(ENV)

.PHONY: infra-diff
infra-diff: check-deps ## Show infrastructure changes
	@echo "$(BLUE)Showing infrastructure diff for $(ENV)...$(NC)"
	@cd $(INFRA_DIR) && cdk diff --context env=$(ENV) '*'

.PHONY: infra-destroy
infra-destroy: check-deps ## Destroy stack (with confirmation)
	@echo "$(RED)Destroying infrastructure in $(ENV) environment...$(NC)"
	@bash $(SCRIPTS_DIR)/destroy.sh $(ENV)

.PHONY: infra-status
infra-status: check-deps ## Show stack status
	@bash $(SCRIPTS_DIR)/status.sh $(ENV)

.PHONY: infra-outputs
infra-outputs: check-deps ## Extract CDK outputs to JSON
	@bash $(SCRIPTS_DIR)/outputs.sh $(ENV)

###########################################
# Testing Commands
###########################################

.PHONY: test-infra
test-infra: check-deps ## Run infrastructure validation tests
	@echo "$(BLUE)Running infrastructure tests for $(ENV)...$(NC)"
	@cd scripts/aws/test && CDK_ENV=$(ENV) pytest test_infrastructure.py -v

.PHONY: test-all
test-all: check-deps ## Run all tests (infra + API + e2e)
	@echo "$(BLUE)Running all tests for $(ENV)...$(NC)"
	@cd scripts/aws/test && CDK_ENV=$(ENV) pytest -v

###########################################
# Database Commands
###########################################

.PHONY: db-connect
db-connect: check-deps ## Open psql connection to RDS
	@echo "$(BLUE)Connecting to RDS database in $(ENV)...$(NC)"
	@bash $(SCRIPTS_DIR)/db-connect.sh $(ENV)

.PHONY: db-migrate
db-migrate: check-deps ## Run schema migrations (future)
	@echo "$(YELLOW)Database migrations not yet implemented$(NC)"
	@echo "Future: Run Alembic migrations against RDS"

.PHONY: db-seed-golden
db-seed-golden: check-deps ## Seed golden dataset (future)
	@echo "$(YELLOW)Golden dataset seeding not yet implemented$(NC)"
	@echo "Future: Upload golden images to S3 and trigger processing"

###########################################
# Secrets Commands
###########################################

.PHONY: secrets-populate
secrets-populate: check-deps ## Push secrets from .env to Parameter Store
	@echo "$(BLUE)Populating Parameter Store from .env.$(ENV)...$(NC)"
	@bash $(SCRIPTS_DIR)/secrets/populate.sh $(ENV)

.PHONY: secrets-export
secrets-export: check-deps ## Pull secrets from Parameter Store to .env
	@echo "$(YELLOW)Secrets export not yet implemented$(NC)"
	@echo "Future: Download secrets from Parameter Store to local .env file"

###########################################
# Lambda Commands
###########################################

.PHONY: lambda-deploy-api
lambda-deploy-api: check-deps ## Deploy API Lambda only (fast)
	@echo "$(BLUE)Deploying API Lambda for $(ENV)...$(NC)"
	@cd $(INFRA_DIR) && cdk deploy --context env=$(ENV) CollectionsApiStack-$(ENV) --require-approval never

.PHONY: lambda-logs
lambda-logs: check-deps ## Tail CloudWatch logs
ifndef FUNC
	@echo "$(RED)Error: FUNC parameter required$(NC)"
	@echo "Usage: make lambda-logs FUNC=api ENV=dev"
	@exit 1
endif
	@bash $(SCRIPTS_DIR)/lambda-logs.sh $(FUNC) $(ENV)

###########################################
# Utility Commands
###########################################

.PHONY: check-deps
check-deps: ## Check required dependencies
	@command -v aws >/dev/null 2>&1 || { echo "$(RED)Error: aws CLI not found. Install it from https://aws.amazon.com/cli/$(NC)"; exit 1; }
	@command -v jq >/dev/null 2>&1 || { echo "$(RED)Error: jq not found. Install it with: sudo apt-get install jq$(NC)"; exit 1; }
	@command -v cdk >/dev/null 2>&1 || { echo "$(RED)Error: AWS CDK CLI not found. Install it with: npm install -g aws-cdk$(NC)"; exit 1; }
	@aws sts get-caller-identity >/dev/null 2>&1 || { echo "$(RED)Error: AWS credentials not configured. Run: aws configure$(NC)"; exit 1; }

.PHONY: clean
clean: ## Clean temporary files
	@echo "$(BLUE)Cleaning temporary files...$(NC)"
	@rm -f .aws-outputs-*.json
	@rm -rf $(INFRA_DIR)/cdk.out
	@rm -rf ./claude-temp/*
	@echo "$(GREEN)Clean complete$(NC)"

###########################################
# Development Shortcuts
###########################################

.PHONY: dev-setup
dev-setup: check-deps ## Quick setup for dev environment
	@echo "$(BLUE)Setting up dev environment...$(NC)"
	@make infra-bootstrap ENV=dev
	@make secrets-populate ENV=dev
	@make infra-deploy ENV=dev
	@make infra-outputs ENV=dev
	@echo "$(GREEN)Dev environment ready!$(NC)"

.PHONY: dev-reset
dev-reset: ## Reset dev environment (destroy + redeploy)
	@echo "$(YELLOW)Resetting dev environment...$(NC)"
	@make infra-destroy ENV=dev
	@make infra-deploy ENV=dev
	@make infra-outputs ENV=dev
	@echo "$(GREEN)Dev environment reset complete$(NC)"
