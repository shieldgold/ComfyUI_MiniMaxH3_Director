# Pixal3D 四视图部署

新增工作流 `Pixal3D/pixal3d_multiview_4images.json`，保留原单图模板。四个 LoadImage 按正面、左侧、背面、右侧连接到 Pixal3DMultiViewConditioning，共同生成一份带纹理 GLB。

## 运行与回滚

GPU3 实例使用独立代码 `/opt/ComfyUI-pixal-multiview`，基础版本 `efa6c8f8`；仅应用官方已合并 PR 16048 的两个文件改动，补丁随本目录留档。共用已有 Python 环境与模型目录，保留原有自定义节点副本。其他 GPU 实例继续使用 `/opt/ComfyUI`。

服务覆盖项为 `comfyui-gpu3.service.d/multiview.conf`，内容见同名文件。回滚可移走该覆盖项，执行 systemctl daemon-reload，再重启空闲的 comfyui-gpu3；原代码及单图工作流未改。

## 模型来源和校验

- 文件：`pixal3d_multiview_int8_convrot.safetensors`
- 大小：5,584,555,824 字节
- SHA256：`6b1eb3328930d921d3b57508d9c46cceec1c174dcedeebc14f176ab67d49f477`
- 下载源：https://www.modelscope.cn/models/Comfy-Org/Pixal3D/resolve/master/diffusion_models/pixal3d_multiview_int8_convrot.safetensors
- 本次实际下载连接为国内 CDN `112.48.179.223`，探测连接 `112.48.183.211`。重定向地址会变，后续仍应检查实际连接。完整文件哈希与官方 Hugging Face LFS 元数据一致。

## 使用

在工作流列表的 Pixal3D 目录打开多视图文件，替换四张图后运行。默认图是 TencentARC/Pixal3D 官方 example，不是用户资产。

输入应是同一物体四个相隔 90 度、同高度的视角，顺序 front / left / back / right，对应官方方位角 0 / 90 / 180 / 270。图像保持共同的尺度、居中、方形黑底，最大尺寸约占画面 91%；不要独立裁剪成不同缩放比例。透明图建议先合成到黑底。FOV 默认 20 度。任意手机拍摄角度不等价于该固定环绕相机模板，需要先匹配视角与相机。

缺少侧面可断开相应输入，至少保留正面。不是将多张图拼成一张，也不是对四张图分别生成四个模型。

默认 1024 体素分辨率、512 重网格、约 5 万三角面，输出前缀 `3d/Pixal3D_multiview`。这是重建模型，不代表已经具备游戏拓扑、骨骼或引擎验收。

## 实测

2026-09-15：模型哈希通过，节点齐全；真实四图任务 `06fbbf5d-9558-4f1a-8924-0414388c5f09` 成功，耗时约 120.86 秒。输出 `3d/Pixal3D_multiview_00001.glb`，20,139,516 字节，49,960 三角面、1 个材质、3 张内嵌纹理。首次 API 转换曾遗漏动态下拉参数，后按命名参数修正，完整任务 node_errors 为空。

验收证据目录：服务器 `/var/lib/comfyui/gpu3/multiview-acceptance/`。官方工作流来源：https://github.com/Comfy-Org/ComfyUI/pull/16048 。官方样例：https://github.com/TencentARC/Pixal3D/tree/master/assets/mv_images/example 。

网页验收任务 `b8ef8bfb-d008-4458-b76a-65efbf409dee` 也成功，176.80 秒，结果 `3d/Pixal3D_multiview_00002.glb` 已出现在媒体资产列表。四张默认输入已调整到 input 根目录，解决前端对有效子目录图片的缺失误报。连接、视角、资源参数三个离线测试通过：`python3 verify_workflow.py`。

原单图回归任务进入采样后被中断，记录为 execution_interrupted，不能当作完整单图回归通过。当前验收确认多视图运行与文件结构有效；尚未完成成品与四视图的逐面视觉质量评审。

## 六视图扩展

`pixal3d_multiview_6images.json` 使用独立节点 `Pixal3DSixViewConditioning`，源码在 `six_view_node/`，部署到隔离实例 `custom_nodes/ComfyUI_Pixal3D_SixView/`。无需新增权重，继续复用已校验的多视图模型。四视图与单图模板不变。

这是一项本地节点扩展，不是官方四视图节点原生的六入口。它沿用官方任意视图聚合路径，将六个特征与六个相机矩阵传入；六面的重建质量，特别是模型对顶底视图的泛化，需另行验收。

固定六面：前(-Y)、左(+X)、后(+Y)、右(-X)、顶部(+Z)、底部(-Z)。顶部图的画面上方朝物体背面(+Y)，底部图的画面上方朝物体正面(-Y)。这些是相机坐标约定，不能把上下图任意转90度。不是绕物体每60度拍摄的六张图。正面必需，其他输入可断开。

各图保持相同物体尺度、视场角和居中构图，推荐黑底方图。测试六图由上一轮样例GLB统一相机渲染得到，用于功能检查，不是新的真实多角度拍摄样本。`test_six_view.py` 验证六相机位置、正交性、上下视图旋转约定和输入批次边界。

回滚六视图节点可将 `ComfyUI_Pixal3D_SixView` 移出 custom_nodes，在队列空闲时重启 GPU3；四视图节点无需回滚。

六视图实测（2026-09-15）：任务 `db021c7b-96ac-4abb-bc56-2532f59119d7` 成功，六张独立输入全部参与条件聚合，耗时 226.97 秒。输出 `3d/Pixal3D_sixview_00001.glb`，22,108,060 字节，49,971 三角面、1 个材质、3 张内嵌纹理；GLB 头与文件长度一致。此结果验证运行及文件结构，尚不代表真实拍摄六面输入的视觉质量验收。
