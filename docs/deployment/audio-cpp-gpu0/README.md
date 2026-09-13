# audio.cpp GPU0 部署

目标：在 `10.10.11.8` 第一张卡（GPU0，CMP 170HX 64GB，SM80）上提供中文配音与声音克隆网页/API。与原有 GPU0 Qwen 服务共用显卡；不停止或改动原有 Qwen 配置。

## 固定版本和目录

- 官方发行版：audio.cpp `v0.7.4`，Ubuntu x64 CUDA 12.8 Colab 发行包。
- 二进制：`/opt/audio.cpp/releases/v0.7.4/audiocpp_server`。
- 二进制 SHA-256：`7791730b08a9eae06e4ed489a498be925ffc01057f37d09309f18fb383eadba6`，与发行包 SHA256SUMS 一致（清单原路径前缀为 dist/）。
- 独立运行库：`/opt/audio.cpp/runtime/lib`，复制已有 LatentSync 环境的 CUDA 12 cuBLAS、CUDA Runtime、cuFFT、NCCL 动态库，不修改来源。
- 模型：`/model/audio-cpp/`。
- 配置：`/etc/audio-cpp/server.json`。
- 状态、下载和验收：`/var/lib/audio-cpp/`。
- 服务用户：`audiocpp`；服务单元：`audio-cpp-gpu0.service`。

## 模型来源

模型从 `https://hf-mirror.com/audio-cpp/audio.cpp-gguf/resolve/main/` 下载。

- Qwen3-TTS 1.7B CustomVoice Q8_0：预设音色中文配音，API id `qwen3-tts-customvoice`，默认 Vivian。
- Qwen3-TTS 1.7B Base Q8_0 v2：参考音频克隆，API id `qwen3-tts-clone`。

每个 GGUF 的大小与 SHA-256 来自镜像 API LFS 元数据，校验清单见 [model-sha256.txt](model-sha256.txt)。所有文件校验成功后才启动服务。

## 服务设置

内网入口：`http://10.10.11.8:8090`。固定 `CUDA_VISIBLE_DEVICES=0` 与 `device=0`；CUDA 后端识别到唯一可见的 GPU 为 CMP 170HX。

懒加载，最多常驻一个模型；五分钟无请求后卸载；模型加载保留至少 8192 MiB 估算可用内存余量。该余量检查不等价于 GPU 硬配额，仍需监控同卡业务。网页使用固定模型配置，不开启任意模型下载管理。

配置和 systemd 单元分别留档于本目录。服务为开机自启；日常维护：

```bash
systemctl status audio-cpp-gpu0.service
journalctl -u audio-cpp-gpu0.service -n 80 --no-pager
systemctl restart audio-cpp-gpu0.service
```

撤回部署时，`systemctl disable --now audio-cpp-gpu0.service` 即停止服务并释放其 GPU 资源；模型和输出可保留。

## 验收方法

1. 固定发行包二进制和两个 GGUF 校验。
2. 检查 API 配音返回真实 WAV，记录时长、采样率、SHA-256 和耗时。
3. 以上一步合成语音作为克隆参考，生成不同中文文本并检查 WAV。
4. 浏览器验证配置模型可见、实际请求及音频播放。
5. 检查新服务 PID 确实位于物理 GPU0，原有 Qwen 服务仍健康。

验收请求使用合成参考音频，不上传用户声音到外部平台。请求记录与样片保存在服务器 `/var/lib/audio-cpp/acceptance/`。

## 2026-09-13 实测结果

- 两个 GGUF 的 SHA-256 均为 OK；CUDA 发行包已成功执行 SM80 推理。
- 配音 API：返回 24kHz 单声道、6.8 秒 WAV，326,444 字节。首次请求含冷加载与预热，耗时 48.94 秒。
- 克隆 API：以合成配音为参考生成不同文本，返回 24kHz 单声道、5.2 秒 WAV，249,644 字节，耗时 6.10 秒。
- Chrome 中文界面显示两个模型。网页实际生成 42 字中文，显示 4.89 秒完成并出现可播放音轨和保存 WAV 按钮；点击播放后控件进入 pause 状态。
- 新服务 PID 3918022 与原 Qwen PID 1595870 位于同一物理 GPU0 UUID `GPU-c6d2c525-73bb-9ac9-d96f-d6af0bc0a17d`。新增进程观测约 3.5–4.3GB 显存，非峰值基准。
- 服务 active/enabled；三个原 Qwen 推理服务保持 active，GPU0 与 vision 健康检查均 HTTP 200。
- 功能验证通过；声音相似度、自然度和长文稳定性仍需使用者试听/进一步测试，本次没有把 WAV 有效性当作主观音质验收。

安装时发行包顶层目录带 0700 权限，已将 `/opt/audio.cpp/releases/v0.7.4` 调整为 root 所有、0755，解决专用服务用户无法执行的问题。GGUF 内嵌旧版 spec，运行时按发行版自带 schema-v1 契约验证，实际两条推理均成功。
