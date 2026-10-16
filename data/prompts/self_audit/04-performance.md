# Self-audit prompt 04 — performance & cost (run weekly)

Measure, don't guess. Evidence per item:
1. `curl /v1/info` measured throughput — gen tok/s within 4–9? If below 3, find the hog (`top`, competing jobs).
2. Memory: `free -h` available > 1GB with all servers up? Any OOM kills since last audit?
3. GPU spend: any DO droplets tagged urai-train still alive? (`gh run list` for gpu workflows + DO API droplet list — destroy strays, they bill hourly.)
4. Modal/Kaggle: any spend this month vs free credits? (`modal billing summary`.)
5. Context bloat: largest prompt sizes in traces — anything routinely >3000 tokens that should be compacted/summarized?
6. Slow endpoints: any `/agent` calls past 120s? Consider budget cuts or tier downgrade for that task class.

Output: numbers + top offender + one action. No action without a measurement.
