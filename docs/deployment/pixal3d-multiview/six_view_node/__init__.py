"""Six-face conditioning extension for the installed native Pixal3D multi-view path."""
import math
import torch
from comfy_api.latest import ComfyExtension, IO
import comfy.utils
from comfy_extras.nodes_trellis2 import _build_pixal3d_conditioning
from .cameras import VIEWS, camera_matrices, batch_size_for_views

class Pixal3DSixViewConditioning(IO.ComfyNode):
    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id='Pixal3DSixViewConditioning',
            display_name='Pixal3D Six-View Conditioning / 六视图',
            category='model/conditioning/trellis2',
            inputs=[IO.ClipVision.Input('clip_vision_model'),
                    IO.Float.Input('fov', default=20.0, min=1.0, max=170.0, step=0.01),
                    IO.Image.Input('front', tooltip='Front at -Y; same scale, framing and black background for all views.')]
                   + [IO.Image.Input(name, optional=True, tooltip=(
                       'Top camera at +Z, image up is +Y.' if name == 'top' else
                       'Bottom camera at -Z, image up is -Y.' if name == 'bottom' else
                       'Fixed 90-degree orbit view. Keep the same object scale as the front.'))
                      for name in VIEWS[1:]],
            outputs=[IO.Conditioning.Output(display_name='positive'), IO.Conditioning.Output(display_name='negative')])

    @classmethod
    def execute(cls, clip_vision_model, fov, front, left=None, back=None, right=None, top=None, bottom=None):
        views = dict(front=front, left=left, back=back, right=right, top=top, bottom=bottom)
        names = [n for n in VIEWS if views[n] is not None]
        matrices = camera_matrices(names, fov)
        for n in names:
            v = views[n]
            if v.ndim != 4 or v.shape[-1] not in (3, 4) or min(v.shape[1:3]) < 1:
                raise ValueError(f'{n}: expected a nonempty BHWC RGB/RGBA image')
        batch = batch_size_for_views([views[n].shape[0] for n in names])
        items = []
        for b in range(batch):
            for n in names:
                v = views[n][0 if views[n].shape[0] == 1 else b][None]
                if v.shape[-1] == 4:
                    v = v[..., :3] * v[..., 3:4]
                if v.shape[1:3] != (1024, 1024):
                    v = comfy.utils.common_upscale(v.movedim(-1,1),1024,1024,'lanczos','disabled').movedim(1,-1)
                items.append(v)
        return _build_pixal3d_conditioning(
            clip_vision_model, torch.cat(items, dim=0),
            torch.tensor(matrices, dtype=torch.float32).repeat(batch,1,1),
            torch.full((batch*len(names),), math.radians(fov)),
            torch.ones(batch), num_views=len(names))

class SixViewExtension(ComfyExtension):
    async def get_node_list(self):
        return [Pixal3DSixViewConditioning]

async def comfy_entrypoint():
    return SixViewExtension()
