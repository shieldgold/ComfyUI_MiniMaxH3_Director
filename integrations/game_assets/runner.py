"""Isolated, cancellable Blender jobs. No ComfyUI imports in this module."""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import signal
import struct
import subprocess
import time
import uuid
import zipfile
import zlib

VIEWS = ('front', 'back', 'left', 'right', 'top', 'bottom')
MODELS = ('model.glb', 'lod1.glb', 'lod2.glb', 'collision.glb')
TEXTURES = ('base_color', 'roughness', 'metallic', 'normal')


def atomic_json(path: Path, data: dict) -> None:
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)


def validate_config(target_faces=20000, texture_size=1024, preview_size=256):
    if type(target_faces) is not int or not 1000 <= target_faces <= 100000:
        raise ValueError('target_faces must be an integer between 1000 and 100000')
    if type(texture_size) not in (int, str) or type(preview_size) not in (int, str):
        raise ValueError('Texture and preview sizes must be integer choices')
    texture_size, preview_size = int(texture_size), int(preview_size)
    if texture_size not in (512, 1024, 2048) or preview_size not in (256, 512):
        raise ValueError('Unsupported texture_size or preview_size')
    return dict(target_faces=target_faces, texture_size=texture_size, preview_size=preview_size)


def create_job(output_dir) -> Path:
    root = Path(output_dir).resolve() / 'game-assets'
    if root.is_symlink():
        raise ValueError('game-assets directory cannot be a symlink')
    root.mkdir(parents=True, exist_ok=True)
    job = root / uuid.uuid4().hex
    job.mkdir()
    return job


def checked_file(job: Path, relative: str) -> Path:
    candidate = job / relative
    if candidate.is_symlink() or not candidate.is_file() or not candidate.resolve().is_relative_to(job.resolve()):
        raise ValueError(f'Missing or unsafe artifact: {relative}')
    if candidate.stat().st_size == 0:
        raise ValueError(f'Empty artifact: {relative}')
    return candidate


def validate_glb(path: Path) -> None:
    size = path.stat().st_size
    with path.open('rb') as stream:
        header = stream.read(12)
        if len(header) != 12:
            raise ValueError(f'Truncated GLB: {path.name}')
        magic, version, length = struct.unpack('<4sII', header)
        if magic != b'glTF' or version != 2 or length != size:
            raise ValueError(f'Invalid GLB header: {path.name}')
        offset, first, binary_size = 12, True, None
        while offset < size:
            chunk_header = stream.read(8)
            if len(chunk_header) != 8:
                raise ValueError('Truncated GLB chunk')
            count, kind = struct.unpack('<I4s', chunk_header)
            if count % 4 or offset + 8 + count > size:
                raise ValueError('Invalid GLB chunk length')
            if first:
                if kind != b'JSON' or count > 64 * 1024 * 1024:
                    raise ValueError('Missing or oversized GLB JSON chunk')
                document = json.loads(stream.read(count))
                if document.get('asset', {}).get('version') != '2.0':
                    raise ValueError('Invalid glTF asset version')
                first = False
            else:
                if kind == b'BIN\0':
                    if binary_size is not None:
                        raise ValueError('Multiple GLB binary chunks')
                    binary_size = count
                stream.seek(count, 1)
            offset += 8 + count
        if first:
            raise ValueError('GLB has no chunks')
    validate_geometry(document, binary_size)


