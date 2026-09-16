import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path

class BridgeTests(unittest.TestCase):
    def test_input_boundary(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / 'input'
            root.mkdir()
            ((root / 'clip.mp4').resolve()).write_bytes(b'video')
            (Path(d) / 'outside.mp4').write_bytes(b'outside')
            (root / 'escape.mp4').symlink_to(Path(d) / 'outside.mp4')
            sys.modules['folder_paths'] = types.SimpleNamespace(get_input_directory=lambda: str(root))
            sys.modules['comfy'] = types.ModuleType('comfy')
            sys.modules['comfy.model_management'] = types.ModuleType('comfy.model_management')
            sys.modules['comfy_api'] = types.ModuleType('comfy_api')
            sys.modules['comfy_api.latest'] = types.SimpleNamespace(InputImpl=object())
            spec = importlib.util.spec_from_file_location('bridge', Path(__file__).with_name('__init__.py'))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            self.assertEqual(mod.input_file('clip.mp4'), (root / 'clip.mp4').resolve())
            for bad in ['../outside.mp4', 'escape.mp4', 'missing.mp4']:
                with self.assertRaises(ValueError):mod.input_file(bad)

if __name__ == '__main__':unittest.main()
