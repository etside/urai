#!/usr/bin/env bash
# ==============================================================================
# launch-training-aws.sh — Launch Urai v1.04 fine-tuning on AWS spot GPU
# Usage: bash scripts/launch-training-aws.sh
# Requires: aws CLI authenticated, ~/.ssh/urai-deploy.pem present
# ==============================================================================

set -e

# --- Configuration -----------------------------------------------------------
REGION="ap-south-1"
AZ="ap-south-1b"
INSTANCE_TYPE="g4dn.xlarge"
MAX_SPOT_PRICE="0.50"
# NOTE: Verify this AMI ID before use.
# Deep Learning AMI GPU PyTorch 2.5, Ubuntu 22.04, ap-south-1.
# Check latest at: https://aws.amazon.com/releasenotes/aws-deep-learning-ami-gpu-pytorch-2-5-ubuntu-22-04/
AMI_ID="ami-0e306788ff2473ccb"
KEY_PAIR="urai-deploy"
SECURITY_GROUP="sg-0026bb40fd666fae5"
SUBNET="subnet-0c91881e2cd9340ac"
S3_BUCKET="urai-data-089737991855-ap-south-1"
S3_PREFIX="urai-v1.04"
PEM_FILE="${HOME}/.ssh/urai-deploy.pem"
REMOTE_USER="ubuntu"
SPOT_REQ_ID=""
INSTANCE_ID=""

# --- Cleanup trap (runs on EXIT) ---------------------------------------------
cleanup() {
    echo ""
    echo "[$(date '+%H:%M:%S')] Running cleanup..."
    if [ -n "${INSTANCE_ID}" ]; then
        echo "[$(date '+%H:%M:%S')] Terminating instance ${INSTANCE_ID}..."
        aws ec2 terminate-instances --instance-ids "${INSTANCE_ID}" \
            --region "${REGION}" > /dev/null 2>&1 || true
    fi
    if [ -n "${SPOT_REQ_ID}" ]; then
        echo "[$(date '+%H:%M:%S')] Cancelling spot request ${SPOT_REQ_ID}..."
        aws ec2 cancel-spot-instance-requests \
            --spot-instance-request-ids "${SPOT_REQ_ID}" \
            --region "${REGION}" > /dev/null 2>&1 || true
    fi
    if [ -n "${LAUNCH_SPEC_FILE}" ] && [ -f "${LAUNCH_SPEC_FILE}" ]; then
        rm -f "${LAUNCH_SPEC_FILE}"
    fi
}
trap cleanup EXIT

# --- Step 1: Check aws CLI ---------------------------------------------------
echo "[$(date '+%H:%M:%S')] Checking AWS CLI authentication..."
aws sts get-caller-identity > /dev/null 2>&1 || {
    echo "ERROR: aws CLI not authenticated. Run: aws configure"
    exit 1
}
echo "[$(date '+%H:%M:%S')] AWS CLI OK."

# --- Step 2: Check PEM file --------------------------------------------------
echo "[$(date '+%H:%M:%S')] Checking PEM file at ${PEM_FILE}..."
if [ ! -f "${PEM_FILE}" ]; then
    echo ""
    echo "ERROR: PEM file not found at ${PEM_FILE}"
    echo ""
    echo "To fix this:"
    echo "  1. Download the 'urai-deploy' key pair from the AWS console:"
    echo "     https://ap-south-1.console.aws.amazon.com/ec2/home?region=ap-south-1#KeyPairs:"
    echo "  2. Save it as ~/.ssh/urai-deploy.pem"
    echo "  3. Run: chmod 600 ~/.ssh/urai-deploy.pem"
    exit 1
fi
chmod 600 "${PEM_FILE}"
echo "[$(date '+%H:%M:%S')] PEM file OK."

# --- Step 3: Sync code and data to S3 ----------------------------------------
echo "[$(date '+%H:%M:%S')] Syncing code to s3://${S3_BUCKET}/${S3_PREFIX}/code/ ..."
aws s3 sync . "s3://${S3_BUCKET}/${S3_PREFIX}/code/" \
    --exclude ".git/*" \
    --exclude "model/base/*.gguf" \
    --exclude "__pycache__/*" \
    --region "${REGION}"
echo "[$(date '+%H:%M:%S')] S3 sync complete."

