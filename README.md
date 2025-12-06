# llm-tools-fragment-bridge

Expose LLM fragment loaders as callable tools for AI models.

## Installation

```bash
llm install /opt/llm-tools-fragment-bridge
# Or from GitHub:
llm install git+https://github.com/c0ffee0wl/llm-tools-fragment-bridge
```

## Tools Provided

This plugin exposes the following fragment loaders as tools:

| Tool | Fragment | Description |
|------|----------|-------------|
| `load_yt` | `yt:` | Load YouTube video transcript |
| `load_github` | `github:` | Load files from GitHub repository |
| `load_pdf` | `pdf:` | Extract text from PDF document |

## Requirements

The corresponding fragment plugins must be installed for each tool to work:

- `load_yt` requires `llm-fragments-youtube-transcript`
- `load_github` requires `llm-fragments-github`
- `load_pdf` requires `llm-fragments-pdf`

## Usage

```bash
# Use as a tool in prompts
llm --tool load_yt "https://youtube.com/watch?v=dQw4w9WgXcQ" "Summarize this video"

# Load GitHub repo
llm --tool load_github "simonw/llm" "What does this project do?"

# Extract PDF text
llm --tool load_pdf "/path/to/document.pdf" "Extract the key points"
```

## Why Tools Instead of Fragments?

**Fragments** (`-f`) are one-way: content is injected into the prompt before inference.

**Tools** (`--tool`) are bidirectional: the model can decide when to load content during the conversation. This is useful when:

- The model needs to decide whether to fetch content
- Multiple sources might be relevant and the model should choose
- Content should be loaded conditionally based on conversation context

## Architecture

This plugin wraps the existing fragment loader infrastructure:

```
User: "Summarize this video: https://youtube.com/watch?v=xxx"
  │
  ▼
Model: decides to call load_yt tool
  │
  ▼
load_yt(argument) → llm.get_fragment_loaders()['yt'](argument)
  │
  ▼
Returns: transcript text → Model generates summary
```

## License

GPL-3.0
