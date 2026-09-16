# 8191 本地 LatentSync 桥接

将本目录的 `__init__.py` 放到目标实例的独立 custom_nodes 目录；仅在该实例的 extra-model-paths 配置中添加目录。不要加载到共享实例。

依赖服务器已有 `/opt/latentsync/app`、独立 Python 环境 `/opt/latentsync/venv` 和 `/model/latentsync-1.6/checkpoints`。本节点不安装依赖、不下载模型，继承当前实例的 GPU 分配。执行前卸载 ComfyUI 模型以释放显存。

在输入目录放置视频与最终音频，在“LatentSync 1.6 本地口型同步”节点选择文件，VIDEO 输出连接原生 SaveVideo。可用视频文件作为音频源。默认 20 步、guidance 1.5、种子 1247。

输出为上游 LatentSync 的 25fps 视频；时长可能按帧对齐。不保证口型或身份质量，需播放验收。当前桥接使用文件选择输入，不自动连接 LTX/H3 生成输出。临时副本和日志保留在实例 temp/latentsync_* 中（实际 temp 根目录以实例配置为准）；结果保存在 output/LatentSync。

取消任务会终止推理子进程。输入路径限制在实例 input 目录，拒绝越界和越界符号链接。服务须能读取既有模型，且仅需写入自己的实例目录。

验证：`python3 deployments/latentsync_bridge/test_bridge.py`。
