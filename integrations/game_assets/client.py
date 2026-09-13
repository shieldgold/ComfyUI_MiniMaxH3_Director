#!/usr/bin/env python3
"""Submit once, resume by saved prompt ID, download resulting asset bundle."""
import argparse
import json
import shutil
import tempfile
import zipfile
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def request(base, route, data=None, content_type='application/json'):
    req = urllib.request.Request(base.rstrip('/') + route, data=data)
    if data is not None:
        req.add_header('Content-Type', content_type)
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.load(response)


def atomic(path, data):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    tmp.replace(path)



def download_bundle(base, bundle, output):
    """Validate a temporary download before replacing the user's destination."""
    path = Path(bundle)
    if path.is_absolute() or '..' in path.parts or path.name != 'asset.zip':
        raise ValueError('Invalid relative bundle path')
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    query = urllib.parse.urlencode({'filename': path.name, 'subfolder': str(path.parent), 'type': 'output'})
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, prefix=output.name + '.', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            with urllib.request.urlopen(base.rstrip('/') + '/view?' + query, timeout=120) as response:
                shutil.copyfileobj(response, stream)
        with zipfile.ZipFile(temporary) as archive:
            bad = archive.testzip()
            if bad:
                raise ValueError('Corrupt ZIP member: ' + bad)
            names = set(archive.namelist())
            if not {'manifest.json', 'report.json', 'model.glb'}.issubset(names):
                raise ValueError('Asset ZIP is missing required files')
            manifest = json.loads(archive.read('manifest.json'))
            if not isinstance(manifest, dict) or not isinstance(manifest.get('files'), list) or not manifest['files']:
                raise ValueError('Invalid asset manifest')
            for name in manifest['files']:
                if not isinstance(name, str) or Path(name).is_absolute() or '..' in Path(name).parts or name not in names:
                    raise ValueError('Invalid or missing manifest member')
        temporary.replace(output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server', default='http://10.10.11.8:8188')
    parser.add_argument('--image', type=Path)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--target-faces', type=int, default=20000)
    parser.add_argument('--surface-resolution', type=int, choices=[128,256], default=256)
    parser.add_argument('--texture-size', type=int, choices=[512,1024,2048], default=1024)
    parser.add_argument('--output', type=Path, default=Path('asset.zip'))
    args = parser.parse_args()
    if args.resume:
        state = json.loads(args.state.read_text())
        base = state['server']
        if not state.get('prompt_id'):
            matches = []
            queue = request(base, '/queue')
            entries = queue.get('queue_running', []) + queue.get('queue_pending', [])
            entries += [v.get('prompt', []) for v in request(base, '/history?max_items=1000').values()]
            for entry in entries:
                if len(entry) > 3 and entry[3].get('operation_key') == state['operation_key']:
                    matches.append(entry[1])
            matches = list(set(matches))
            if len(matches) != 1:
                raise SystemExit('Cannot uniquely recover submission from queue/history; state retained and no duplicate submitted.')
            state['prompt_id'] = matches[0]
            atomic(args.state, state)
    else:
        if args.state.exists():
            raise SystemExit('State already exists; use --resume. Never overwrite an uncertain submission.')
        if not args.image or not args.image.is_file():
            parser.error('--image is required for a new task')
        if not 1000 <= args.target_faces <= 100000:
            parser.error('--target-faces must be 1000..100000')
        base = args.server.rstrip('/')
        operation = str(uuid.uuid4())
        boundary = 'gameasset' + uuid.uuid4().hex
        filename = operation + args.image.suffix.lower()
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n').encode() + args.image.read_bytes() + f'\r\n--{boundary}--\r\n'.encode()
        upload = request(base, '/upload/image', body, 'multipart/form-data; boundary=' + boundary)
        prompt = json.loads((Path(__file__).parent / 'workflows' / 'image_to_game_asset_api.json').read_text())
        prompt['122']['inputs']['image'] = '/'.join(x for x in [upload.get('subfolder'), upload['name']] if x)
        prompt['900']['inputs'].update(target_faces=args.target_faces, texture_size=str(args.texture_size), surface_resolution=str(args.surface_resolution))
        workflow = json.loads((Path(__file__).parent / 'workflows' / 'image_to_game_asset.json').read_text())
        for node in workflow['nodes']:
            if node['id'] == 122:
                node['widgets_values'][0] = prompt['122']['inputs']['image']
                node.setdefault('widgets_values_named', {})['image'] = prompt['122']['inputs']['image']
            elif node['id'] == 900:
                node['widgets_values'] = [args.target_faces, str(args.texture_size), '256', str(args.surface_resolution)]
        state = {'server':base,'operation_key':operation,'status':'submission_pending','image':str(args.image)}
        args.state.parent.mkdir(parents=True,exist_ok=True)
        # Exclusive creation prevents accidental duplicate submissions from two clients.
        with args.state.open('x') as f:
            json.dump(state, f, indent=2)
        try:
            result = request(base,'/prompt',json.dumps({'prompt':prompt,'client_id':operation,'extra_data':{'operation_key':operation,'extra_pnginfo':{'workflow':workflow}}}).encode())
        except Exception:
            state['status'] = 'submission_unknown'
            atomic(args.state,state)
            raise
        if 'prompt_id' not in result:
            state.update(status='rejected',response=result)
            atomic(args.state,state)
            raise SystemExit(str(result))
        state.update(status='queued',prompt_id=result['prompt_id'])
        atomic(args.state,state)
        print('prompt_id=' + state['prompt_id'],flush=True)
    while True:
        try:
            history = request(base, '/history/' + state['prompt_id'])
        except (urllib.error.URLError,TimeoutError):
            time.sleep(5)
            continue
        item = history.get(state['prompt_id'])
        if item:
            status = item.get('status',{})
            if status.get('status_str') == 'error':
                state.update(status='failed',error=status.get('messages'))
                atomic(args.state,state)
                raise SystemExit('Pipeline failed; inspect saved state and server job log')
            if status.get('completed'):
                output = item.get('outputs',{}).get('900',{})
                state.update(status='download_pending', outputs=output)
                atomic(args.state, state)
                print(json.dumps(output, ensure_ascii=False, indent=2), flush=True)
                texts = output.get('text', [])
                bundle = next((t for t in texts if isinstance(t, str) and t.endswith('/asset.zip')), None)
                if bundle is None:
                    state.update(status='output_invalid', error='Completed pipeline returned no asset bundle')
                    atomic(args.state, state)
                    raise SystemExit(state['error'])
                try:
                    download_bundle(base, bundle, args.output)
                except Exception as error:
                    state.update(status='download_failed', error=str(error))
                    atomic(args.state, state)
                    raise
                state.pop('error', None)
                state.update(status='complete', bundle=bundle, local_bundle=str(args.output.resolve()))
                atomic(args.state, state)
                print('Downloaded and verified: ' + str(args.output.resolve()))
                return
        time.sleep(5)

if __name__ == '__main__':
    main()
