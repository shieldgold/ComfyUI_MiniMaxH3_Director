import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

SPEC = importlib.util.spec_from_file_location('game_assets_client', Path(__file__).resolve().parents[2] / 'integrations/game_assets/client.py')
client = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(client)


def archive_bytes(include_model=True):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        archive.writestr('manifest.json', json.dumps({'files': ['report.json', 'model.glb']}))
        archive.writestr('report.json', '{}')
        if include_model:
            archive.writestr('model.glb', b'glTF')
    return stream.getvalue()


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / 'state.json'
        self.output = self.root / 'asset.zip'
        self.argv = ['client.py', '--resume', '--state', str(self.state), '--output', str(self.output)]

    def save_state(self, prompt=True):
        state = {'server': 'http://test.invalid', 'operation_key': 'operation', 'status': 'submission_unknown'}
        if prompt:
            state['prompt_id'] = 'prompt'
        self.state.write_text(json.dumps(state))

    def history(self, bundle=True):
        return {'prompt': {'status': {'completed': True}, 'outputs': {'900': {'text': ['game-assets/job/asset.zip'] if bundle else ['report only']}}}}

    def test_unknown_submission_recovered_without_resubmission(self):
        self.save_state(prompt=False)
        responses = [ {'queue_running': [[0, 'prompt', {}, {'operation_key': 'operation'}]]}, {}, self.history()]
        with patch.object(client, 'request', side_effect=responses) as request, patch.object(client.urllib.request, 'urlopen', return_value=io.BytesIO(archive_bytes())), patch('sys.argv', self.argv):
            client.main()
        self.assertEqual([call.args[1] for call in request.call_args_list], ['/queue', '/history?max_items=1000', '/history/prompt'])
        self.assertTrue(all(len(call.args) == 2 for call in request.call_args_list))
        self.assertEqual(json.loads(self.state.read_text())['status'], 'complete')
        self.assertTrue(self.output.is_file())

    def test_unresolved_submission_never_resubmits(self):
        self.save_state(prompt=False)
        with patch.object(client, 'request', side_effect=[{}, {}]) as request, patch('sys.argv', self.argv):
            with self.assertRaisesRegex(SystemExit, 'Cannot uniquely recover'):
                client.main()
        self.assertEqual(request.call_count, 2)
        self.assertEqual(json.loads(self.state.read_text())['status'], 'submission_unknown')

    def test_completed_without_bundle_is_not_success(self):
        self.save_state()
        with patch.object(client, 'request', return_value=self.history(bundle=False)), patch('sys.argv', self.argv):
            with self.assertRaisesRegex(SystemExit, 'no asset bundle'):
                client.main()
        self.assertEqual(json.loads(self.state.read_text())['status'], 'output_invalid')
        self.assertFalse(self.output.exists())

    def test_corrupt_download_retains_previous_destination(self):
        self.save_state()
        self.output.write_bytes(b'previous archive')
        with patch.object(client, 'request', return_value=self.history()), patch.object(client.urllib.request, 'urlopen', return_value=io.BytesIO(b'not zip')), patch('sys.argv', self.argv):
            with self.assertRaises(zipfile.BadZipFile):
                client.main()
        self.assertEqual(self.output.read_bytes(), b'previous archive')
        self.assertEqual(json.loads(self.state.read_text())['status'], 'download_failed')
        self.assertEqual(list(self.root.glob('asset.zip.*.tmp')), [])

    def test_zip_crc_corruption_is_rejected(self):
        damaged = archive_bytes().replace(b'glTF', b'glTX')
        with patch.object(client.urllib.request, 'urlopen', return_value=io.BytesIO(damaged)):
            with self.assertRaisesRegex(ValueError, 'Corrupt ZIP member'):
                client.download_bundle('http://test.invalid', 'game-assets/job/asset.zip', self.output)
        self.assertFalse(self.output.exists())

    def test_zip_missing_model_is_rejected(self):
        with patch.object(client.urllib.request, 'urlopen', return_value=io.BytesIO(archive_bytes(include_model=False))):
            with self.assertRaisesRegex(ValueError, 'missing required'):
                client.download_bundle('http://test.invalid', 'game-assets/job/asset.zip', self.output)
        self.assertFalse(self.output.exists())

    def test_path_traversal_is_rejected_before_network(self):
        with patch.object(client.urllib.request, 'urlopen') as network:
            with self.assertRaises(ValueError):
                client.download_bundle('http://test.invalid', '../asset.zip', self.output)
            network.assert_not_called()


if __name__ == '__main__':
    unittest.main()
