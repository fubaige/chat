# -*- coding: utf-8 -*-
# 一键提交并部署脚本 (Windows PowerShell)
# 自动提交当前变更 -> 推送到 GitHub -> 打包上传 -> 服务器部署

param(
    [string]$Message = "chore: quick deploy update"
)

$SERVER_IP = "103.36.221.102"
$SERVER_PORT = 59582
$SERVER_USER = "root"
$DEPLOY_PATH = "/www/wwwroot/chat.aigcqun.cn"
$SSH_KEY = ".ssh_deploy_key"

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  Quick Deploy Script" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# 1. Check for changes
Write-Host "[1/6] Checking code changes..." -ForegroundColor Yellow
$status = git status --porcelain
if (-not $status) {
    Write-Host "No changes to commit" -ForegroundColor Yellow
    $continue = Read-Host "Continue deploying latest code? (y/n)"
    if ($continue -ne "y") {
        Write-Host "Cancelled" -ForegroundColor Red
        exit 0
    }
} else {
    Write-Host "Changes detected:" -ForegroundColor Green
    git status --short
    Write-Host ""
}

# 2. Commit changes
if ($status) {
    Write-Host "[2/6] Committing changes..." -ForegroundColor Yellow
    git add -A
    git commit -m $Message
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Commit failed!" -ForegroundColor Red
        exit 1
    }
    Write-Host "OK Committed: $Message" -ForegroundColor Green
    Write-Host ""
} else {
    Write-Host "[2/6] Skipping commit (no changes)" -ForegroundColor DarkGray
    Write-Host ""
}

# 3. Push to GitHub
Write-Host "[3/6] Pushing to GitHub..." -ForegroundColor Yellow
git push origin main
if ($LASTEXITCODE -ne 0) {
    Write-Host "Push failed!" -ForegroundColor Red
    exit 1
}
Write-Host "OK Pushed successfully" -ForegroundColor Green
Write-Host ""

# 4. Clean up server disk space before deploy
Write-Host "[4/6] Cleaning up server disk space (Preserving build cache)..." -ForegroundColor Yellow
# Write-Host "  - Docker dangling images prune (Skipped to preserve cache)" -ForegroundColor DarkGray
$sshCleanup = @"
# docker image prune -f 2>/dev/null || true
apt-get clean 2>/dev/null || true
"@
ssh -i $SSH_KEY -p $SERVER_PORT -o StrictHostKeyChecking=no -o ServerAliveInterval=10 -o ServerAliveCountMax=6 "${SERVER_USER}@${SERVER_IP}" $sshCleanup
Write-Host "OK Server disk cleaned" -ForegroundColor Green
Write-Host ""

# 5. Package and upload to server
Write-Host "[5/6] Packaging and uploading..." -ForegroundColor Yellow
$archiveFile = "deploy-archive.tar.gz"

# Package (exclude .git and node_modules for faster deployment)
git archive --format=tar.gz -o $archiveFile HEAD
if ($LASTEXITCODE -ne 0) {
    Write-Host "Packaging failed!" -ForegroundColor Red
    exit 1
}
$archiveSize = [math]::Round((Get-Item $archiveFile).Length / 1MB, 2)
Write-Host "  Packaged: ${archiveSize}MB" -ForegroundColor DarkGray

# Upload
scp -i $SSH_KEY -P $SERVER_PORT -o StrictHostKeyChecking=no $archiveFile "${SERVER_USER}@${SERVER_IP}:${DEPLOY_PATH}/"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Upload failed!" -ForegroundColor Red
    Remove-Item $archiveFile -ErrorAction SilentlyContinue
    exit 1
}

# Cleanup local archive
Remove-Item $archiveFile -ErrorAction SilentlyContinue
Write-Host "OK Code uploaded to server" -ForegroundColor Green
Write-Host ""

# 6. Deploy on server (extract and run directly without git)
Write-Host "[6/6] Deploying on server..." -ForegroundColor Yellow
Write-Host "(Press Ctrl+C to exit log view, deployment continues)" -ForegroundColor DarkGray
Write-Host ""

# Deploy command: extract, fix line endings, and run docker-compose
$remoteCmd = "cd $DEPLOY_PATH && tar -xzf deploy-archive.tar.gz 2>/dev/null && rm -f deploy-archive.tar.gz && export DOCKER_BUILDKIT=1 && export COMPOSE_DOCKER_CLI_BUILD=1 && docker-compose up -d --build"
ssh -i $SSH_KEY -p $SERVER_PORT -o StrictHostKeyChecking=no -o ServerAliveInterval=10 -o ServerAliveCountMax=6 "${SERVER_USER}@${SERVER_IP}" $remoteCmd

Write-Host ""
Write-Host "==========================================" -ForegroundColor Green
Write-Host "  Deployment Complete!" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
Write-Host ""
Write-Host "URL: https://chat.aigcqun.cn" -ForegroundColor Cyan
Write-Host ""
Write-Host "Common commands:" -ForegroundColor Yellow
Write-Host "  View logs: docker-compose logs -f" -ForegroundColor DarkGray
Write-Host "  Check status: docker-compose ps" -ForegroundColor DarkGray
Write-Host "  Restart: docker-compose --profile all restart" -ForegroundColor DarkGray
