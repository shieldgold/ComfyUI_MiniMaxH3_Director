import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import zlib

SPEC = importlib.util.spec_from_file_location('game_assets_runner', Path(__file__).resolve().parents[2] / 'integrations/game_assets/runner.py')
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def glb(document=None):
    if document is None:
        document = {
            'asset': {'version': '2.0'}, 'buffers': [{'byteLength': 42}],
            'bufferViews': [{'buffer': 0, 'byteOffset': 0, 'byteLength': 36}, {'buffer': 0, 'byteOffset': 36, 'byteLength': 6}],
            'accessors': [{'bufferView': 0, 'componentType': 5126, 'count': 3, 'type': 'VEC3'}, {'bufferView': 1, 'componentType': 5123, 'count': 3, 'type': 'SCALAR'}],
            'meshes': [{'primitives': [{'attributes': {'POSITION': 0}, 'indices': 1}]}],
            'nodes': [{'mesh': 0}], 'scenes': [{'nodes': [0]}], 'scene': 0,
        }
    data = json.dumps(document).encode()
    data += b' ' * (-len(data) % 4)
    binary = struct.pack('<9f3H', 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 1, 2)
    binary += b'\0' * (-len(binary) % 4)
    return (struct.pack('<4sII', b'glTF', 2, 28 + len(data) + len(binary))
            + struct.pack('<I4s', len(data), b'JSON') + data
            + struct.pack('<I4s', len(binary), b'BIN\0') + binary)


def png():
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(b'\0\xff\0\0')) + chunk(b'IEND', b'')


