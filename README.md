# Hermes Radio 📻

**Zero-LLM daily broadcast engine** — generates an audio show or text briefing from live web data using only API calls, templates, and TTS. No tokens burned on AI summarization.

Inspired by [u/amaksimchuk's Hermes Radio](https://www.reddit.com/r/hermesagent/comments/1tpms69/what_cron_jobs_do_you_run_with_hermes_agent_heres/) on r/hermesagent.

## Features

- **Zero LLM tokens** — all content is pulled from APIs (SearXNG, GitHub) and rotated content banks. No AI calls.
- **Dual mode** — audio broadcast (TTS + FFmpeg → MP3) or text-only briefing from the same pipeline.
- **Jinja templated** — every broadcast's narration script and Telegram caption come from editable `.j2` templates. Reorder segments, change the voice's script, add sections — no code changes needed.
- **Pluggable content banks** — tips, jokes, quotes rotate daily via simple text files. Add your own.
- **Self-hosted** — uses your own SearXNG instance, edge-tts for speech, FFmpeg for assembly. No external APIs needed.
- **Hermes Agent cron ready** — designed for `no_agent: true` delivery with `MEDIA:` output.

## Quick Start

### Dependencies

- Python 3.11+
- [FFmpeg](https://ffmpeg.org/) — audio assembly
- [edge-tts](https://github.com/rany2/edge-tts) — text-to-speech
- [SearXNG](https://docs.searxng.org/) — web search (self-hosted)
- Jinja2, PyYAML — Python packages

```bash
# Install Python deps
pip install jinja2 pyyaml

# Install edge-tts
pip install edge-tts

# Install ffmpeg
# macOS: brew install ffmpeg
# Ubuntu/Debian: sudo apt install ffmpeg
```

### Setup

```bash
# Clone the repo
git clone https://github.com/zarguell/hermes-radio.git
cd hermes-radio

# Copy and customize config
cp config.example.yaml config.yaml
# Edit config.yaml with your SearXNG URL, voice preference, etc.

# Run audio mode (default)
python3 broadcast.py

# Run text-only mode
python3 broadcast.py --mode text
```

## Configuration

See [`config.example.yaml`](config.example.yaml) for all options with documentation.

| Key | Default | Description |
|-----|---------|-------------|
| `mode` | `audio` | `audio` or `text` |
| `searxng.base_url` | `http://localhost:8888` | Your SearXNG instance |
| `tts.voice` | `en-US-ChristopherNeural` | edge-tts voice name |
| `output.directory` | `./output` | Where MP3s are saved |
| `output.cleanup_days` | `7` | Auto-delete old broadcasts |
| `headlines.enabled` | `true` | Fetch AI headlines |
| `headlines.max_results` | `4` | Number of headlines |
| `music.enabled` | `true` | Find trending music |
| `content.banks.*` | file paths | Rotating content sources |

## Templates

The engine uses two Jinja2 templates:

### `templates/tts_script.txt.j2`
The narration script — what the voice reads. Default flow: Intro → Headlines → Tip → Quote → Music → Joke → Outro.

Edit this to reorder segments, change what the voice says, or add custom sections. Available variables: `date`, `headlines` (list), `tip`, `joke`, `quote`, `music` (string).

### `templates/telegram.md.j2`
The Telegram caption — text that accompanies the audio file (or the standalone text in text mode). Supports Telegram markdown. Same variables plus `duration` and `mode`.

## Content Banks

Text files in `content_banks/`, one item per line. `#` comments are ignored. Each day picks one item via deterministic day-of-year rotation.

- `tips.txt` — tech/sysadmin tips
- `jokes.txt` — tech/AI humor
- `quotes.txt` — engineering wisdom

Add your own files and reference them in `config.yaml` under `content.banks`.

## Dual Mode

The same engine powers both output formats:

- **Audio mode** (`mode: audio`): Renders the TTS template → generates speech with edge-tts → assembles with FFmpeg → outputs caption + `MEDIA:` path for Telegram
- **Text mode** (`mode: text`): Renders the Telegram template directly → outputs plain text — no TTS, no FFmpeg

Use `python3 broadcast.py --mode text` to override.

## Hermes Agent Cron Integration

```yaml
# In your Hermes Agent config or via the cron tool:
# Schedule: daily at 7:00 AM
# Script: /path/to/hermes-radio/broadcast.py
# no_agent: true — the script's stdout is delivered directly
```

The script outputs:
1. A Telegram-formatted caption with **bold** headlines, tips, etc.
2. A `MEDIA:/path/to/broadcast.mp3` line that Hermes delivers as native audio

Set `cleanup_days: 7` in config to auto-remove old broadcasts.

## Architecture

```
broadcast.py              # Engine: config → data → templates → output
├── config.yaml           # All configuration
├── templates/
│   ├── tts_script.txt.j2 # What the voice reads
│   └── telegram.md.j2    # Telegram text caption
├── content_banks/        # Rotating content
│   ├── tips.txt
│   ├── jokes.txt
│   └── quotes.txt
└── output/               # Generated MP3s
```

Data flow:
1. `collect_data()` fetches headlines + music from SearXNG, picks daily items from content banks
2. Jinja2 renders templates with the data
3. (Audio mode only) edge-tts generates speech → FFmpeg assembles MP3
4. Engine prints caption + `MEDIA:` path for Hermes cron delivery

## License

MIT
