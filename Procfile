web: python3 -m jev.cli api --host 0.0.0.0 --port 8777
llama4b: ./third_party/llama.cpp/build/bin/llama-server -m model/base/Qwen3-4B-Q4_K_M.gguf --host 127.0.0.1 --port 8080 -c 2048 -t 2 -fa on --no-webui
llama17b: ./third_party/llama.cpp/build/bin/llama-server -m model/base/Qwen3-1.7B-Q4_K_M.gguf --host 127.0.0.1 --port 8082 -c 2048 -t 2 -fa on --no-webui
embed: ./third_party/llama.cpp/build/bin/llama-server -m model/base/nomic-embed-text-v1.5.Q4_K_M.gguf --host 127.0.0.1 --port 8081 --embedding --pooling mean -c 2048 -t 4 --n-gpu-layers 0
grind_a: LOCAL_TEACHER=1 LOCAL_TEACHER_URL=http://127.0.0.1:8080 LOCAL_TEACHER_MODEL=qwen3-4b URAI_DISTILL_THRESHOLD=0.6 bash scripts/distill/run_free_grind.sh data/raw_tasks/parallel-a distill-now-a
grind_b: LOCAL_TEACHER=1 LOCAL_TEACHER_URL=http://127.0.0.1:8082 LOCAL_TEACHER_MODEL=qwen3-17b URAI_DISTILL_THRESHOLD=0.6 bash scripts/distill/run_free_grind.sh data/raw_tasks/parallel-b distill-now-b
