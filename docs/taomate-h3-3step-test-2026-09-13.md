# TaoMate-H3 三步 LoRA 实测（2026-09-13）

在 GPU4 的 ComfyUI（端口 8189）测试了 Robert1212star/TaoMate-H3-3Step-ComfyUI。结论：能够加载并生成有效视频，在本次相机工作流中速度更快，但运镜明显偏离八步对照，暂不替换原有默认配置。

## 下载与安装

- 国内镜像入口：`https://hf-mirror.com/Robert1212star/TaoMate-H3-3Step-ComfyUI/resolve/main/taomate_h3_3step_comfy.safetensors`
- 大小：2,481,007,456 字节。
- SHA-256：`c1c057121a5ebf77d708b8a5c331ebb78416b90775df465c02a4fa48688315cb`，与镜像模型 API 的 LFS OID 一致。
- 服务器位置：`/model/comfyui-models/minimax-h3/loras/taomate_h3_3step_comfy.safetensors`。
- 未更新 ComfyUI、未重启服务；未覆盖八步工作流。

## 同输入对照

基础模型为 MiniMax H3 FL2VA INT8 ConvRot；文本编码器为 Qwen3-VL 32B H3 INT8 ConvRot。使用已有相机工作流输入、相同轨迹和 seed 43，608×352、124 帧、24 fps。两组使用 `res_multistep`、`simple` 调度、LoRA 权重 1。

| 配置 | 执行耗时 | 输出 |
|---|---:|---|
| LightX2V FL2V Turbo 8-step，8 步 | 30.423 秒 | `TaoMate-test/AB-8step-seed43_00001_.mp4` |
| TaoMate-H3，3 步 | 18.557 秒 | `TaoMate-test/AB-3step-seed43_00001_.mp4` |

本次三步约快 1.64 倍，耗时减少约 39%。耗时取 execution_start 到 execution_success；两组均复用上游缓存，但采样与解码实际重新执行。仅 LoRA、步数、输出前缀不同。结果不是完整冷启动耗时，也不是多次重复基准测试。

原先 seed 42 的八步运行耗时 104.83 秒，三步耗时 16.28 秒，因缓存条件不同不用于计算加速比。另一次八步调用完全命中采样结果缓存（2.65 秒），同样排除。

## 验证与限制

- 两组任务完成，H.264 视频加 AAC 音轨，608×352、124 帧、24 fps，容器时长 5.167 秒。
- 三步视频在 Chrome 内实际解码播放完毕；关键帧已检查。
- 两个 seed 的三步样片保持了人物和夜景，没有明显噪声崩坏；但以仰视/横移效果为主，八步样片则明显向下俯视、展示城市。此结论仅适用于本次设置，不代表官方流式运行程序的效果，也未验证精确角度与音频质量。
- 转换版说明仅建议三步，没有给出完整采样器/调度器配方；本次沿用已有相机工作流，未验证官方分块三步调度。

## 测试入口与追踪

ComfyUI 工作流：`H3-Camera-TaoMate-3Step-Test.json`，保留初次 seed 42 三步测试设置，可自行更换图像及轨迹。

- 初次三步任务：`aa5f3b37-6bd2-402b-89cb-2888c7e89de7`。
- 公平八步任务：`97aab810-4fc3-4482-b793-ac5e09057ee9`。
- 公平三步任务：`72285519-d6fc-444e-97ab-e158ec4cc9a0`。
- 服务器证据目录：`/var/lib/comfyui/gpu4/user/taomate-test/`，包含提交前意图、执行参数、history 与媒体元数据。每次提交均先记录，避免重复派发。
