# Urai × Google Colab CLI — on-demand GPU/TPU

This box has **no local GPU**. The official
[google-colab-cli](https://github.com/googlecolab/google-colab-cli) gives Urai
on-demand CPU / GPU (T4, L4, G4, A100, H100) / TPU (v5e1, v6e1) runtimes from
the terminal, with ephemeral jobs that tear themselves down.

## 1. Installed here

```bash
# isolated install (does not touch Urai's pinned core env)
python3 -m venv /root/.venvs/colab-cli
/root/.venvs/colab-cli/bin/pip install google-colab-cli==0.8.0
# launcher: /usr/local/bin/colab  (or /root/bin/colab) -> venv bin/colab

colab --version
```

Platform support is Linux/macOS only (this box is Linux aarch64, Python 3.12 —
supported). Session state lives in `~/.config/colab-cli/sessions.json`;
global settings in `~/.config/colab-cli/settings.json`.

## 2. One-time authentication (user action)

The CLI authenticates with Google OAuth2 by default. Run any command that
needs a runtime (`colab new`, `colab usage`) in a browser-capable session and
complete the Google sign-in. For headless/service use, Application Default
Credentials are supported:

```bash
gcloud auth application-default login \
  --scopes=openid,https://www.googleapis.com/auth/cloud-platform,\
https://www.googleapis.com/auth/userinfo.email,\
https://www.googleapis.com/auth/colaboratory
colab --auth adc usage
```

On first run the CLI prints a Google consent URL, then asks you to paste the
authorization code back into the terminal — run it interactively, not through
a pipe. If it warns that no OS keyring backend is available, either install one
(`pip install keyrings.alt` in the colab venv) or switch to ADC
(`colab --auth adc ...`).

**No Google/Colab credential is stored in Urai.** Never paste account tokens
into a notebook, a dataset, or git.

## 2b. Multiple Google accounts (auth routing)

`urai-router` owns credential routing. Each Colab account is a profile with its
**own HOME and keyring**, so switching accounts never overwrites another
token:

```bash
urai auth status                          # profiles per service
urai auth use colab                       # selected profile (JSON)
urai-router auth launch colab-oauth-2     # opens Google sign-in in the browser
                                          # for a second account, then prompts
                                          # for the code (or use --code CODE)
urai-router auth switch colab-oauth-2     # pin that account as active
```

Profiles: `colab-oauth` (default), `colab-oauth-2/3/4` (isolated under
`~/.urai/colab-profiles/`), `colab-adc` (headless ADC). The count of extra
profiles is controlled by `URAI_COLAB_PROFILES` (default 4 total). When a
service has no usable credential, `urai auth use <service>` returns
`next_profile` and `launch_hint` so the caller knows exactly which browser
auth to launch. An explicitly requested `--preferred` profile that is not
authenticated is reported as unavailable — Urai never silently substitutes a
different identity.

## 3. Command cheat sheet

```bash
colab new -s urai-train --gpu T4        # provision (T4 | L4 | G4 | A100 | H100)
colab sessions                          # active sessions
colab status -s urai-train              # hardware + machine shape
colab install -s urai-train unsloth trl peft bitsandbytes datasets
colab exec -s urai-train -f kaggle/train_qlora.py
colab upload -s urai-train data/verified/distill-now.jsonl /content/distill.jsonl
colab download -s urai-train /content/urai-adapter ./urai-adapter
colab stop -s urai-train                # release the VM
colab usage                             # compute-unit balance/rate
colab update --install                  # upgrade the CLI
```

Ephemeral form — provision, run a local script, retrieve output, tear down in
one command:

```bash
colab run --gpu T4 train.py -- --steps 300
```

## 4. Urai training on Colab (same script as Kaggle)

`kaggle/train_qlora.py` now honours two env overrides so the same Unsloth
QLoRA code works on Kaggle **and** Colab:

| Env | Default (Kaggle) | Colab value |
|---|---|---|
| `URAI_TRAIN_DATA_GLOB` | `/kaggle/input/**/*.jsonl` | `/content/**/*.jsonl` |
| `URAI_ADAPTER_OUT` | `/kaggle/working/urai-adapter` | `/content/urai-adapter` |

```bash
# 1. version the dataset locally (DeepLake optional but recommended)
urai deeplake dataset-import data/verified/distill-now.jsonl

# 2. provision + run
colab new -s urai-train --gpu T4
colab upload -s urai-train data/verified/distill-now.jsonl /content/distill.jsonl
colab install -s urai-train unsloth trl peft accelerate bitsandbytes datasets transformers
colab exec -s urai-train -f kaggle/train_qlora.py \
  # set URAI_TRAIN_DATA_GLOB/URAI_ADAPTER_OUT via the notebook env before exec
colab download -s urai-train /content/urai-adapter ./urai-adapter
colab stop -s urai-train

# 3. finish locally: merge -> GGUF export -> bench gate (docs/TRAINING.md)
```

`colab exec -f` transmits the file content to the remote kernel — no manual
upload needed for the script itself. `--gpu A100`, `--high-mem` and L4 shapes
may require a Colab Pro/Pro+ entitlement.

## 5. Honest limits

- OAuth sign-in needs the user; the CLI cannot allocate a GPU anonymously.
- Free-tier GPU availability and quotas are controlled by Google, not Urai.
- Ephemeral VMs lose local state at teardown — always `colab download` the
  adapter/checkpoints before `colab stop`, or mount Drive (`colab drivemount`).
- This is remote execution of local code: treat the script and its data as
  leaving this machine. Keep secrets out of both.
- Urai never auto-starts a paid runtime; every `colab` invocation is explicit.

## 6. Urai wrapper (optional)

`jev/colab_gpu.py` + `urai colab status|new|run|exec|upload|download|stop|usage`
wrap the CLI with argument lists (no `shell=True`), timeouts, JSON output and
honest `available:false` when `colab` is not on PATH. The wrapper does not
store credentials or expose raw shell lines.
