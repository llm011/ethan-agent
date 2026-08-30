# CosyVoice 环境准备（一次性，Mac M 系列验证通过）

audio_pipeline.py 的 `engine: "cosyvoice"` 路径需要独立 venv（重依赖不进主环境）。

## 1. 装依赖

```bash
uv venv --python 3.11 ~/.ethan/cosyvoice-venv
uv pip install --python ~/.ethan/cosyvoice-venv/bin/python torch torchaudio setuptools wheel
git clone --depth 1 https://github.com/FunAudioLLM/CosyVoice.git ~/.ethan/CosyVoice
uv pip install --python ~/.ethan/cosyvoice-venv/bin/python --no-build-isolation \\
  "conformer==0.3.2" "HyperPyYAML==1.2.3" "wetext==0.0.4" "x-transformers==2.11.24" "inflect==7.3.1"
uv pip install --python ~/.ethan/cosyvoice-venv/bin/python \\
  "diffusers==0.29.0" "hydra-core==1.3.2" "librosa==0.10.2" "modelscope>=1.20" \\
  "omegaconf==2.3.0" "onnxruntime>=1.19" "protobuf==4.25" "pydantic==2.7.0" \\
  "soundfile==0.12.1" "transformers==4.51.3" gdown "openai-whisper==20231117" numpy==1.26.4
```

坑：PyPI 的 `cosyvoice` 包是空壳（无 cli 模块），必须用官方仓库；`onnxruntime==1.18.0` 在新 macOS import 失败，用 >=1.19；非 CUDA 环境官方代码自动降级 fp32/CPU，M1 Pro 32GB 实测可用（CPU 推理，RTF 约 1–2x 实时）。

## 2. 下载模型（约 5GB）

```bash
cd ~/.ethan/CosyVoice && ~/.ethan/cosyvoice-venv/bin/python -c "
from modelscope import snapshot_download
snapshot_download('iic/CosyVoice2-0.5B', local_dir='pretrained_models/CosyVoice2-0.5B')"
```

## 3. 验证

```bash
~/.ethan/cosyvoice-venv/bin/python -c "
import sys; sys.path.insert(0, '$HOME/.ethan/CosyVoice')
from cosyvoice.cli.cosyvoice import AutoModel
m = AutoModel(model_dir='$HOME/.ethan/CosyVoice/pretrained_models/CosyVoice2-0.5B')
print(m.list_available_spks())"
```

预置音色名以输出为准（常见：英文女/英文男/中文女等）。非默认 venv 路径用 `COSYVOICE_PYTHON` 环境变量覆盖解释器。

## 性能对比（M1 Pro 32GB，CPU）

- edge-tts：免费、快（RTF≈0.3x），但情感平淡
- CosyVoice2：本地、无网络依赖、情感/韵律显著更好，10 分钟音频合成约 10–20 分钟（句级缓存后重跑极快）
