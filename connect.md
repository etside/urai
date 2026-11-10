# Connect to Urai

## API (OpenAI-compatible)
Base URL: http://52.66.18.45:8777/v1
API Key: urai_e3sbJn3XztLzDS3nahrJPnYKdbDRiRpY

## Python

```python
from openai import OpenAI
client = OpenAI(base_url="http://52.66.18.45:8777/v1", api_key="urai_e3sbJn3XztLzDS3nahrJPnYKdbDRiRpY")
response = client.chat.completions.create(model="urai", messages=[{"role":"user","content":"hello"}])
print(response.choices[0].message.content)
```

## CLI

```bash
curl -fsSL https://raw.githubusercontent.com/etside/urai/main/install.sh | bash
urai login urai_e3sbJn3XztLzDS3nahrJPnYKdbDRiRpY --url http://52.66.18.45:8777
urai ask "hello"
urai tui
```

## Web Studio
https://etside.github.io/urai/ or http://52.66.18.45:8777/app

## Ollama

```bash
ollama run urai  # after: ollama create urai -f Modelfile
```
