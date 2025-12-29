#!/bin/bash
# Build Docker images with version info baked in
#
# Usage: ./scripts/build_with_version.sh [image_name] [docker_tag]
#
# Examples:
#   ./scripts/build_with_version.sh collections-api latest
#   ./scripts/build_with_version.sh collections-api prod

set -e

IMAGE_NAME=${1:-"collections-api"}
DOCKER_TAG=${2:-"latest"}

# Capture git info
GIT_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
GIT_TAG=$(git describe --tags --exact-match HEAD 2>/dev/null || echo "")
GIT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
BUILD_TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

echo "Building ${IMAGE_NAME}:${DOCKER_TAG}"
echo "  Git SHA:    ${GIT_SHA}"
echo "  Git Tag:    ${GIT_TAG:-"(none)"}"
echo "  Git Branch: ${GIT_BRANCH}"
echo "  Built at:   ${BUILD_TIMESTAMP}"

docker build \
  --build-arg GIT_SHA="${GIT_SHA}" \
  --build-arg GIT_TAG="${GIT_TAG}" \
  --build-arg GIT_BRANCH="${GIT_BRANCH}" \
  --build-arg BUILD_TIMESTAMP="${BUILD_TIMESTAMP}" \
  -t "${IMAGE_NAME}:${DOCKER_TAG}" \
  -f app/Dockerfile \
  .

echo ""
echo "Successfully built ${IMAGE_NAME}:${DOCKER_TAG}"
echo "Verify with: docker run --rm ${IMAGE_NAME}:${DOCKER_TAG} python -c 'from version import get_version_info; print(get_version_info())'"