def validate_geometry(document: dict, binary_size) -> None:
    """Require indexed triangle geometry whose accessors fit the embedded BIN."""
    buffers = document.get('buffers', [])
    meshes = document.get('meshes', [])
    if not meshes or not binary_size:
        raise ValueError('GLB has no mesh geometry or embedded binary data')
    if len(buffers) != 1 or buffers[0].get('uri') is not None:
        raise ValueError('GLB geometry must use one embedded buffer')
    declared = buffers[0].get('byteLength')
    if type(declared) is not int or not 0 < declared <= binary_size:
        raise ValueError('Invalid embedded buffer length')
    views = document.get('bufferViews', [])
    accessors = document.get('accessors', [])
    for view in views:
        offset, length = view.get('byteOffset', 0), view.get('byteLength')
        if (view.get('buffer') != 0 or type(offset) is not int or type(length) is not int
                or offset < 0 or length <= 0 or offset + length > declared):
            raise ValueError('GLB bufferView exceeds embedded BIN')

    def accessor(index, position=False):
        if type(index) is not int or not 0 <= index < len(accessors):
            raise ValueError('Missing geometry accessor')
        value = accessors[index]
        view_index, count = value.get('bufferView'), value.get('count')
        if type(view_index) is not int or not 0 <= view_index < len(views):
            raise ValueError('Geometry accessor has no embedded bufferView')
        if type(count) is not int or count < 3:
            raise ValueError('Geometry accessor must contain at least 3 elements')
        if position:
            if value.get('type') != 'VEC3' or value.get('componentType') != 5126:
                raise ValueError('POSITION must use floating point VEC3')
            element_size = 12
        else:
            if value.get('type') != 'SCALAR' or value.get('componentType') not in (5121, 5123, 5125):
                raise ValueError('Invalid triangle index accessor')
            element_size = {5121: 1, 5123: 2, 5125: 4}[value['componentType']]
            if count % 3:
                raise ValueError('Triangle index count must be divisible by 3')
        view = views[view_index]
        offset, stride = value.get('byteOffset', 0), view.get('byteStride', element_size)
        if (type(offset) is not int or offset < 0 or type(stride) is not int or stride < element_size
                or offset + (count - 1) * stride + element_size > view['byteLength']):
            raise ValueError('Geometry accessor exceeds bufferView')

    for mesh in meshes:
        primitives = mesh.get('primitives', [])
        if not primitives:
            raise ValueError('GLB mesh has no primitives')
        for primitive in primitives:
            if primitive.get('mode', 4) != 4:
                raise ValueError('GLB primitive must contain triangles')
            accessor(primitive.get('attributes', {}).get('POSITION'), position=True)
            accessor(primitive.get('indices'))


def validate_png(path: Path) -> None:
    with path.open('rb') as stream:
        if stream.read(8) != b'\x89PNG\r\n\x1a\n':
            raise ValueError(f'Invalid PNG: {path.name}')
        decoder = zlib.decompressobj()
        seen_header = seen_data = False
        while True:
            header = stream.read(8)
            if len(header) != 8:
                raise ValueError('Truncated PNG')
            length, kind = struct.unpack('>I4s', header)
            if length > 64 * 1024 * 1024:
                raise ValueError('Oversized PNG chunk')
            data, crc = stream.read(length), stream.read(4)
            if len(data) != length or len(crc) != 4 or zlib.crc32(kind + data) & 0xffffffff != struct.unpack('>I', crc)[0]:
                raise ValueError('Corrupt PNG chunk')
            if not seen_header:
                if kind != b'IHDR' or length != 13 or not all(struct.unpack('>II', data[:8])):
                    raise ValueError('Invalid PNG dimensions')
                seen_header = True
            if kind == b'IDAT':
                decoder.decompress(data)
                seen_data = True
            if kind == b'IEND':
                if not seen_data or not decoder.eof:
                    raise ValueError('Incomplete PNG pixels')
                break


