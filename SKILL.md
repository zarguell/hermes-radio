---
name: hermes-radio
description: >
  Generate a daily Hermes Radio broadcast with LLM-enhanced segments.
  Collects zero-token data, processes LLM segments, assembles audio or text.
---

# Hermes Radio

This skill orchestrates the Hermes Radio broadcast in **hybrid mode** — where some
segments are zero-token (SearXNG, content banks) and others are LLM-generated.

For pure zero-token mode (all `source: searxng` / `source: bank`), use the
broadcast script directly with `no_agent: true` instead — no skill needed.

## Workflow

You are tasked with producing today's broadcast. Follow these steps in order.

### 1. Collect zero-token data

Run the broadcast script in collect mode:

```bash
cd /opt/data/hermes-radio && python3 broadcast.py --step collect
```

This outputs a JSON object with:
- `ctx` — all zero-token data (headlines, bank picks, etc.) plus empty placeholders
  for LLM segments
- `llm_needed` — array of LLM segments that need your reasoning

Save this output to a temporary file for further processing.

### 2. Process LLM segments

For each item in `llm_needed`:

```json
{
  "id": "segment_name",
  "prompt": "The instruction with context filled in...",
  "model_hint": "suggested-model",
  "output": null
}
```

- Read the `prompt` field carefully — it includes the context data
- Use your own reasoning to generate the segment content (you are the LLM)
- Update `output` with your generated text
- Also update `ctx["segment_name"]` with the same value

### 3. Build the final broadcast

Save the completed context JSON to a file (e.g. `/tmp/hermes-radio-ctx.json`),
then run:

```bash
cd /opt/data/hermes-radio && python3 broadcast.py --step build /tmp/hermes-radio-ctx.json
```

The output will include:
- A Telegram-formatted caption
- `MEDIA:/path/to/broadcast.mp3` (in audio mode) — Hermes delivers this as native audio

## Notes

- **Prompt variables**: `{n_headlines}`, `{headlines_str}`, `{month}`, `{year}`,
  and any earlier segment's output are available in LLM prompts.
- **Model hint**: The `model_hint` field is advisory — use the best model available to you.
- **Content banks**: Tips, jokes, and quotes are rotated daily via content_banks/*.txt.
  Do not modify the bank files — they are deterministic per day.
- **Music segment**: Found via SearXNG video search. May return sports highlights
  or unrelated content — use discretion when referencing it.

## Cron Job Setup

```yaml
# Hybrid mode (LLM segments enabled):
schedule: "0 11 * * *"   # 7 AM EDT
skills: ["hermes-radio"]
prompt: "Follow the hermes-radio skill instructions to produce today's broadcast."
workdir: /opt/data/hermes-radio
```

## Templates

The broadcast uses two Jinja2 templates in `templates/`:

- `tts_script.txt.j2` — spoken narration (TTS input)
- `telegram.md.j2` — Telegram caption

Edit these to reorder segments, change wording, or add new sections.
