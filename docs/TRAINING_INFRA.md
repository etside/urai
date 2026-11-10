# Urai Training Infrastructure

## Modal (cloud GPU training)
- Profile: kptjms991 (~/.modal.toml)
- Tokens: MODAL_TOKEN_ID + MODAL_TOKEN_SECRET stored as gh repo secrets
- Workflow: .github/workflows/urai-modal-train.yml
- Status: working

## Kaggle (free GPU training)
- Notebook: urai_kaggle_setup.txt (5 cells, paste into Kaggle Notebook)
- Kernel script: urai-train-qlora.py (self-contained, run as kernel)
- Hardware: GPU T4 x2 (Kaggle free tier)
- Base model: Qwen3-0.6B-bnb-4bit (kaggle setup) or Qwen3-4B-bnb-4bit (qlora script)
- Training: QLoRA r=16, alpha=16, 4-bit, adamw_8bit, gradient checkpointing
- Steps: 300 (qlora.py) or 1 epoch (kaggle setup)
- Output: adapter at /kaggle/working/urai-adapter
- Export: GGUF Q4_K_M via Unsloth save_pretrained_gguf

## Dataset
- File: urai-distill-now.jsonl (~200+ rows)
- Source: data/verified/distill-now.jsonl in repo
- Categories: code-gen, code-repair, reasoning, security, api-engineering, agentic, debugging, repo-reasoning, tool-use
- Teachers: mock-v1, qwen3-17b, qwen3-4b, local-student
- Pipeline: distill-v0.1
- Kaggle dataset: sherikhtj/urai-distill-v0-2

## Training flow
1. Generate distill data: `urai distill` (uses teacher API or mock)
2. Verify/filter: scripts/distill/verifier.py (compile + JSON + exec checks)
3. Upload to Kaggle dataset or use locally
4. Run QLoRA training (Kaggle free tier or Modal cloud GPU)
5. Export GGUF Q4_K_M
6. Download GGUF, place in model/base/
7. Update registry: `urai model add`
8. Benchmark: `urai model bench`
9. Gate: must beat previous model on suite to activate
