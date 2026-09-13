# 2026-09-13 实机验收

服务器 `10.10.11.8`，ComfyUI GPU3 `8188`，Blender 4.0.2 CPU 后处理。

## 最终 API 全链路

通过本目录 `client.py` 上传官方 `viking_wolf_rune_axe.png`，提交完整 Pixal3D 工作流，等待 Blender 后处理，并从 ComfyUI `/view` 下载 ZIP。

- prompt_id：`48ec1fe1-b654-4ff1-a112-faee0d368819`
- job_id：`cca3ee6620c94e85b2fa213332a20d85`
- ComfyUI 显示执行耗时：207.94 秒（单次样例，不是性能保证）。
- 目录：`/var/lib/comfyui/gpu3/output/game-assets/cca3ee6620c94e85b2fa213332a20d85/`
- ZIP：30 个文件，95,817,388 bytes。
- ZIP SHA256：`b9302bcbae62e70ab58ead6d36e9cb69cd57157913d3f96958a184e36de05f12`

| 项目 | 结果 |
|---|---|
| 原始高模 | 694,941 三角形 |
| LOD0 | 19,998 三角形 |
| LOD1 | 9,998 三角形 |
| LOD2 | 4,999 三角形 |
| 碰撞盒 | 12 三角形 |
| 内嵌纹理 | 每个 LOD 三张 1024×1024 PNG，逐张解码成功 |
| 几何 | 顶点有限数值，全部三角索引在顶点数组范围内 |
| 六视图 | 前后左右上下逐张查看，模型可见 |
| 旋转视频 | ffprobe 解码通过，256×256，12 帧 |
| ZIP | CRC、清单与必需文件验证通过 |
| Blender | 独立重开工程成功，原始高模、三个 LOD、碰撞体及四张打包纹理均存在 |

模型仍有 6 条非流形边，报告保留此结果；UV 总面积约 0.395，无检测到退化面。此处验收的是可重复调用的资产生成处理流程，不代表美术或目标游戏引擎的发布验收。水晶材质、绑定布线、六面骰子数字规则和碰撞体贴合仍需专门处理。

## 修复并加入验证的实测问题

1. 直接对生成网格减面后 UV 面积不足 1%，造成点状烘焙。改为体素重建连续表面，验证 UV 面积至少 20%。
2. 导出器在导出时自动修复网格并清除三角缓存，曾输出只有节点、没有网格的 GLB。将网格验证提前到展开 UV 之前；产物检查现在要求真实 POSITION、三角索引和合法内嵌二进制范围。
3. Ubuntu Blender 未包含 OpenImageDenoiser，显式关闭降噪，使用 128 次 CPU 渲染采样及按模型尺度调整灯光。
4. MP4 改为必需产物，必须解码出 12 帧视频后才完成任务。

第一轮未通过独立几何检查的任务 `5ee0cca6-045c-486c-ab38-5b67e7544ff8` 已标记 `validation_failed`，其 ZIP 不应使用。

## 自动化验证

- 游戏资产 runner/client：22 项单元测试通过。
- 原 GPU broker：9 项测试通过（本地端口测试在允许绑定回环端口的环境执行）。
- 原时间线 FPS：6 项 Node 测试通过。
- Python 编译、JavaScript 语法、shell 语法和 diff 空白检查通过。

## 部署隔离

最终部署备份：`/var/backups/comfyui-game-assets-7cdf877618644d41a6fe165856c4d52a`。

只有 `comfyui-gpu3.service` 被重启；GPU7 原有 H3 任务在检查时仍持续运行。插件只在 GPU3 的 `GAME_ASSETS_ENABLED=1` 下注册。已有 Pixal3D 模板保留，新增模板位于 `GameAssets/image_to_game_asset.json`。

## 浏览器端验收

从服务器工作流入口加载后，在浏览器点击“执行”完成第二次实际运行。优化节点显示六视图及三个操作按钮，右侧 3D 预览已居中显示真实斧头模型。点击“下载资产 ZIP”打开实际 `/api/view` 下载地址，HTTP 200、`application/zip`、95,030,901 bytes；该 UI 任务目录为 `1c048cb727bd4a4da5bba6156b60d468`，状态 `completed`。

旧页面曾缓存安装前的节点定义；新页面验证已无缺失节点提示。以后安装新节点后应刷新整个页面。
