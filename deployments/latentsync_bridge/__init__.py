"""Local LatentSync bridge; installed only on explicitly selected instances."""
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import folder_paths
import comfy.model_management as mm
from comfy_api.latest import InputImpl


def input_file(name):
    root = Path(folder_paths.get_input_directory()).resolve()
    path = (root / name).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('Select an existing file in the instance input directory')
    return path


def choices(suffixes):
    root = Path(folder_paths.get_input_directory())
    return sorted(str(p.relative_to(root)) for p in root.rglob('*')
                  if p.is_file() and p.suffix.lower() in suffixes)


class LocalLatentSync:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {
            'video': (choices({'.mp4', '.mov', '.webm', '.mkv'}),),
            'audio': (choices({'.wav', '.mp3', '.m4a', '.flac', '.mp4'}),),
            'steps': ('INT', {'default': 20, 'min': 1, 'max': 100}),
            'guidance': ('FLOAT', {'default': 1.5, 'min': 1.0, 'max': 3.0, 'step': 0.1}),
            'seed': ('INT', {'default': 1247, 'min': 0, 'max': 2147483647}),
        }}

    RETURN_TYPES = ('VIDEO', 'STRING')
    RETURN_NAMES = ('video', 'output_path')
    FUNCTION = 'run'
    CATEGORY = 'video/LatentSync'
    DESCRIPTION = 'Local LatentSync 1.6, same GPU as this instance. Output is 25fps. Uses existing /opt/latentsync runtime.'

    def run(self, video, audio, steps, guidance, seed):
        src, snd = input_file(video), input_file(audio)
        token = uuid.uuid4().hex
        work = Path(folder_paths.get_temp_directory()) / ('latentsync_' + token)
        work.mkdir(parents=True)
        out = Path(folder_paths.get_output_directory()) / 'LatentSync'
        out.mkdir(parents=True, exist_ok=True)
        result = out / (token + '.mp4')
        # Fixed safe names also protect the upstream ffmpeg shell invocation.
        shutil.copyfile(src, work / ('source' + src.suffix.lower()))
        subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-y', '-i', str(snd),
                        '-vn', '-ar', '16000', '-ac', '1', str(work / 'audio.wav')], check=True)
        mm.unload_all_models()
        mm.soft_empty_cache()
        env = os.environ.copy()
        env.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                   LATENTSYNC_VAE_PATH='/model/latentsync-1.6/checkpoints/sd-vae-ft-mse',
                   PYTHONUNBUFFERED='1', LATENTSYNC_TMP_DIR=str(work / 'decode'),
                   MPLCONFIGDIR=str(work / 'matplotlib'))
        libs = sorted(Path('/opt/latentsync/venv/lib/python3.10/site-packages/nvidia').glob('*/lib'))
        env['LD_LIBRARY_PATH'] = ':'.join(map(str, libs)) + ':' + env.get('LD_LIBRARY_PATH', '')
        cmd = ['/opt/latentsync/venv/bin/python', '-m', 'scripts.inference',
               '--unet_config_path', 'configs/unet/stage2_512.yaml',
               '--inference_ckpt_path', 'checkpoints/latentsync_unet.pt',
               '--video_path', str(work / ('source' + src.suffix.lower())),
               '--audio_path', str(work / 'audio.wav'), '--video_out_path', str(result),
               '--temp_dir', str(work / 'inference'), '--inference_steps', str(steps),
               '--guidance_scale', str(guidance), '--seed', str(seed)]
        with (work / 'inference.log').open('w') as log:
            proc = subprocess.Popen(cmd, cwd='/opt/latentsync/app', env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                while True:
                    try:
                        code = proc.wait(timeout=1)
                        break
                    except subprocess.TimeoutExpired:
                        mm.throw_exception_if_processing_interrupted()
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
        if code or not result.is_file():
            raise RuntimeError(f'LatentSync failed; see {work / "inference.log"}')
        return (InputImpl.VideoFromFile(str(result)), str(result))


NODE_CLASS_MAPPINGS = {'LocalLatentSync': LocalLatentSync}
NODE_DISPLAY_NAME_MAPPINGS = {'LocalLatentSync': 'LatentSync 1.6 本地口型同步'}