def verify_artifacts(job: Path) -> list[str]:
    files = list(MODELS) + ['model.blend', 'report.json'] + [f'views/{view}.png' for view in VIEWS]
    files += [f'textures/{name}.png' for name in TEXTURES]
    files += [str(path.relative_to(job)) for path in sorted((job / 'textures').glob('*.png')) if str(path.relative_to(job)) not in files]
    frames = sorted((job / 'turntable').glob('*.png'))
    if not frames:
        raise ValueError('Missing turntable PNG frames')
    files += [str(frame.relative_to(job)) for frame in frames]
    for relative in files:
        path = checked_file(job, relative)
        if path.suffix == '.glb':
            validate_glb(path)
        elif path.suffix == '.png':
            validate_png(path)
        elif path.suffix == '.blend':
            with path.open('rb') as stream:
                if stream.read(7) != b'BLENDER':
                    raise ValueError('Invalid Blender project')
    movie = checked_file(job, 'turntable.mp4')
    probe = subprocess.run([
        '/usr/bin/ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v',
        '-show_entries', 'stream=codec_type,width,height,nb_read_frames', '-of', 'json', str(movie),
    ], capture_output=True, text=True, check=True, timeout=60)
    if probe.stderr.strip():
        raise ValueError('Turntable MP4 decoding error: ' + probe.stderr.strip())
    streams = json.loads(probe.stdout).get('streams', [])
    if len(streams) != 1:
        raise ValueError('Turntable MP4 must contain one video stream')
    stream = streams[0]
    if (stream.get('codec_type') != 'video' or int(stream.get('width', 0)) <= 0
            or int(stream.get('height', 0)) <= 0 or int(stream.get('nb_read_frames', 0)) != 12):
        raise ValueError('Turntable MP4 must contain 12 valid video frames')
    files.append('turntable.mp4')
    report = json.loads((job / 'report.json').read_text(encoding='utf-8'))
    if not isinstance(report, dict):
        raise ValueError('report.json must contain an object')
    return files


def terminate_process(process):
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()


def run_job(job_dir, target_faces=20000, texture_size=1024, preview_size=256,
            cancel_check=None, timeout=1800, blender='/usr/bin/blender') -> dict:
    job = Path(job_dir).resolve()
    status = job / 'status.json'
    process = None
    started = time.monotonic()
    try:
        config = validate_config(target_faces, texture_size, preview_size)
        validate_glb(checked_file(job, 'source.glb'))
        config.update(job_dir=str(job), source=str(job / 'source.glb'))
        atomic_json(job / 'config.json', config)
        atomic_json(status, dict(state='waiting'))
        with (job.parent / '.blender.lock').open('a') as lock:
            while True:
                if cancel_check:
                    cancel_check()
                if time.monotonic() - started >= timeout:
                    raise TimeoutError('Blender job exceeded time limit')
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    time.sleep(0.2)
            atomic_json(status, dict(state='running'))
            with (job / 'blender.log').open('wb') as log:
                process = subprocess.Popen([
                    blender, '--background', '--factory-startup', '--threads', '8', '--python-exit-code', '1',
                    '--python', str(Path(__file__).with_name('blender_stage.py')),
                    '--', str(job / 'config.json'),
                ], stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    while process.poll() is None:
                        if cancel_check:
                            cancel_check()
                        if time.monotonic() - started >= timeout:
                            raise TimeoutError('Blender job exceeded time limit')
                        time.sleep(0.2)
                except BaseException:
                    terminate_process(process)
                    raise
                if process.returncode:
                    raise RuntimeError(f'Blender exited with code {process.returncode}; see blender.log')
        if cancel_check:
            cancel_check()
        files = verify_artifacts(job)
        manifest = dict(schema_version=1, job_id=job.name, files=files, report='report.json', model='model.glb')
        atomic_json(job / 'manifest.json', manifest)
        with zipfile.ZipFile(job / 'asset.zip.tmp', 'w', zipfile.ZIP_DEFLATED) as archive:
            for relative in files + ['manifest.json']:
                archive.write(checked_file(job, relative), relative)
        os.replace(job / 'asset.zip.tmp', job / 'asset.zip')
        atomic_json(status, dict(state='completed', bundle='asset.zip', manifest='manifest.json'))
        return dict(job_dir=str(job), model=str(job / 'model.glb'), report=str(job / 'report.json'),
                    manifest=str(job / 'manifest.json'), bundle=str(job / 'asset.zip'))
    except BaseException as error:
        if process is not None:
            terminate_process(process)
        atomic_json(status, dict(state='failed', error=str(error), error_type=type(error).__name__))
        raise
