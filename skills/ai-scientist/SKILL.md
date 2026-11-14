---
name: ai-scientist
description: "Autonomous scientific research loop from SakanaAI AI-Scientist. Generates research ideas, runs experiments, analyzes results, writes papers, and peer-reviews them. Use for ML research, hypothesis testing, data analysis, and automated experimentation."
source: https://github.com/SakanaAI/AI-Scientist
---

# AI Scientist (Urai)

Urai can run an autonomous research loop inspired by SakanaAI's AI-Scientist.

## Capabilities

- **Idea generation**: generate novel research hypotheses from a topic
- **Literature review**: search and summarize relevant papers
- **Experiment design**: write and run experiments (code execution)
- **Result analysis**: parse outputs, generate plots, draw conclusions
- **Paper writing**: produce a structured research writeup
- **Peer review**: self-critique and improve the paper

## Usage

```bash
# Start a research project
urai agent "conduct research on: does in-context learning improve with longer prompts for math tasks"

# With specific template
urai research --topic "effect of quantization on reasoning quality" --template nanoGPT
```

## Research Loop

```
1. Generate 5-10 research ideas on the topic
2. Score ideas by novelty, feasibility, impact
3. Pick the top idea
4. Write experiment code
5. Run experiments (code_run tool)
6. Analyze results
7. Generate figures
8. Write paper sections (abstract, intro, methods, results, conclusion)
9. Self-review and improve
10. Output final PDF or markdown
```

## Templates Available

- `nanoGPT` — language model training experiments
- `nanoGPT_lite` — faster lightweight version
- Custom: provide your own experiment template

## Output

Results saved to `data/research/<timestamp>/`:
- `paper.md` — full paper
- `figures/` — generated plots
- `experiments/` — code and logs
- `review.md` — self-review

## Notes

- Requires llama-server or cloud backend for generation
- Experiment runs use the sandbox code executor
- Scientific integrity: Urai does not fabricate data or results
