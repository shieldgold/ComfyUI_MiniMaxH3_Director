import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import uuid
from aiohttp.test_utils import TestClient, TestServer

spec = importlib.util.spec_from_file_location('gpu_broker', Path(__file__).parents[1] / 'tools/gpu_broker.py')
broker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(broker)


class Assets(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.source = {k: str(Path(self.tmp.name) / 'source' / k) for k in ('input', 'output', 'temp')}
        self.target = {k: str(Path(self.tmp.name) / 'target' / k) for k in ('input', 'output', 'temp')}
        for root in [*self.source.values(), *self.target.values()]:
            Path(root).mkdir(parents=True)

    def test_embedded_timeline_workflow_and_same_named_target(self):
        Path(self.source['input'], '口播.mp4').write_bytes(b'original')
        Path(self.target['input'], '口播.mp4').write_bytes(b'preserve')
        timeline = {'video': {'videoFile': '口播.mp4', 'fileName': '口播.mp4', 'type': 'input'}}
        data, count = broker.transfer_assets({'timeline_data': json.dumps(timeline), 'workflow': timeline},
                                             self.source, self.target, str(uuid.uuid4()))
        changed = json.loads(data['timeline_data'])
        self.assertEqual(count, 1)
        self.assertEqual(changed, data['workflow'])
        self.assertEqual(changed['video']['fileName'], changed['video']['videoFile'])
        self.assertEqual(Path(self.target['input'], changed['video']['videoFile']).read_bytes(), b'original')
        self.assertEqual(Path(self.target['input'], '口播.mp4').read_bytes(), b'preserve')

    def test_prompt_text_is_not_treated_as_an_asset(self):
        Path(self.source['input'], 'literal.png').write_bytes(b'image')
        data, count = broker.transfer_assets({'text': 'literal.png', 'prompt': 'literal.png',
                                              'filename_prefix': 'literal.png'},
                                             self.source, self.target, str(uuid.uuid4()))
        self.assertEqual(count, 0)
        self.assertEqual(data['text'], 'literal.png')
        self.assertEqual(data['prompt'], 'literal.png')

    def test_output_subfolder_moves_to_input(self):
        Path(self.source['output'], 'video').mkdir()
        Path(self.source['output'], 'video/a.mp4').write_bytes(b'a')
        data, _ = broker.transfer_assets({'videoFile': 'a.mp4', 'subfolder': 'video', 'type': 'output'},
                                         self.source, self.target, str(uuid.uuid4()))
        self.assertEqual(data['type'], 'input')
        self.assertEqual(data['subfolder'], '')
        self.assertTrue(Path(self.target['input'], data['videoFile']).is_file())

    def test_missing_traversal_and_symlink_rejected(self):
        outside = Path(self.tmp.name, 'outside.mp4')
        outside.write_bytes(b'secret')
        Path(self.source['input'], 'link.mp4').symlink_to(outside)
        for name in ('missing.mp4', '../../outside.mp4', str(outside), 'link.mp4'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                broker.transfer_assets({'videoFile': name}, self.source, self.target, str(uuid.uuid4()))


class Submission(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = {'database': str(Path(self.tmp.name, 'ops.db')), 'origins': ['http://local:8190'],
                       'instances': [{'id': 'gpu5', 'gpu': 5, 'port': 8190}]}
        self.broker = broker.Broker(self.config)
        self.addCleanup(self.broker.db.close)
        self.sent = 0
        async def call(instance, path, body=None):
            if path == '/object_info': return 200, {'Example': {}}
            if path == '/prompt':
                self.sent += 1
                raise TimeoutError()
            if path.startswith('/history/'): return 200, {}
            return 200, {'queue_running': [], 'queue_pending': []}
        self.broker.call = call
        self.body = {'operation_key': str(uuid.uuid4()), 'source': 'gpu5', 'target': 'gpu5',
                     'prompt': {'1': {'class_type': 'Example', 'inputs': {}}}, 'workflow': {}}

    async def send(self):
        parent = self
        class Request:
            async def json(self): return parent.body
        return json.loads((await self.broker.submit(Request())).text)

    async def test_timeout_retry_and_restart_never_resubmit(self):
        self.assertEqual((await self.send())['state'], 'unknown')
        self.assertEqual((await self.send())['state'], 'unknown')
        self.assertEqual(self.sent, 1)
        previous = self.broker
        self.broker = broker.Broker(self.config)
        self.addCleanup(self.broker.db.close)
        self.broker.call = previous.call
        self.assertEqual((await self.send())['state'], 'unknown')
        self.assertEqual(self.sent, 1)
        self.body['workflow'] = {'changed': True}
        with self.assertRaises(ValueError): await self.send()

    async def test_missing_nodes_fail_before_submission(self):
        self.body['prompt']['1']['class_type'] = 'Absent'
        with self.assertRaises(ValueError): await self.send()
        self.assertEqual(self.sent, 0)

    async def test_origin_allowlist(self):
        async with TestClient(TestServer(broker.create_app(self.config))) as client:
            response = await client.get('/instances', headers={'Origin': 'https://untrusted.example'})
            self.assertEqual(response.status, 403)
            response = await client.options('/submit', headers={'Origin': 'http://local:8190'})
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers['Access-Control-Allow-Origin'], 'http://local:8190')


if __name__ == '__main__': unittest.main()
