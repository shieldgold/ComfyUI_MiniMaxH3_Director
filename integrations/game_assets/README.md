# 图片 → 游戏资产候选包（GPU3）

独立 ComfyUI 插件，把现有 Pixal3D 图生 3D 接到服务器 Blender 后处理。当前针对静态道具；输出是需要美术检查的资产候选，不自动承诺角色布线、绑定或目标引擎中的水晶效果。

## 已提供的入口

- ComfyUI：`http://10.10.11.8:8188/`，工作流列表 `GameAssets/image_to_game_asset.json`。
- API：沿用 ComfyUI `/upload/image`、`/prompt`、`/history/<prompt_id>`、`/view`。
- 节点：`Game Asset · Blender Optimize`。前接 `MeshToFile3D`，后接 3D 预览。

界面打开上述工作流，更换 Load Image 的图片，点击运行。模型生成之后自动执行 Blender；节点展示六视图，并提供下载 ZIP、打开检查报告和播放旋转预览三个按钮，右侧预览优化后的 GLB。只有更改输入/参数才会重新执行，重复同一工作流可能命中 ComfyUI 缓存。

命令行（Python 3.10+，仅标准库）：

```bash
python3 integrations/game_assets/client.py \
  --server http://10.10.11.8:8188 \
  --image /absolute/path/product.png \
  --target-faces 20000 --texture-size 1024 \
  --state /absolute/path/job-state.json \
  --output /absolute/path/asset.zip
```

客户端先记录提交意图，再提交一次，保存 `prompt_id`；中断后续查，不重复生成：

```bash
python3 integrations/game_assets/client.py \
  --resume --state /absolute/path/job-state.json \
  --output /absolute/path/asset.zip
```

若提交响应丢失，客户端通过 `operation_key` 在队列和最近 1000 条历史中恢复；找不到唯一任务时保留未知状态，不自动重发。下载经过 ZIP CRC 和文件清单检查，确认有效后原子替换目标文件。服务器只提供已有局域网 ComfyUI 接口，不新增公网监听。

## 产物

每次后处理在 `output/game-assets/<job_id>/` 下创建独立目录：

| 文件 | 用途 |
|---|---|
| `model.glb` | LOD0，内嵌材质纹理 |
| `lod1.glb`、`lod2.glb` | 较低三角形数量的模型 |
| `model.blend` | 原始高模、优化模型、LOD、灯光、相机和打包纹理，可继续编辑 |
| `textures/*.png` | 基础色、粗糙度、金属度、切线法线 |
| `collision.glb` | 包围盒碰撞体，需要按玩法调整 |
| `views/*.png` | 前后左右上下六视图 |
| `turntable.mp4`、`turntable/*.png` | 旋转预览视频和 12 帧源图 |
| `report.json` | 实际面数、尺寸、几何检查和限制 |
| `manifest.json`、`asset.zip` | 产物清单和下载包 |
| `status.json`、`blender.log` | 服务器运行状态和排错日志，不打进交付包 |

Blender 重建连续表面，再减面、展开 UV、从高模烘焙材质，生成 LOD 和预览。保留输入空间尺寸；未推断真实厘米/米。细薄结构可能受体素重建影响，应通过六视图对照参考。

## 运行环境与维护

Ubuntu 24.04，Blender 4.0.2，`python3-numpy` 和 `ffmpeg`，ComfyUI 含 `FILE_3D_GLB`/`Types.File3D` 支持。

```bash
sudo apt-get install --no-install-recommends blender python3-numpy ffmpeg
bash integrations/game_assets/deploy_gpu3.sh root@10.10.11.8
```

部署脚本将本目录复制为 `/opt/ComfyUI/custom_nodes/ComfyUI_GameAssets`，仅 GPU3 增加 `GAME_ASSETS_ENABLED=1`，检查队列空闲后重启 `comfyui-gpu3.service`。其它 GPU 不注册该节点，不重启。安装软件与首次模型权重准备需要管理员单独完成。

Blender 用 CPU、8 个线程；同一输出根目录通过文件锁串行，任务上限 1800 秒。ComfyUI 取消会终止 Blender 进程组。中途失败留下状态和日志，缺少/损坏产物不会报告完成。

回滚：GPU3 队列空闲后移除 `/etc/systemd/system/comfyui-gpu3.service.d/game-assets.conf`，执行 `systemctl daemon-reload`、`systemctl restart comfyui-gpu3.service`。原 Pixal3D 工作流和产物不依赖本插件，无需删除。已有同名 drop-in 的备份位于 `/var/backups/comfyui-game-assets-<deployment_id>/`，更新回滚应恢复备份。

## 验证

```bash
python3 -m unittest discover -s tests/game_assets -v
```

覆盖任务取消/失败、非法参数、文件越界、GLB/PNG 损坏、产物缺失、未知提交恢复和下载损坏。真实端到端验证记录见 `ACCEPTANCE.md`。

骰子六面点数等精确规则目前仍由输入生成模型决定；这条通用图生流程不能从一张图保证隐藏面的正确数字。水晶折射、内部光效需要目标引擎材质适配，不能把二维高光完整烘焙后当成物理材质。
