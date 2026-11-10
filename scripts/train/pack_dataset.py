#!/usr/bin/env python3
"""Pack Urai's training data for a free-GPU session (Kaggle/Colab).

Kaggle GPU sessions may run without internet, so everything the notebook
needs (besides pip-installable Unsloth) goes into one tarball you upload
once as a Kaggle Dataset (or Colab file):

    python3 scripts/train/pack_dataset.py \
        --inputs data/verified/distill-v0.2.jsonl data/raw_tasks/sample_tasks.jsonl \
        --out /tmp/urai-train-data.tar.gz

Then: Kaggle -> Add Input -> Upload Dataset (the tarball), notebook reads
/kaggle/input/*/distill-v0.2.jsonl automatically. Colab: upload the .jsonl
directly. See notebooks/train_urai_qlora.ipynb + docs/TRAINING.md.
"""

import argparse
import json
import tarfile
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inputs", nargs="+", required=True)
    ap.add_argument("--out", default="/tmp/urai-train-data.tar.gz")
    args = ap.parse_args()

    total = 0
    with tarfile.open(args.out, "w:gz") as tar:
        for f in args.inputs:
            p = Path(f)
            if not p.exists():
                print(f"SKIP missing: {f}")
                continue
            n = sum(1 for _ in open(p) if _.strip())
            total += n
            tar.add(str(p), arcname=p.name)
            print(f"+ {p.name} ({n} records)")
    # manifest for the notebook
    manifest = {"files": [Path(f).name for f in args.inputs
                          if Path(f).exists()],
                "records": total,
                "expects": "notebooks/train_urai_qlora.ipynb"}
    print(json.dumps(manifest, indent=1))
    print(f"packed -> {args.out}")


if __name__ == "__main__":
    main()
