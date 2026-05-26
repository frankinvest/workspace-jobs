#!/usr/bin/env bash
# deploy-cos.sh — 将 dist/ 目录同步到腾讯云 COS
# 用法: ./scripts/deploy-cos.sh
#
# 环境变量（必须在运行前设置）:
#   COS_SECRET_ID   - 腾讯云 SecretId
#   COS_SECRET_KEY  - 腾讯云 SecretKey
#   COS_BUCKET     - 存储桶名称，如 "my-bucket-1300000000"
#   COS_REGION     - 区域，如 "ap-beijing"
#   COS_PREFIX     - 可选，CDN 加速的子目录前缀，如 "workspace-jobs/"

set -e

# ── 检查依赖 ──────────────────────────────────────────────
if ! command -v coscmd &> /dev/null; then
  echo "[COS] 错误: coscmd 未安装"
  echo "[COS] 安装: pip install cos-python-sdk-v5"
  exit 1
fi

# ── 检查环境变量 ──────────────────────────────────────────
if [[ -z "$COS_SECRET_ID" || -z "$COS_SECRET_KEY" || -z "$COS_BUCKET" || -z "$COS_REGION" ]]; then
  echo "[COS] 错误: 缺少必需环境变量"
  echo "[COS] 必须设置: COS_SECRET_ID, COS_SECRET_KEY, COS_BUCKET, COS_REGION"
  exit 1
fi

# ── 配置 coscmd ────────────────────────────────────────────
cos_config="/tmp/.cos.conf"
cat > "$cos_config" << EOF
[DEFAULT]
secret_id = ${COS_SECRET_ID}
secret_key = ${COS_SECRET_KEY}
bucket = ${COS_BUCKET}
region = ${COS_REGION}
EOF

export COSCONF_PATH="$cos_config"

# ── 同步 dist/ 到 COS ─────────────────────────────────────
DIST_DIR="${DIST_DIR:-dist}"
PREFIX="${COS_PREFIX:-}"

echo "[COS] 开始同步 ${DIST_DIR}/ 到 COS bucket=${COS_BUCKET} region=${COS_REGION}"

coscmd -c "$cos_config" upload -r "$DIST_DIR/" "/${PREFIX}" --force

echo "[COS] 同步完成!"
echo "[COS] 访问地址: https://${COS_BUCKET}.cos.${COS_REGION}.myqcloud.com/${PREFIX}"
