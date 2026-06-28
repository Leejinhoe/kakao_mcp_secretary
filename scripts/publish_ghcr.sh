#!/usr/bin/env bash
set -euo pipefail

REGISTRY="${REGISTRY:-ghcr.io}"
GHCR_NAMESPACE="${GHCR_NAMESPACE:-leejinhoe}"
GITHUB_USERNAME="${GITHUB_USERNAME:-$GHCR_NAMESPACE}"
IMAGE_NAME="${IMAGE_NAME:-mcp-secretary}"
IMAGE_TAG="${IMAGE_TAG:-v1.0.4}"
TARGET_PLATFORM="${TARGET_PLATFORM:-linux/amd64}"
BUILDER="${BUILDER:-colima}"
LOCAL_IMAGE="${LOCAL_IMAGE:-$IMAGE_NAME:$IMAGE_TAG}"
REMOTE_IMAGE="$REGISTRY/$GHCR_NAMESPACE/$IMAGE_NAME:$IMAGE_TAG"
SOURCE_REPO="${SOURCE_REPO:-https://github.com/Leejinhoe/kakao_mcp_secretary}"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker 명령을 찾을 수 없습니다. Docker Desktop을 설치하고 실행한 뒤 다시 시도하세요." >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker daemon에 연결할 수 없습니다. Docker Desktop이 실행 중인지 확인하세요." >&2
  exit 1
fi

if [[ ! -f "secrets.local.json" ]]; then
  echo "secrets.local.json 파일이 없습니다. API 키를 담은 로컬 비밀 파일을 먼저 만들어야 합니다." >&2
  exit 1
fi

if docker buildx version >/dev/null 2>&1; then
  echo "Building $LOCAL_IMAGE for $TARGET_PLATFORM with buildx builder '$BUILDER' ..."
  docker buildx build \
    --builder "$BUILDER" \
    --platform "$TARGET_PLATFORM" \
    --load \
    --label "org.opencontainers.image.source=$SOURCE_REPO" \
    --label "org.opencontainers.image.description=DailyRoute Guard MCP server" \
    -t "$LOCAL_IMAGE" \
    .
else
  echo "Building $LOCAL_IMAGE for $TARGET_PLATFORM ..."
  docker build \
    --platform "$TARGET_PLATFORM" \
    --label "org.opencontainers.image.source=$SOURCE_REPO" \
    --label "org.opencontainers.image.description=DailyRoute Guard MCP server" \
    -t "$LOCAL_IMAGE" \
    .
fi

echo "Tagging $REMOTE_IMAGE ..."
docker tag "$LOCAL_IMAGE" "$REMOTE_IMAGE"

if [[ -z "${GHCR_PAT:-}" ]]; then
  read -r -s -p "GitHub PAT(classic, write:packages/read:packages): " GHCR_PAT
  echo
fi

echo "Logging in to $REGISTRY as $GITHUB_USERNAME ..."
printf '%s' "$GHCR_PAT" | docker login "$REGISTRY" -u "$GITHUB_USERNAME" --password-stdin

echo "Pushing $REMOTE_IMAGE ..."
docker push "$REMOTE_IMAGE"

cat <<EOF

Pushed: $REMOTE_IMAGE
Platform: $TARGET_PLATFORM

GitHub Container Registry는 첫 publish 시 기본 visibility가 private입니다.
GitHub Packages 화면에서 이 패키지를 Public으로 바꾸지 마세요.
PlayMCP 이미지 등록에는 아래 값을 넣으면 됩니다.

Registry 호스트: $REGISTRY
Registry 사용자: $GITHUB_USERNAME
Registry 비밀번호: GitHub PAT(classic, read:packages 권한 포함)
image_name: $GHCR_NAMESPACE/$IMAGE_NAME
image_tag: $IMAGE_TAG
EOF
