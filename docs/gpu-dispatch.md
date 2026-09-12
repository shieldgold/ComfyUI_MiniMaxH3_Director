# GPU 实例调度

可选的「导演台 · GPU 实例」面板显示显存余量、GPU 利用率、队列和当前页面绑定的 GPU。选择目标后，点击「提交到所选 GPU」提交一次当前工作流。原有运行按钮仍使用当前页面实例。

素材从源实例的 input/output/temp 复制到目标 input/director_dispatch/<任务编号>/，工作流和执行图同时改写引用。不会覆盖目标同名素材，也不会移动正在执行的任务。目标必须安装工作流使用的节点和模型；模型参数由目标 ComfyUI 正常校验。

提交状态持久化到 SQLite；向目标发请求前先记录意图，网络超时或进程重启后不自动重发。面板提供「查询本次任务」和目标实例链接，结果保存在目标实例的历史记录中。状态 unknown 表示尚不能确认是否接收，需继续查询目标队列/历史，不应另建相同任务。

## 部署范围

当前服务器目标：GPU 3 / 8188、GPU 4 / 8189、GPU 5 / 8190、GPU 6 / 8191。

1. 部署新增 tools/gpu_broker.py 和 web/js/minimax_gpu.js。独立调度服务不需要重启 GPU 5。
2. 在 GPU 3、6 的现有 YAML 后追加 GPU 5 的 minimax_h3 模型目录段，保留原有 Hunyuan/LTX 模型配置并备份文件；重新检查队列为空后才重启 GPU 3、6，使它们加载最新共享插件和模型列表。
3. 新建 /etc/comfyui/director-gpus.json、director-gpu-broker.service 和 SQLite 状态目录；使用 comfyui 用户运行，限制写入 /var/lib/comfyui。
4. 调度端口 8193 仅绑定 10.10.11.8，并添加独立 nftables 表，沿用现有 ComfyUI 的局域网白名单（10.0.0.0/8、127.0.0.0/8、192.168.0.0/16）。不会修改现有 ComfyUI 防火墙表。
5. 创建未纳入 Git 的 web/js/gpu_instances.json，内容为 {"broker_port":8193}。浏览器刷新后出现面板。正在编辑的页面先保存工作流。
6. 验收 GPU 状态、真实浏览器操作、跨实例小型图片任务、素材哈希和目标历史；不运行耗时视频生成测试，不中断 GPU 5。

配置示例（路径与 origin 必须按部署调整）：

```json
{
  "listen": "127.0.0.1",
  "port": 8193,
  "database": "/var/lib/comfyui/director-broker/operations.sqlite",
  "origins": ["http://localhost:8190", "http://localhost:8191"],
  "instances": [
    {"id":"gpu5", "gpu":5, "port":8190,
     "input":"/var/lib/comfyui/gpu5/input", "output":"/var/lib/comfyui/gpu5/output", "temp":"/var/lib/comfyui/gpu5/temp"},
    {"id":"gpu6", "gpu":6, "port":8191,
     "input":"/var/lib/comfyui/gpu6/input", "output":"/var/lib/comfyui/gpu6/output", "temp":"/var/lib/comfyui/gpu6/temp"}
  ]
}
```

启动：`python tools/gpu_broker.py --config /etc/comfyui/director-gpus.json`。依赖 ComfyUI 已安装的 aiohttp；只支持配置中列出的同机实例，不接受浏览器提供任意服务器 URL。Origin 白名单是浏览器访问边界，不替代网络隔离或用户认证；此服务用于已受信任的内网 ComfyUI 环境。

回滚：删除 gpu_instances.json 隐藏面板，停止独立 broker 服务及其防火墙服务，删除独立 nftables 表 director_broker_access；按需还原 GPU 3、6 YAML 备份并在空闲时重启。已生成的结果、同步素材及 SQLite 记录保留，避免丢失追踪证据。

## 验证

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
node --test tests/*.test.mjs
```

覆盖嵌套时间线和工作流同步、目标同名文件保护、output 转 input、缺失素材、越界和符号链接、重复提交/超时/重启、缺失节点及 Origin 边界。2026-09-12 已完成服务器部署及验收：

- GPU 3、6 加载导演台，枚举到 H3 fl2va/ref2va、Qwen3-VL 文本编码器和音视频 VAE；原模型配置保留。
- GPU 5 → GPU 6 测试任务 da2ff7f6-2ff7-4018-a9f2-e57b8cc67300 完成；重复提交返回同一任务，素材 SHA-256 和输出像素一致。
- 真实浏览器从 GPU 6 面板提交到 GPU 3，任务 02939077-d883-407b-8fda-4280f7f8d7a4 完成，面板查询显示 completed。
- 7 个调度测试和 6 个现有帧率测试通过。上述图片测试验证调度和素材链路，不代表已在 GPU 3、6 运行 H3 视频推理。GPU 5 未重启或中断。
