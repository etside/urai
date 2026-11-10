# Kaggle T4 free GPU — run tonight (~30 free GPU-hours/week)

No CLI keys needed on your side. 5 steps, ~10 minutes of your time:

1. Go to kaggle.com → Create → Notebook. Turn **GPU T4 x2** ON, **Internet** ON.
2. **Add input → Upload** `data/verified/distill-now.jsonl`
   (download it from this repo, or ask — current file has 76 rows).
3. First cell, install + fetch the trainer:
   ```
   !pip install -q unsloth trl peft accelerate bitsandbytes datasets
   !curl -sLO https://raw.githubusercontent.com/etside/urai/main/kaggle/train_qlora.py
   ```
   (Repo is private → instead upload `kaggle/train_qlora.py` from this repo
   as a second input, or paste its contents into a cell.)
4. Run: `!python3 train_qlora.py` (set `MAX_TRAIN_STEPS=300` env for ~1h).
5. Download `/kaggle/working/urai-adapter` → send the folder back.
   Next here: merge → GGUF export → bench gate (no regression or DISCARD).

Why Kaggle and not DO: this DO account has **GPU limit 0**
(proven: `DO-REJECTED: creating this/these droplet(s) will exceed your GPU limit`).
A limit increase needs a support ticket; Kaggle works today at $0.
