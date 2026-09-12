import { app } from "../../scripts/app.js";

// Deployment configuration is optional; normal single-instance installs have no panel.
app.registerExtension({
    name: "ComfyUI.MiniMaxH3Director.GPU",
    async setup() {
        let config;
        try {
            const response = await fetch(new URL("gpu_instances.json", import.meta.url));
            if (!response.ok) return;
            config = await response.json();
        } catch { return; }
        const base = new URL(location.origin);
        base.port = String(config.broker_port);
        const request = async (path, body) => {
            const response = await fetch(new URL(path, base), {
                method: body ? "POST" : "GET",
                headers: body ? { "Content-Type": "application/json" } : {},
                body: body ? JSON.stringify(body) : undefined,
                signal: AbortSignal.timeout(body ? 180000 : 10000),
            });
            const data = await response.json();
            if (!response.ok) throw Object.assign(new Error(data.error || `HTTP ${response.status}`), {rejected: response.status === 400});
            return data;
        };
        const panel = document.createElement("details");
        panel.id = "minimax-gpu-panel";
        panel.style.cssText = "position:fixed;right:16px;bottom:60px;z-index:1000;background:#222;color:#eee;padding:10px;border:1px solid #666;border-radius:8px;max-width:470px;font:13px sans-serif;box-shadow:0 4px 18px #0008";
        panel.innerHTML = `<summary style="cursor:pointer">导演台 · GPU 实例</summary>
            <p>选择执行实例，使用下方按钮提交一次当前工作流。</p>
            <select aria-label="目标 GPU 实例" style="width:100%;padding:6px"></select>
            <p data-status style="white-space:pre-wrap"></p>
            <button data-refresh>刷新显存 / 队列</button>
            <button data-submit disabled>提交到所选 GPU</button>
            <button data-check hidden>查询本次任务</button>
            <p data-result style="white-space:pre-wrap;overflow-wrap:anywhere;max-height:180px;overflow:auto"></p>
            <a data-open target="_blank" rel="noopener" hidden>打开目标实例查看任务 / 结果</a>
            <p style="color:#bbb">页面原有「运行」按钮仍在当前实例执行。</p>`;
        document.body.append(panel);
        const select = panel.querySelector("select");
        const status = panel.querySelector("[data-status]");
        const submit = panel.querySelector("[data-submit]");
        const check = panel.querySelector("[data-check]");
        const result = panel.querySelector("[data-result]");
        const open = panel.querySelector("[data-open]");
        let instances = [], sending = false;
        const storageKey = `minimax-gpu-operation:${location.origin}`;
        let operation = sessionStorage.getItem(storageKey);
        check.hidden = !operation;
        const show = data => {
            result.textContent = `${data.message}\n任务：${data.prompt_id}\n状态：${data.state} · 同步素材 ${data.assets} 个`;
            const target = new URL(location.origin);
            target.port = String(data.port);
            open.href = target.href;
            open.hidden = false;
            // Unknown submissions stay locked until their status can be reconciled.
            sending = data.state === "unknown";
            submit.disabled = sending || !select.value;
        };
        const refresh = async () => {
            try {
                const selected = select.value;
                instances = (await request("/instances")).instances;
                select.replaceChildren(...instances.map(i => {
                    const option = document.createElement("option");
                    option.value = i.id;
                    const free = ((i.device?.vram_free || 0) / 1024 ** 3).toFixed(1);
                    option.textContent = `GPU ${i.gpu} :${i.port} — ${!i.online ? "离线" : !i.director ? "缺少导演台" : `可用 ${free} GiB · 利用率 ${i.utilization ?? "?"}% · 运行 ${i.running} / 排队 ${i.pending}`}`;
                    option.disabled = !i.online || !i.director;
                    return option;
                }));
                if (instances.some(i => i.id === selected && i.online && i.director)) select.value = selected;
                else {
                    const available = instances.filter(i => i.online && i.director)
                        .sort((a, b) => (b.device?.vram_free || 0) - (a.device?.vram_free || 0));
                    select.value = available[0]?.id || "";
                }
                const current = instances.find(i => String(i.port) === location.port);
                status.textContent = `当前页面：GPU ${current?.gpu ?? "未知"}。已刷新 ${new Date().toLocaleTimeString()}。显存包含该 GPU 上所有进程占用。`;
                submit.disabled = sending || !select.value;
            } catch (error) {
                status.textContent = `状态读取失败：${error.message}`;
                submit.disabled = true;
            }
        };
        panel.querySelector("[data-refresh]").onclick = refresh;
        check.onclick = async () => {
            try { show(await request(`/operations/${operation}`)); }
            catch (error) { result.textContent = `查询失败：${error.message}。提交标识 ${operation} 已保留，请勿重复提交。`; }
        };
        submit.onclick = async () => {
            if (sending) return;
            sending = true;
            submit.disabled = true;
            let dispatched = false;
            try {
                const source = instances.find(i => String(i.port) === location.port);
                if (!source) throw new Error("当前实例不在调度配置中");
                for (const node of app.graph?._nodes || []) node._minimaxEditor?.flushTimelineSync?.();
                const graph = await app.graphToPrompt();
                operation = "10000000-1000-4000-8000-100000000000".replace(/[018]/g,
                    c => (Number(c) ^ crypto.getRandomValues(new Uint8Array(1))[0] & 15 >> Number(c) / 4).toString(16));
                sessionStorage.setItem(storageKey, operation);
                check.hidden = false;
                result.textContent = "正在同步素材并提交，请勿关闭页面…";
                dispatched = true;
                show(await request("/submit", {operation_key: operation, source: source.id,
                    target: select.value, prompt: graph.output, workflow: graph.workflow}));
            } catch (error) {
                result.textContent = `${error.message}${dispatched && !error.rejected ? "。请查询本次任务确认结果，避免重复提交。" : ""}`;
                sending = dispatched && !error.rejected;
                if (error.rejected) {
                    sessionStorage.removeItem(storageKey);
                    check.hidden = true;
                }
                submit.disabled = sending || !select.value;
            }
        };
        panel.addEventListener("toggle", () => { if (panel.open) refresh(); });
        if (operation) {
            sending = true;
            check.click();
        }
    },
});
