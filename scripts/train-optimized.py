#!/usr/bin/env python3
"""
Urai v1.04 optimized training script.
Auto-detects hardware and applies best training strategy.
Runnable standalone: python scripts/train-optimized.py
Also importable: from scripts.train_optimized import detect_hardware, get_optimization_flags
"""

import subprocess
import sys
import os
import re


def detect_hardware():
    """
    Detect available hardware and return a profile dict.

    Returns:
        dict with keys:
            gpu_type (str): "T4", "A10G", "A100", "V100", "consumer", "AMD", "CPU"
            vram_gb (float | None): GPU VRAM in GB, or None if no GPU
            ram_gb (float): System RAM in GB
            recommended_batch_size (int)
            use_flash_attn (bool)
            use_qlora (bool)
            dtype (str): "fp16", "bf16", or "fp32"
    """
    ram_gb = _get_system_ram_gb()

    # --- Try NVIDIA ---
    gpu_type, vram_gb = _detect_nvidia()
    if gpu_type is not None:
        flags = get_optimization_flags({
            "gpu_type": gpu_type,
            "vram_gb": vram_gb,
            "ram_gb": ram_gb,
        })
        return {
            "gpu_type": gpu_type,
            "vram_gb": vram_gb,
            "ram_gb": ram_gb,
            "recommended_batch_size": flags["batch_size"],
            "use_flash_attn": flags["flash_attn"],
            "use_qlora": flags["qlora"],
            "dtype": "bf16" if flags["bf16"] else ("fp16" if flags["fp16"] else "fp32"),
        }

    # --- Try AMD ---
    amd_vram = _detect_amd_vram()
    if amd_vram is not None:
        return {
            "gpu_type": "AMD MI250",
            "vram_gb": amd_vram,
            "ram_gb": ram_gb,
            "recommended_batch_size": 8,
            "use_flash_attn": False,
            "use_qlora": False,
            "dtype": "bf16",
        }

    # --- CPU fallback ---
    print("WARNING: No GPU detected. Training on CPU is very slow (50-100x slower than T4).")
    return {
        "gpu_type": "CPU",
        "vram_gb": None,
        "ram_gb": ram_gb,
        "recommended_batch_size": 1,
        "use_flash_attn": False,
        "use_qlora": True,
        "dtype": "fp32",
    }


def _get_system_ram_gb():
    """Parse /proc/meminfo for total RAM."""
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    return round(kb / 1024 / 1024, 1)
    except Exception:
        pass
    return 0.0


def _detect_nvidia():
    """
    Run nvidia-smi and return (gpu_type_str, vram_gb) or (None, None).
    """
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None, None

        line = result.stdout.strip().splitlines()[0]
        parts = [p.strip() for p in line.split(",")]
        gpu_name = parts[0]
        # memory.total is in MiB, e.g. "16160 MiB"
        vram_mib = float(re.sub(r"[^\d.]", "", parts[1]))
        vram_gb = round(vram_mib / 1024, 1)
        gpu_type = _map_gpu_name(gpu_name, vram_gb)
        return gpu_type, vram_gb

    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        return None, None


def _map_gpu_name(name: str, vram_gb: float) -> str:
    """Map raw GPU name string to canonical type label."""
    n = name.upper()
    if "T4" in n:
        return "T4"
    if "A10G" in n or ("A10" in n and "A100" not in n):
        return "A10G"
    if "A100" in n:
        return "A100"
    if "V100" in n:
        return "V100"
    if "3090" in n or "4090" in n or "3080" in n or "4080" in n:
        return "consumer"
    if "3070" in n or "4070" in n or "3060" in n or "4060" in n:
        return "consumer"
    # Generic NVIDIA — treat as consumer
    return "consumer"