# --- Step 4: Request spot instance -------------------------------------------
echo "[$(date '+%H:%M:%S')] Writing spot launch spec..."
LAUNCH_SPEC_FILE="$(mktemp /tmp/urai-launch-spec-XXXXXX.json)"

cat > "${LAUNCH_SPEC_FILE}" << EOF
{
  "ImageId": "${AMI_ID}",
  "InstanceType": "${INSTANCE_TYPE}",
  "KeyName": "${KEY_PAIR}",
  "NetworkInterfaces": [
    {
      "DeviceIndex": 0,
      "SubnetId": "${SUBNET}",
      "Groups": ["${SECURITY_GROUP}"],
      "AssociatePublicIpAddress": true
    }
  ],
  "IamInstanceProfile": {},
  "BlockDeviceMappings": [
    {
      "DeviceName": "/dev/sda1",
      "Ebs": {
        "VolumeSize": 50,
        "VolumeType": "gp3",
        "DeleteOnTermination": true
      }
    }
  ]
}
EOF

echo "[$(date '+%H:%M:%S')] Requesting spot instance (${INSTANCE_TYPE}, max \$${MAX_SPOT_PRICE}/hr)..."
SPOT_REQ_ID=$(aws ec2 request-spot-instances \
    --spot-price "${MAX_SPOT_PRICE}" \
    --instance-count 1 \
    --type "one-time" \
    --availability-zone-group "${AZ}" \
    --launch-specification "file://${LAUNCH_SPEC_FILE}" \
    --region "${REGION}" \
    --query "SpotInstanceRequests[0].SpotInstanceRequestId" \
    --output text)

echo "[$(date '+%H:%M:%S')] Spot request ID: ${SPOT_REQ_ID}"

# --- Step 5: Poll spot request until fulfilled --------------------------------
echo "[$(date '+%H:%M:%S')] Waiting for spot request to be fulfilled (max 5 min)..."
POLL=0
MAX_POLLS=20
while [ "${POLL}" -lt "${MAX_POLLS}" ]; do
    STATUS=$(aws ec2 describe-spot-instance-requests \
        --spot-instance-request-ids "${SPOT_REQ_ID}" \
        --region "${REGION}" \
        --query "SpotInstanceRequests[0].Status.Code" \
        --output text 2>/dev/null || echo "pending-evaluation")

    INSTANCE_ID_CHECK=$(aws ec2 describe-spot-instance-requests \
        --spot-instance-request-ids "${SPOT_REQ_ID}" \
        --region "${REGION}" \
        --query "SpotInstanceRequests[0].InstanceId" \
        --output text 2>/dev/null || echo "None")

    echo "[$(date '+%H:%M:%S')] Spot status: ${STATUS} | Instance: ${INSTANCE_ID_CHECK}"

    if [ "${STATUS}" = "fulfilled" ] && [ "${INSTANCE_ID_CHECK}" != "None" ] && [ -n "${INSTANCE_ID_CHECK}" ]; then
        INSTANCE_ID="${INSTANCE_ID_CHECK}"
        echo "[$(date '+%H:%M:%S')] Spot fulfilled! Instance ID: ${INSTANCE_ID}"
        break
    fi

    if echo "${STATUS}" | grep -qE "^(capacity-not-available|price-too-low|instance-terminated-by-user)$"; then
        echo "ERROR: Spot request failed with status: ${STATUS}"
        exit 1
    fi

    POLL=$((POLL + 1))
    sleep 15
done

if [ -z "${INSTANCE_ID}" ]; then
    echo "ERROR: Spot request not fulfilled after $((MAX_POLLS * 15)) seconds."
    exit 1
fi

# Wait for instance to reach running state
echo "[$(date '+%H:%M:%S')] Waiting for instance to reach running state..."
aws ec2 wait instance-running \
    --instance-ids "${INSTANCE_ID}" \
    --region "${REGION}"
echo "[$(date '+%H:%M:%S')] Instance is running."

# Extract public IP
INSTANCE_IP=$(aws ec2 describe-instances \
    --instance-ids "${INSTANCE_ID}" \
    --region "${REGION}" \
    --query "Reservations[0].Instances[0].PublicIpAddress" \
    --output text)

echo "[$(date '+%H:%M:%S')] Instance IP: ${INSTANCE_IP}"

