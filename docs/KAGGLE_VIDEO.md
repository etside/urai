# WAN 2.1 Video Generation on Kaggle (Free T4 GPU)

Run open-source WAN 2.1 (Apache 2.0) video generation on Kaggle's free T4 GPU.
No paid APIs. Generates real motion video, not an animatic slideshow.

## Quick Start (10 minutes)

### 1. Create Kaggle Notebook
- Go to [kaggle.com](https://kaggle.com) → **Create** → **New Notebook**
- Settings → **Accelerator: GPU T4 x2** ✓
- Settings → **Internet: ON** ✓

### 2. Upload the kernel script
Add a code cell and run:
```python
!curl -sLO https://raw.githubusercontent.com/holidaysrambler/urai/main/kaggle/wan21_video_gen.py
```
Or upload `kaggle/wan21_video_gen.py` from this repo as an input file.

### 3. Set your prompt and run
```python
import os
os.environ["URAI_VIDEO_PROMPT"] = "A sunset over mountains, cinematic tracking shot"
os.environ["URAI_VIDEO_DURATION"] = "5"
os.environ["URAI_WAN_MODEL"] = "1.3B"  # fits T4; use 14B on A100

# Optional: push result directly back to your Urai server
os.environ["URAI_API_URL"] = "https://your-urai-server:8777"
os.environ["URAI_API_KEY"] = "your-urai-key"

exec(open("wan21_video_gen.py").read())
```

### 4. Download the output
- Output video: `/kaggle/working/output.mp4`
- Download from Kaggle output panel

### 5. Add to Urai
If not auto-pushed, manually ingest:
```bash
# Base64 encode and push
B64=$(base64 -w0 output.mp4)
curl -X POST http://localhost:8777/v1/videos/ingest \
  -H "Content-Type: application/json" \
  -d "{\"video_b64\": \"$B64\", \"prompt\": \"your prompt\", \"backend\": \"wan21\"}"
```

## Model Sizes

| Model | VRAM | Quality | Kaggle GPU |
|-------|------|---------|------------|
| 1.3B | ~6GB | Good | T4 ✓ |
| 14B | ~28GB | Best | A100 (paid) |

**Recommendation**: Use 1.3B for drafts (free T4), 14B for finals (Kaggle's paid A100 tier or future Urai GPU VPS).

## Automation: Kaggle API

You can trigger Kaggle notebooks via API for batch video gen:
```bash
# Install Kaggle CLI
pip install kaggle

# Configure credentials (~/.kaggle/kaggle.json)
# Push notebook and run via API
kaggle kernels push -p your-notebook-dir
kaggle kernels status your-username/wan21-video-gen
```

## Upcoming: Urai GPU VPS

Once a GPU VPS is available, WAN 2.1 will run directly in Urai with no Kaggle step needed:
```bash
urai model download wan2.1  # downloads ~3GB (1.3B) or ~28GB (14B)
urai serve start             # auto-detects WAN 2.1 for video gen
```

## Sources
- WAN 2.1: https://github.com/Wan-Video/Wan2.1 (Apache 2.0)
- HuggingFace: https://huggingface.co/Wan-AI/Wan2.1-T2V-1.3B-Diffusers
