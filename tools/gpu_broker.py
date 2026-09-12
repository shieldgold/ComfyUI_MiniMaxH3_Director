"""Optional same-host ComfyUI dispatcher. Run with --config /etc/comfyui/director-gpus.json."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import uuid

from aiohttp import ClientSession, ClientTimeout, web

MEDIA_KEYS = {'videoFile', 'imageFile', 'audioFile', 'previewImageFile', 'pairedAudioFile',
              'video_file', 'image_file', 'audio_file'}
EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif', '.mp4', '.mov', '.webm',
              '.mkv', '.avi', '.wav', '.mp3', '.flac', '.ogg', '.m4a', '.aac'}


def contained(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if path == root or not path.is_relative_to(root):
        raise ValueError('素材路径超出实例目录')
    return path


def transfer_assets(value, source, target, operation):
    """Copy referenced media into an operation namespace; never overwrite target input."""
    copied = {}

    def visit(item, key='', kind='input', subfolder=''):
        if isinstance(item, dict):
            kind = item.get('type', kind)
            if kind not in ('input', 'output', 'temp'):
                kind = 'input'
            subfolder = item.get('subfolder', '')
            result = {k: visit(v, k, kind, subfolder) for k, v in item.items()}
            if any(result.get(k) != item.get(k) for k in MEDIA_KEYS if k in item):
                result['type'] = 'input'
                result['subfolder'] = ''
            return result
        if isinstance(item, list):
            return [visit(v, key, kind, subfolder) for v in item]
        if not isinstance(item, str) or not item:
            return item
        if key in {'text', 'prompt', 'positive', 'negative', 'description', 'filename_prefix'}:
            return item
        if item.lstrip().startswith(('{', '[')):
            try:
                decoded = json.loads(item)
            except ValueError:
                return item
            return json.dumps(visit(decoded), ensure_ascii=False)
        raw = item
        suffix = ''
        for annotation in ('input', 'output', 'temp'):
            if raw.endswith(f' [{annotation}]'):
                kind = annotation
                raw = raw[:-(len(annotation) + 3)]
                suffix = ' [input]'
        if Path(raw).suffix.lower() not in EXTENSIONS:
            return item
        if key not in MEDIA_KEYS and (len(raw) > 512 or '\n' in raw):
            return item
        if subfolder and '/' not in raw:
            raw = f'{subfolder}/{raw}'
        path = contained(source[kind], raw)
        if not path.is_file():
            if key in MEDIA_KEYS:
                raise ValueError(f'找不到素材：{raw}')
            return item
        identity = str(path)
        if identity not in copied:
            name = hashlib.sha256(identity.encode()).hexdigest()[:16] + path.suffix.lower()
            relative = f'director_dispatch/{operation}/{name}'
            dest = contained(target['input'], relative)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, dest)
            copied[identity] = relative
        return copied[identity] + suffix

    return visit(value), len(copied)


class Broker:
    def __init__(self, config):
        self.config = config
        self.instances = {x['id']: x for x in config['instances']}
        self.lock = asyncio.Lock()
        self.db = sqlite3.connect(config['database'])
        self.db.execute('CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, digest TEXT, result TEXT)')
        self.db.commit()

    def save(self, operation, digest, result):
        self.db.execute('INSERT OR REPLACE INTO operations VALUES (?, ?, ?)',
                        (operation, digest, json.dumps(result)))
        self.db.commit()

    async def call(self, instance, path, body=None):
        url = f"http://127.0.0.1:{instance['port']}{path}"
        async with ClientSession(timeout=ClientTimeout(total=120 if body else 6)) as session:
            async with session.request('POST' if body is not None else 'GET', url, json=body) as response:
                data = await response.json()
                return response.status, data

    async def status(self, request):
        utilization = {}
        try:
            process = await asyncio.create_subprocess_exec(
                'nvidia-smi', '--query-gpu=index,utilization.gpu', '--format=csv,noheader,nounits',
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            try:
                output, _ = await asyncio.wait_for(process.communicate(), timeout=5)
                for line in output.decode().splitlines():
                    index, percent = line.split(',')
                    utilization[int(index)] = int(percent)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        except (OSError, ValueError):
            pass
        async def read(instance):
            result = {k: instance[k] for k in ('id', 'port', 'gpu')}
            result['utilization'] = utilization.get(instance['gpu'])
            try:
                (_, stats), (_, queue), (_, nodes) = await asyncio.gather(
                    self.call(instance, '/system_stats'), self.call(instance, '/queue'),
                    self.call(instance, '/object_info/MiniMaxH3Director'))
                result.update(online=True, director='MiniMaxH3Director' in nodes,
                              running=len(queue['queue_running']), pending=len(queue['queue_pending']),
                              device=stats['devices'][0])
            except Exception:
                result.update(online=False, director=False)
            return result
        return web.json_response({'instances': await asyncio.gather(*(read(i) for i in self.instances.values()))})

    async def submit(self, request):
        body = await request.json()
        operation = str(uuid.UUID(body['operation_key']))
        source = self.instances[body['source']]
        target = self.instances[body['target']]
        digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        async with self.lock:
            row = self.db.execute('SELECT digest, result FROM operations WHERE id=?', (operation,)).fetchone()
            if row:
                if row[0] != digest:
                    raise ValueError('同一提交标识对应的工作流已改变，请创建新提交')
                return web.json_response(json.loads(row[1]))
            # Fail before submitting if the target lacks a node type.
            _, nodes = await self.call(target, '/object_info')
            missing = {n['class_type'] for n in body['prompt'].values()} - nodes.keys()
            if missing:
                raise ValueError('目标缺少节点：' + ', '.join(sorted(missing)))
            data = {'prompt': body['prompt'], 'extra_data': {'extra_pnginfo': {'workflow': body['workflow']}}}
            if source['id'] != target['id']:
                data, count = await asyncio.to_thread(transfer_assets, data, source, target, operation)
            else:
                count = 0
            workflow_file = f'Director-dispatch/{operation}.json'
            if not target.get('workflows'):
                raise ValueError('目标未配置 workflows 目录，无法保存工作流')
            path = contained(target['workflows'], workflow_file)
            workflow = data['extra_data']['extra_pnginfo']['workflow']
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.exists():
                    if json.loads(path.read_text()) != workflow:
                        raise ValueError('目标工作流文件已被修改，请创建新提交')
                else:
                    with path.open('x', encoding='utf-8') as output:
                        json.dump(workflow, output, ensure_ascii=False, indent=2)
            except OSError as exc:
                raise ValueError('目标工作流保存失败，未提交生成任务') from exc
            data['prompt_id'] = operation
            result = {'state': 'unknown', 'prompt_id': operation, 'target': target['id'],
                      'port': target['port'], 'assets': count, 'workflow_file': workflow_file,
                      'message': '提交结果待核对；请查询状态，不要再次提交同一任务。'}
            # Persist intent BEFORE the request. A restart or timeout must not resend it.
            self.save(operation, digest, result)
            try:
                code, response = await self.call(target, '/prompt', data)
                if code == 200:
                    result.update(state='queued', message='已提交到目标实例')
                elif code == 400:
                    result.update(state='rejected', message=json.dumps(response, ensure_ascii=False))
            except Exception:
                pass
            self.save(operation, digest, result)
            return web.json_response(result)

    async def operation(self, request):
        operation = str(uuid.UUID(request.match_info['operation']))
        row = self.db.execute('SELECT digest, result FROM operations WHERE id=?', (operation,)).fetchone()
        if not row:
            raise web.HTTPNotFound()
        result = json.loads(row[1])
        instance = self.instances[result['target']]
        try:
            _, history = await self.call(instance, f'/history/{operation}')
            if operation in history:
                status = history[operation].get('status', {})
                result.update(state='error' if status.get('status_str') == 'error' else 'completed',
                              message='目标执行失败' if status.get('status_str') == 'error' else '目标执行完成')
            else:
                _, queue = await self.call(instance, '/queue')
                for key, state in (('queue_running', 'running'), ('queue_pending', 'queued')):
                    if any(entry[1] == operation for entry in queue[key]):
                        result.update(state=state, message='目标正在执行' if state == 'running' else '目标排队中')
                        break
        except Exception:
            result['message'] = '目标暂不可达；保留原提交标识，稍后查询'
        self.save(operation, row[0], result)
        return web.json_response(result)


def create_app(config):
    origins = set(config['origins'])

    @web.middleware
    async def access(request, handler):
        origin = request.headers.get('Origin')
        if origin not in origins:
            raise web.HTTPForbidden(text='Origin not allowed')
        try:
            response = web.Response() if request.method == 'OPTIONS' else await handler(request)
        except (ValueError, KeyError, TypeError) as exc:
            response = web.json_response({'error': str(exc)}, status=400)
        response.headers.update({'Access-Control-Allow-Origin': origin,
                                 'Vary': 'Origin', 'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
                                 'Access-Control-Allow-Headers': 'Content-Type'})
        return response

    broker = Broker(config)
    app = web.Application(middlewares=[access], client_max_size=64 * 1024 ** 2)
    app.router.add_get('/instances', broker.status)
    app.router.add_post('/submit', broker.submit)
    app.router.add_get('/operations/{operation}', broker.operation)
    async def options(request):
        return web.Response()
    app.router.add_route('OPTIONS', '/{path:.*}', options)
    async def close(app):
        broker.db.close()
    app.on_cleanup.append(close)
    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    web.run_app(create_app(config), host=config.get('listen', '127.0.0.1'), port=config.get('port', 8193))
