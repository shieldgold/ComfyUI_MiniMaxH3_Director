"""Optional standalone ComfyUI game-asset integration."""
import json
import os
from pathlib import Path

from .runner import VIEWS, atomic_json, create_job, run_job, validate_config


class GameAssetBlenderOptimize:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {
            'model_3d': ('FILE_3D_GLB',),
            'target_faces': ('INT', {'default': 20000, 'min': 1000, 'max': 100000}),
            'texture_size': (['512', '1024', '2048'], {'default': '1024'}),
            'preview_size': (['256', '512'], {'default': '256'}),
        }}

    RETURN_TYPES = ('FILE_3D_GLB', 'STRING', 'STRING', 'IMAGE')
    RETURN_NAMES = ('model_3d', 'report', 'bundle_path', 'six_views')
    FUNCTION = 'optimize'
    CATEGORY = 'Game Assets'
    OUTPUT_NODE = True

    def optimize(self, model_3d, target_faces=20000, texture_size='1024', preview_size='256'):
        import folder_paths
        import comfy.model_management
        from comfy_api.latest import Types
        import numpy as np
        from PIL import Image
        import torch

        settings = validate_config(target_faces, texture_size, preview_size)
        output = Path(folder_paths.get_output_directory()).resolve()
        job = create_job(output)
        atomic_json(job / 'status.json', {'state': 'saving_source'})
        try:
            model_3d.save_to(str(job / 'source.glb'))
        except Exception as error:
            atomic_json(job / 'status.json', {'state': 'failed', 'error': str(error), 'error_type': type(error).__name__})
            raise
        result = run_job(job, **settings, cancel_check=comfy.model_management.throw_exception_if_processing_interrupted)
        views = []
        for view in VIEWS:
            with Image.open(job / 'views' / f'{view}.png') as picture:
                views.append(torch.from_numpy(np.array(picture.convert('RGB'), dtype=np.float32) / 255.0))
        report = json.dumps(json.loads(Path(result['report']).read_text(encoding='utf-8')), ensure_ascii=False, indent=2)
        bundle = str(Path(result['bundle']).relative_to(output))
        images = [
            {'filename': f'{view}.png', 'subfolder': str((job / 'views').relative_to(output)), 'type': 'output'}
            for view in VIEWS
        ]
        return {
            'ui': {'text': [report, bundle], 'images': images},
            'result': (Types.File3D(result['model']), report, bundle, torch.stack(views)),
        }


NODE_CLASS_MAPPINGS = {'GameAssetBlenderOptimize': GameAssetBlenderOptimize} if os.environ.get('GAME_ASSETS_ENABLED') == '1' else {}
NODE_DISPLAY_NAME_MAPPINGS = {'GameAssetBlenderOptimize': 'Game Asset · Blender Optimize'} if NODE_CLASS_MAPPINGS else {}

if NODE_CLASS_MAPPINGS:
    WEB_DIRECTORY = './web'