# --- Step 6: SSH and run remote bootstrap ------------------------------------
SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=30 -o BatchMode=yes -i ${PEM_FILE}"

echo "[$(date '+%H:%M:%S')] Waiting for SSH to become available (up to 5 attempts)..."
SSH_ATTEMPT=0
SSH_MAX=5
while [ "${SSH_ATTEMPT}" -lt "${SSH_MAX}" ]; do
    SSH_ATTEMPT=$((SSH_ATTEMPT + 1))
    echo "[$(date '+%H:%M:%S')] SSH attempt ${SSH_ATTEMPT}/${SSH_MAX}..."
    if ssh ${SSH_OPTS} "${REMOTE_USER}@${INSTANCE_IP}" "echo SSH_OK" 2>/dev/null; then
        echo "[$(date '+%H:%M:%S')] SSH connection established."
        break
    fi
    if [ "${SSH_ATTEMPT}" -ge "${SSH_MAX}" ]; then
        echo "ERROR: Could not connect via SSH after ${SSH_MAX} attempts."
        exit 1
    fi
    echo "[$(date '+%H:%M:%S')] SSH not ready yet, retrying in 20s..."
    sleep 20
done

echo "[$(date '+%H:%M:%S')] Running remote bootstrap..."
ssh ${SSH_OPTS} "${REMOTE_USER}@${INSTANCE_IP}" << 'REMOTE_EOF'
set -e
echo "[remote] Installing Python dependencies..."
pip install -q transformers peft accelerate bitsandbytes datasets trl flash-attn --no-build-isolation

echo "[remote] Syncing code from S3..."
aws s3 sync s3://urai-data-089737991855-ap-south-1/urai-v1.04/code/ /home/ubuntu/urai/
cd /home/ubuntu/urai

echo "[remote] Preparing training data..."
python scripts/distill/prepare_data.py \
    --output data/finetune/v1.04/ \
    --tasks vibe-code,llm-tools,agent,memory,mcp

echo "[remote] Starting training..."
python scripts/train_pipeline.py \
    --config configs/distill_qwen3_4b.yaml \
    --output-name urai-v1.04 \
    --use-flash-attn \
    --use-qlora \
    --fp16 \
    --gradient-checkpointing \
    --packing

echo "[remote] Exporting GGUF..."
python scripts/distill/export_gguf.py \
    --input model/base/urai-v1.04.bin \
    --output model/base/urai-v1.04.gguf \
    --quant Q4_K_M

echo "[remote] Uploading GGUF to S3..."
aws s3 cp model/base/urai-v1.04.gguf \
    s3://urai-data-089737991855-ap-south-1/urai-v1.04/output/urai-v1.04.gguf

echo "TRAINING_COMPLETE"
REMOTE_EOF

echo "[$(date '+%H:%M:%S')] Remote training complete."

# --- Step 7: Download result -------------------------------------------------
echo "[$(date '+%H:%M:%S')] Downloading urai-v1.04.gguf from S3..."
mkdir -p model/base
aws s3 cp \
    "s3://${S3_BUCKET}/${S3_PREFIX}/output/urai-v1.04.gguf" \
    "model/base/urai-v1.04.gguf" \
    --region "${REGION}"
echo "[$(date '+%H:%M:%S')] Downloaded to model/base/urai-v1.04.gguf"

# --- Step 8 & 9: Terminate instance and cancel spot --------------------------
echo "[$(date '+%H:%M:%S')] Terminating instance ${INSTANCE_ID}..."
aws ec2 terminate-instances \
    --instance-ids "${INSTANCE_ID}" \
    --region "${REGION}" > /dev/null

echo "[$(date '+%H:%M:%S')] Cancelling spot request ${SPOT_REQ_ID}..."
aws ec2 cancel-spot-instance-requests \
    --spot-instance-request-ids "${SPOT_REQ_ID}" \
    --region "${REGION}" > /dev/null

# Clear IDs so the trap doesn't re-try
INSTANCE_ID=""
SPOT_REQ_ID=""

# --- Step 10: Done -----------------------------------------------------------
echo ""
echo "============================================================"
echo " urai-v1.04.gguf downloaded to model/base/"
echo " Run: bash scripts/setup-ollama.sh"
echo "============================================================"