def _detect_amd_vram():
    """Run rocm-smi and return VRAM GB or None."""
    try:
        result = subprocess.run(
            ["rocm-smi", "--showmeminfo", "vram"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return None
        for line in result.stdout.splitlines():
            m = re.search(r"(\d+)\s*MB", line, re.IGNORECASE)
            if m:
                return round(int(m.group(1)) / 1024, 1)
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        pass
    return None


def get_optimization_flags(hw: dict) -> dict:
    """
    Given a hardware profile dict (must have 'gpu_type' and optionally 'vram_gb'),
    return a dict of training optimization flags.

    Returns:
        dict with keys: qlora, flash_attn, bf16, fp16, batch_size, deepspeed
    """
    gpu = hw.get("gpu_type", "CPU")
    vram = hw.get("vram_gb") or 0.0

    if gpu == "T4":
        # T4: 16 GB VRAM, no bf16 support
        return {
            "qlora": True,
            "flash_attn": True,
            "bf16": False,
            "fp16": True,
            "batch_size": 4,
            "deepspeed": False,
        }

    if gpu == "A10G":
        return {
            "qlora": False,
            "flash_attn": True,
            "bf16": True,
            "fp16": False,
            "batch_size": 8,
            "deepspeed": False,
        }

    if gpu == "A100":
        return {
            "qlora": False,
            "flash_attn": True,
            "bf16": True,
            "fp16": False,
            "batch_size": 16,
            "deepspeed": True,
        }

    if gpu == "V100":
        # V100 does not support Flash Attention 2
        return {
            "qlora": True,
            "flash_attn": False,
            "bf16": False,
            "fp16": True,
            "batch_size": 4,
            "deepspeed": False,
        }

    if gpu == "AMD MI250":
        return {
            "qlora": False,
            "flash_attn": False,
            "bf16": True,
            "fp16": False,
            "batch_size": 8,
            "deepspeed": False,
        }

    if gpu == "consumer":
        # Consumer GPUs: differentiate by VRAM
        if vram <= 16.0:
            return {
                "qlora": True,
                "flash_attn": True,
                "bf16": False,
                "fp16": True,
                "batch_size": 4,
                "deepspeed": False,
            }
        else:
            # e.g. RTX 3090 24 GB, RTX 4090 24 GB
            return {
                "qlora": False,
                "flash_attn": True,
                "bf16": True,
                "fp16": False,
                "batch_size": 8,
                "deepspeed": False,
            }

    # CPU only
    print("WARNING: Training on CPU is very slow. Consider using a GPU instance.")
    return {
        "qlora": True,
        "flash_attn": False,
        "bf16": False,
        "fp16": False,
        "batch_size": 1,
        "deepspeed": False,
    }


def build_training_command(flags: dict, config_path: str, output_name: str) -> list:
    """
    Build the CLI argument list for python scripts/train_pipeline.py.

    Args:
        flags: dict from get_optimization_flags()
        config_path: path to the YAML config file
        output_name: value for --output-name

    Returns:
        list of strings suitable for subprocess.run()
    """
    cmd = [
        sys.executable,
        "scripts/train_pipeline.py",
        "--config", config_path,
        "--output-name", output_name,
    ]

    if flags.get("flash_attn"):
        cmd.append("--use-flash-attn")
    if flags.get("qlora"):
        cmd.append("--use-qlora")
    if flags.get("fp16"):
        cmd.append("--fp16")
    if flags.get("bf16"):
        cmd.append("--bf16")
    if flags.get("deepspeed"):
        cmd.extend(["--deepspeed", "configs/deepspeed_zero1.json"])

    # Always apply gradient checkpointing and packing for memory efficiency
    cmd.append("--gradient-checkpointing")
    cmd.append("--packing")

    return cmd


def main():
    dry_run = "--dry-run" in sys.argv

    print("=" * 60)
    print("Urai v1.04 — Hardware-Adaptive Training Optimizer")
    print("=" * 60)

    hw = detect_hardware()

    print(f"\nDetected Hardware:")
    print(f"  GPU type        : {hw['gpu_type']}")
    print(f"  GPU VRAM        : {hw['vram_gb']} GB" if hw['vram_gb'] else "  GPU VRAM        : N/A (CPU)")
    print(f"  System RAM      : {hw['ram_gb']} GB")
    print(f"  Batch size      : {hw['recommended_batch_size']}")
    print(f"  Flash Attention : {hw['use_flash_attn']}")
    print(f"  QLoRA           : {hw['use_qlora']}")
    print(f"  dtype           : {hw['dtype']}")

    flags = get_optimization_flags(hw)

    config_path = os.environ.get("URAI_CONFIG", "configs/distill_qwen3_4b.yaml")
    output_name = os.environ.get("URAI_OUTPUT_NAME", "urai-v1.04")

    cmd = build_training_command(flags, config_path, output_name)

    print(f"\nTraining command:")
    print("  " + " ".join(cmd))
    print()

    if dry_run:
        print("[--dry-run] Skipping execution.")
        sys.exit(0)

    print("Launching training...")
    result = subprocess.run(cmd)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