def artifacts(job):
    for name in runner.MODELS:
        (job / name).write_bytes(glb())
    (job / 'model.blend').write_bytes(b'BLENDER-v400test')
    (job / 'report.json').write_text('{}')
    (job / 'textures').mkdir()
    for name in runner.TEXTURES:
        (job / 'textures' / f'{name}.png').write_bytes(png())
    (job / 'views').mkdir()
    for name in runner.VIEWS:
        (job / 'views' / f'{name}.png').write_bytes(png())
    (job / 'turntable').mkdir()
    (job / 'turntable' / '0001.png').write_bytes(png())
    (job / 'turntable.mp4').write_bytes(b'test video, ffprobe mocked')


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.job = runner.create_job(self.temp.name)
        (self.job / 'source.glb').write_bytes(glb())

    def test_bounds(self):
        for value in [999, 100001, True, 1000.5]:
            with self.assertRaises(ValueError):
                runner.validate_config(value)
        for args in [(20000, 4096, 256), (20000, 1024, 128), (20000, 1024.5, 256), (20000, 1024, 256.5)]:
            with self.assertRaises(ValueError):
                runner.validate_config(*args)
        self.assertEqual(runner.validate_config()['target_faces'], 20000)

    def test_invalid_glb(self):
        for content in [b'', b'not a glb', struct.pack('<4sII', b'glTF', 1, 12), glb()[:-1]]:
            (self.job / 'source.glb').write_bytes(content)
            with self.assertRaises(ValueError):
                runner.validate_glb(self.job / 'source.glb')

    def test_nodes_only_glb_rejected(self):
        (self.job / 'source.glb').write_bytes(glb({'asset': {'version': '2.0'}, 'nodes': [{'name': 'Empty model'}]}))
        with self.assertRaisesRegex(ValueError, 'no mesh geometry'):
            runner.validate_glb(self.job / 'source.glb')

    def test_geometry_accessor_outside_binary_rejected(self):
        data = glb()
        length = struct.unpack('<I', data[12:16])[0]
        document = json.loads(data[20:20 + length])
        document['accessors'][0]['count'] = 100
        (self.job / 'source.glb').write_bytes(glb(document))
        with self.assertRaisesRegex(ValueError, 'exceeds bufferView'):
            runner.validate_glb(self.job / 'source.glb')
        document['accessors'][0]['count'] = 3
        document['bufferViews'][1]['byteOffset'] = 9999
        (self.job / 'source.glb').write_bytes(glb(document))
        with self.assertRaisesRegex(ValueError, 'exceeds embedded BIN'):
            runner.validate_glb(self.job / 'source.glb')

    def test_symlink_and_traversal_artifact_rejected(self):
        outside = Path(self.temp.name) / 'outside'
        outside.write_text('private')
        (self.job / 'link').symlink_to(outside)
        for name in ['link', '../../outside']:
            with self.assertRaises(ValueError):
                runner.checked_file(self.job, name)

    def test_worker_failure_recorded(self):
        with self.assertRaisesRegex(RuntimeError, 'exited'):
            runner.run_job(self.job, blender='/usr/bin/false')
        status = json.loads((self.job / 'status.json').read_text())
        self.assertEqual(status['state'], 'failed')
        self.assertFalse((self.job / 'asset.zip').exists())

    def test_success_exit_without_outputs_is_failure(self):
        with self.assertRaisesRegex(ValueError, 'Missing'):
            runner.run_job(self.job, blender='/usr/bin/true')
        self.assertEqual(json.loads((self.job / 'status.json').read_text())['state'], 'failed')

    def test_corrupt_png_rejected(self):
        artifacts(self.job)
        (self.job / 'views/front.png').write_bytes(png()[:-4])
        with self.assertRaises(ValueError):
            runner.verify_artifacts(self.job)

    def test_missing_texture_rejected(self):
        artifacts(self.job)
        (self.job / 'textures/normal.png').unlink()
        with self.assertRaisesRegex(ValueError, 'normal.png'):
            runner.verify_artifacts(self.job)

    def test_valid_outputs_packaged(self):
        artifacts(self.job)
        probe = {'streams': [{'codec_type': 'video', 'width': 256, 'height': 256, 'nb_read_frames': '12'}]}
        with patch.object(runner.subprocess, 'run', return_value=SimpleNamespace(stdout=json.dumps(probe), stderr="")):
            result = runner.run_job(self.job, blender='/usr/bin/true')
        with runner.zipfile.ZipFile(result['bundle']) as archive:
            self.assertIsNone(archive.testzip())
            self.assertIn('manifest.json', archive.namelist())
            self.assertIn('turntable.mp4', archive.namelist())
            for name in runner.TEXTURES:
                self.assertIn(f'textures/{name}.png', archive.namelist())
            self.assertNotIn('source.glb', archive.namelist())
        self.assertEqual(json.loads((self.job / 'status.json').read_text())['state'], 'completed')

    def test_missing_video_rejected(self):
        artifacts(self.job)
        (self.job / 'turntable.mp4').unlink()
        with self.assertRaisesRegex(ValueError, 'turntable.mp4'):
            runner.verify_artifacts(self.job)

    def test_bad_video_metadata_rejected(self):
        artifacts(self.job)
        valid = {'codec_type': 'video', 'width': 256, 'height': 256, 'nb_read_frames': '12'}
        for streams in [[], [dict(valid, nb_read_frames='11')], [dict(valid, width=0)], [dict(valid, codec_type='audio')], [dict(valid, nb_read_frames='N/A')]]:
            with self.subTest(streams=streams), patch.object(runner.subprocess, 'run', return_value=SimpleNamespace(stdout=json.dumps({'streams': streams}), stderr='')):
                with self.assertRaises(ValueError):
                    runner.verify_artifacts(self.job)

    def test_corrupt_video_worker_status_failed(self):
        artifacts(self.job)
        error = runner.subprocess.CalledProcessError(1, 'ffprobe')
        with patch.object(runner.subprocess, 'run', side_effect=error):
            with self.assertRaises(runner.subprocess.CalledProcessError):
                runner.run_job(self.job, blender='/usr/bin/true')
        self.assertEqual(json.loads((self.job / 'status.json').read_text())['state'], 'failed')
        self.assertFalse((self.job / 'asset.zip').exists())

    def test_cancel_terminates_process_before_lock_release(self):
        class Cancelled(Exception):
            pass
        calls = 0
        def cancel():
            nonlocal calls
            calls += 1
            if calls > 1:
                raise Cancelled('cancelled')
        class FakeProcess:
            pid = 12345
            def poll(self):
                return None
            def wait(self, timeout=None):
                return -15
        with patch.object(runner.subprocess, 'Popen', return_value=FakeProcess()), patch.object(runner.os, 'killpg') as kill:
            with self.assertRaises(Cancelled):
                runner.run_job(self.job, cancel_check=cancel)
            kill.assert_any_call(12345, runner.signal.SIGTERM)
        self.assertFalse((self.job / 'asset.zip').exists())

    def test_timeout_before_launch(self):
        with patch.object(runner.subprocess, 'Popen') as launch:
            with self.assertRaises(TimeoutError):
                runner.run_job(self.job, timeout=0)
            launch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
