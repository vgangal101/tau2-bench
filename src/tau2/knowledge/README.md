# Knowledge Retrieval

Domains with a knowledge base (currently just `banking-knowledge`) require a `--retrieval-config` flag that controls how the agent accesses the knowledge base.

```bash
tau2 run --domain banking_knowledge --retrieval-config <config_name> --agent-llm gpt-4.1 --user-llm gpt-4.1
```

## Retrieval Configs

| Config | Tools | Description |
|--------|-------|-------------|
| `no_knowledge` | None | Agent has no access to the knowledge base |
| `full_kb` | None | Entire knowledge base injected into the system prompt |
| `golden_retrieval` | None | Only task-required documents injected into context |
| `grep_only` | `grep` | Regex pattern search over documents |
| `bm25` | `KB_search` | BM25 keyword retrieval |
| `openai_embeddings` | `KB_search` | OpenAI `text-embedding-3-large` (requires `OPENAI_API_KEY`) |
| `qwen_embeddings` | `KB_search` | Qwen `qwen3-embedding-8b` via OpenRouter (requires `OPENROUTER_API_KEY`) |
| `terminal_use` | `shell` | Agent explores KB files via shell commands in a sandbox |
| `terminal_use_write` | `shell` | Same as `terminal_use` but with write access |

The `bm25`, `openai_embeddings`, and `qwen_embeddings` configs can also be combined with a `_reranker` suffix (adds an LLM reranker postprocessor), a `_grep` suffix (adds a `grep` tool), or both (e.g. `openai_embeddings_reranker_grep`).

## Additional Setup

### OpenRouter API Key

The `qwen_embeddings*` configs route through [OpenRouter](https://openrouter.ai/). Set the `OPENROUTER_API_KEY` environment variable (or add it to your `.env` file).

### sandbox-runtime

The `terminal_use` and `terminal_use_write` configs require [Anthropic's sandbox-runtime](https://github.com/anthropic-experimental/sandbox-runtime) for secure filesystem isolation:

```bash
npm install -g @anthropic-ai/sandbox-runtime@0.0.23
```

**macOS**: Also requires `ripgrep`:
```bash
brew install ripgrep
```

**Linux**: Also requires `ripgrep`, `bubblewrap`, and `socat`:
```bash
# Ubuntu/Debian
sudo apt-get install ripgrep bubblewrap socat
```
