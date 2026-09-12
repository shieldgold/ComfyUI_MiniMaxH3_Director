# GPU 实例调度

可选的「导演台 · GPU 实例」面板显示显存余量、GPU 利用率、队列和当前页面绑定的 GPU。选择目标后，点击「提交到所选 GPU」提交一次当前工作流。原有运行按钮仍使用当前页面实例。

素材从源实例的 input/output/temp 复制到目标 input/director_dispatch/<任务编号>/，工作流和执行图同时改写引用。不会覆盖目标同名素材，也不会移动正在执行的任务。同时在目标工作流程列表的 `Director-dispatch` 文件夹保存本次工作流，面板返回文件位置。保存失败时不提交生成任务，重复查询或重试不会覆盖用户后续编辑。目标必须安装工作流使用的节点和模型；模型参数由目标 ComfyUI 正常校验。

提交状态持久化到 SQLite；向目标发请求前先记录意图，网络超时或进程重启后不自动重发。面板提供「查询本次任务」和目标实例链接，结果保存在目标实例的历史记录中。状态 unknown 表示尚不能确认是否接收，需继续查询目标队列/历史，不应另建相同任务。

## 配置和扩展

调度服务使用部署环境提供的 JSON 配置。机器地址、实际端口、目录、来源白名单和任务记录应留在部署环境中，不提交到仓库。

- `listen` / `port`：调度服务的监听地址和端口。
- `database`：SQLite 文件路径，运行用户必须可写。
- `origins`：允许访问调度服务的 ComfyUI 页面来源（完整协议、主机和端口）。
- `instances`：实例数组；每项包含 `id`、物理卡编号 `gpu`、ComfyUI `port`，以及 `input`、`output`、`temp` 和 `workflows` 的绝对目录。`workflows` 指向目标用户的工作流目录，例如该实例 user 目录下的 `default/workflows`。

实例请求只发到本机回环地址；不接受浏览器提供任意服务器 URL。部署时限制为可信内网访问。Origin 白名单是浏览器访问边界，不替代网络隔离或用户认证。

使用 ComfyUI 已安装 aiohttp 的 Python 环境运行：

```sh
python tools/gpu_broker.py --config /path/to/local-config.json
```

创建未纳入 Git 的 `web/js/gpu_instances.json`，将 `broker_port` 设置为部署配置中的监听端口。保存当前工作流并刷新浏览器后，面板出现。

新增实例（包括 GPU 7）只需在 `instances` 中追加配置，并在 `origins` 中加入其页面来源。确认目标的导演台、模型和素材目录可用后，重启独立 broker 读取配置；已有 ComfyUI 服务无需因此重启。若目标需要补充插件或模型配置，应先确认其队列为空，再按部署环境要求操作。

回滚时删除 `gpu_instances.json` 隐藏面板，停止独立 broker，并撤销对应网络规则；保留已生成结果、同步素材和 SQLite 记录，以便追踪任务。

## 验证

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
node --test tests/*.test.mjs
```

测试覆盖嵌套时间线和工作流同步、目标同名文件保护、output 转 input、缺失素材、越界和符号链接、提示词保持原文、重复提交/超时/重启、缺失节点及 Origin 边界。

部署验收还应通过浏览器选择目标并提交小型图片工作流，核对目标历史、素材 SHA-256 和输出像素，验证重复提交返回同一任务编号。图片测试验证调度和素材链路，不代表已通过 H3 视频推理验收。
