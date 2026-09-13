#!/usr/bin/env bash
set -euo pipefail
host=${1:-root@10.10.11.8}
source_dir=$(cd "$(dirname "$0")" && pwd)
deploy_id=$(python3 -c 'import uuid; print(uuid.uuid4().hex)')
# Stage outside custom_nodes: other ComfyUI processes must not discover it.
ssh "$host" bash -s -- "$deploy_id" <<'REMOTE'
set -euo pipefail
id=$1
curl -fsS http://127.0.0.1:8188/queue | python3 -c 'import sys,json; q=json.load(sys.stdin); assert not q["queue_running"] and not q["queue_pending"], "GPU3 has queued work; deployment deferred"'
command -v blender
command -v ffmpeg
command -v ffprobe
python3 -c 'import numpy'
backup=/var/backups/comfyui-game-assets-$id
mkdir -p "$backup" "/opt/ComfyUI/.game-assets-stage-$id"
if [ -d /opt/ComfyUI/custom_nodes/ComfyUI_GameAssets ]; then
    cp -a /opt/ComfyUI/custom_nodes/ComfyUI_GameAssets "$backup/plugin"
fi
systemctl cat comfyui-gpu3.service > "$backup/service.txt"
REMOTE
tar -C "$source_dir" --exclude='__pycache__' --exclude='*.pyc' -cf - . | ssh "$host" "tar -C /opt/ComfyUI/.game-assets-stage-$deploy_id -xf -"
ssh "$host" bash -s -- "$deploy_id" <<'REMOTE'
set -euo pipefail
id=$1
exec 9>/run/lock/comfyui-game-assets-deploy.lock
flock -n 9 || { echo 'Another game-assets deployment is active' >&2; exit 1; }
live=/opt/ComfyUI/custom_nodes/ComfyUI_GameAssets
stage=/opt/ComfyUI/.game-assets-stage-$id
previous=/opt/ComfyUI/.game-assets-previous-$id
backup=/var/backups/comfyui-game-assets-$id
dropin=/etc/systemd/system/comfyui-gpu3.service.d/game-assets.conf
workflow=/var/lib/comfyui/gpu3/user/default/workflows/GameAssets/image_to_game_asset.json
stopped=0
installed=0
had_plugin=0
had_dropin=0
had_workflow=0
[ ! -e "$dropin" ] || { cp -a "$dropin" "$backup/game-assets.conf"; had_dropin=1; }
[ ! -e "$workflow" ] || { cp -a "$workflow" "$backup/workflow.json"; had_workflow=1; }
rollback() {
    code=$?
    trap - EXIT INT TERM
    if [ "$code" -ne 0 ] && [ "$stopped" -eq 1 ]; then
        set +e
        systemctl stop comfyui-gpu3.service
        if [ "$installed" -eq 1 ]; then mv "$live" "$stage.failed"; fi
        if [ "$had_plugin" -eq 1 ]; then mv "$previous" "$live"; fi
        if [ "$had_dropin" -eq 1 ]; then cp -a "$backup/game-assets.conf" "$dropin"; else rm -f "$dropin"; fi
        if [ "$had_workflow" -eq 1 ]; then cp -a "$backup/workflow.json" "$workflow"; else rm -f "$workflow"; fi
        systemctl daemon-reload
        systemctl start comfyui-gpu3.service
        echo "Deployment failed; attempted GPU3 rollback. Backup: $backup" >&2
    fi
    exit "$code"
}
trap rollback EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
curl -fsS http://127.0.0.1:8188/queue | python3 -c 'import sys,json; q=json.load(sys.stdin); assert not q["queue_running"] and not q["queue_pending"], "GPU3 has queued work; deployment deferred"'
# Prevent new submissions during the directory switch.
stopped=1
systemctl stop comfyui-gpu3.service
if [ -e "$live" ]; then mv "$live" "$previous"; had_plugin=1; fi
mv "$stage" "$live"
installed=1
mkdir -p "$(dirname "$dropin")" "$(dirname "$workflow")"
printf '[Service]\nEnvironment=GAME_ASSETS_ENABLED=1\n' > "$dropin"
cp "$live/workflows/image_to_game_asset.json" "$workflow"
chown -R comfyui:comfyui "$(dirname "$workflow")"
systemctl daemon-reload
systemctl start comfyui-gpu3.service
ready=0
for attempt in {1..30}; do
    if curl -fsS http://127.0.0.1:8188/object_info/GameAssetBlenderOptimize | python3 -c 'import json,sys; assert "GameAssetBlenderOptimize" in json.load(sys.stdin)' 2>/dev/null; then ready=1; break; fi
    sleep 2
done
[ "$ready" -eq 1 ] || { echo 'GPU3 plugin did not become ready' >&2; exit 1; }
trap - EXIT INT TERM
printf 'Backup: %s\nPrevious plugin: %s\n' "$backup" "$previous"
REMOTE
