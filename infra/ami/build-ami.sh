#!/bin/bash
# =============================================================================
# Synapsis Analytics Agent - AMI Builder
# =============================================================================
# Builds a pre-baked AMI with Docker and the Synapsis Agent image cached.
# This eliminates the Docker image pull during instance cold starts.
#
# Prerequisites:
#   - AWS CLI configured with appropriate permissions
#   - ECR repository exists with synapsis-agent:latest pushed
#
# Usage:
#   ./build-ami.sh [--region us-east-1] [--instance-type t3.medium]
# =============================================================================

set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
INSTANCE_TYPE="t3.medium"
ECR_REPO=""
AMI_NAME_PREFIX="synapsis-agent"
SSM_PARAM="/synapsis-agent/ami-id"
BASE_AMI=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --region) REGION="$2"; shift 2 ;;
        --instance-type) INSTANCE_TYPE="$2"; shift 2 ;;
        --ecr-repo) ECR_REPO="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Auto-detect ECR repo if not provided
if [ -z "$ECR_REPO" ]; then
    ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
    ECR_REPO="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/synapsis-agent"
fi

# Find latest Ubuntu 22.04 AMI
echo "[1/7] Finding latest Ubuntu 22.04 AMI..."
BASE_AMI=$(aws ec2 describe-images \
    --region "$REGION" \
    --owners 099720109477 \
    --filters \
        "Name=name,Values=ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*" \
        "Name=state,Values=available" \
    --query 'sort_by(Images, &CreationDate)[-1].ImageId' \
    --output text)
echo "  Base AMI: $BASE_AMI"

# Find default VPC and subnet for the build instance
echo "[2/7] Finding default VPC subnet..."
SUBNET_ID=$(aws ec2 describe-subnets \
    --region "$REGION" \
    --filters "Name=default-for-az,Values=true" \
    --query 'Subnets[0].SubnetId' \
    --output text)
echo "  Subnet: $SUBNET_ID"

# Create a temporary security group
echo "[3/7] Creating temporary security group..."
SG_ID=$(aws ec2 create-security-group \
    --region "$REGION" \
    --group-name "synapsis-ami-builder-$(date +%s)" \
    --description "Temporary SG for AMI build" \
    --query 'GroupId' --output text)
aws ec2 authorize-security-group-ingress \
    --region "$REGION" \
    --group-id "$SG_ID" \
    --protocol tcp --port 22 --cidr 0.0.0.0/0

# Create a temporary IAM instance profile for ECR access
# (Assumes synapsis-agent-ec2-role already exists from CloudFormation)

# Launch build instance
echo "[4/7] Launching build instance ($INSTANCE_TYPE)..."
INSTANCE_ID=$(aws ec2 run-instances \
    --region "$REGION" \
    --image-id "$BASE_AMI" \
    --instance-type "$INSTANCE_TYPE" \
    --subnet-id "$SUBNET_ID" \
    --security-group-ids "$SG_ID" \
    --associate-public-ip-address \
    --iam-instance-profile Name=synapsis-agent-ec2-profile \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=synapsis-ami-builder}]" \
    --user-data "$(cat <<'USERDATA'
#!/bin/bash
set -euo pipefail
exec > /var/log/ami-build.log 2>&1

echo "[$(date)] Starting AMI build..."

# Install Docker
apt-get update
apt-get install -y apt-transport-https ca-certificates curl software-properties-common
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
echo "deb [arch=amd64 signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu jammy stable" > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Enable and start Docker
systemctl enable docker
systemctl start docker

# Install AWS CLI v2 (if not present)
if ! command -v aws &>/dev/null; then
    curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "/tmp/awscliv2.zip"
    unzip -q /tmp/awscliv2.zip -d /tmp
    /tmp/aws/install
fi

# Log in to ECR and pull the synapsis-agent image
REGION=$(curl -s http://169.254.169.254/latest/meta-data/placement/region)
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_REPO="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/synapsis-agent"

aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$ECR_REPO"
docker pull "${ECR_REPO}:latest"

# Pre-pull Traefik image
docker pull traefik:v3.0

# Clean up to reduce AMI size
apt-get clean
rm -rf /var/lib/apt/lists/* /tmp/*
docker system prune -f

# Signal that build is complete
echo "BUILD_COMPLETE" > /tmp/ami-build-status
echo "[$(date)] AMI build complete."
USERDATA
)" \
    --query 'Instances[0].InstanceId' --output text)
echo "  Instance: $INSTANCE_ID"

# Wait for the instance to be running
echo "[5/7] Waiting for instance to be ready and build to complete..."
aws ec2 wait instance-status-ok --region "$REGION" --instance-ids "$INSTANCE_ID"

# Wait for the build to complete (poll via SSM)
echo "  Waiting for Docker image pull to finish..."
for i in $(seq 1 60); do
    STATUS=$(aws ssm send-command \
        --region "$REGION" \
        --instance-ids "$INSTANCE_ID" \
        --document-name "AWS-RunShellScript" \
        --parameters "commands=[\"cat /tmp/ami-build-status 2>/dev/null || echo BUILDING\"]" \
        --query 'Command.CommandId' --output text)
    sleep 5
    RESULT=$(aws ssm get-command-invocation \
        --region "$REGION" \
        --command-id "$STATUS" \
        --instance-id "$INSTANCE_ID" \
        --query 'StandardOutputContent' --output text 2>/dev/null || echo "BUILDING")
    if echo "$RESULT" | grep -q "BUILD_COMPLETE"; then
        echo "  Build complete!"
        break
    fi
    echo "  Still building... (attempt $i/60)"
    sleep 25
done

# Create AMI
echo "[6/7] Creating AMI..."
AMI_NAME="${AMI_NAME_PREFIX}-$(date +%Y%m%d-%H%M%S)"
NEW_AMI_ID=$(aws ec2 create-image \
    --region "$REGION" \
    --instance-id "$INSTANCE_ID" \
    --name "$AMI_NAME" \
    --description "Synapsis Agent pre-baked AMI with Docker and agent image" \
    --no-reboot \
    --query 'ImageId' --output text)
echo "  AMI: $NEW_AMI_ID ($AMI_NAME)"

# Wait for AMI to be available
echo "  Waiting for AMI to be available..."
aws ec2 wait image-available --region "$REGION" --image-ids "$NEW_AMI_ID"

# Update SSM Parameter with new AMI ID
aws ssm put-parameter \
    --region "$REGION" \
    --name "$SSM_PARAM" \
    --value "$NEW_AMI_ID" \
    --type String \
    --overwrite
echo "  SSM Parameter $SSM_PARAM updated to $NEW_AMI_ID"

# Cleanup: terminate build instance and delete temp security group
echo "[7/7] Cleaning up..."
aws ec2 terminate-instances --region "$REGION" --instance-ids "$INSTANCE_ID"
aws ec2 wait instance-terminated --region "$REGION" --instance-ids "$INSTANCE_ID"
aws ec2 delete-security-group --region "$REGION" --group-id "$SG_ID"

echo ""
echo "=== AMI Build Complete ==="
echo "AMI ID: $NEW_AMI_ID"
echo "AMI Name: $AMI_NAME"
echo "SSM Parameter: $SSM_PARAM"
echo ""
echo "To update the CloudFormation stack with this AMI:"
echo "  aws cloudformation deploy --template-file infra/template.yaml --stack-name synapsis-agent-prod --capabilities CAPABILITY_IAM"
