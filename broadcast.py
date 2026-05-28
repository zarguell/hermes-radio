#!/usr/bin/env python3
"""
Hermes Radio — Zero-LLM Daily Broadcast Engine

Dual-mode engine: generates either an audio broadcast (TTS + FFmpeg → MP3)
or a plain-text briefing from the same data sources. All config lives in
config.yaml; all presentation lives in Jinja2 templates.

Inspired by u/amaksimchuk's Hermes Radio (r/hermesagent).
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape


# ═══════════════════════════════════════════════════════════════
# CONFIG LOADING
# ═══════════════════════════════════════════════════════════════

def load_config(path: Path) -> dict:
    """Load and validate YAML config."""
    if not path.exists():
        print(f"[error] Config not found: {path}", file=sys.stderr)
        print(f"[info]  Copy config.example.yaml to config.yaml and customize it.", file=sys.stderr)
        sys.exit(1)
    with open(path) as f:
        cfg = yaml.safe_load(f)
    cfg["_config_dir"] = path.resolve().parent
    cfg.setdefault("mode", "audio")
    cfg.setdefault("templates_dir", "templates")
    cfg.setdefault("content", {}).setdefault("banks", {})
    cfg.setdefault("output", {}).setdefault("directory", "output")
    cfg.setdefault("output", {}).setdefault("cleanup_days", 7)
    cfg.setdefault("searxng", {}).setdefault("timeout", 15)
    cfg.setdefault("headlines", {}).setdefault("enabled", True)
    cfg.setdefault("headlines", {}).setdefault("max_results", 4)
    cfg.setdefault("music", {}).setdefault("enabled", True)
    cfg.setdefault("music", {}).setdefault("max_results", 1)
    cfg.setdefault("tts", {}).setdefault("voice", "en-US-ChristopherNeural")
    return cfg


# ═══════════════════════════════════════════════════════════════
# CONTENT BANKS
# ═══════════════════════════════════════════════════════════════

def load_bank(path: Path) -> list[str]:
    """Load content bank: one item per line, blank/comment lines ignored."""
    if not path.exists():
        return []
    items = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                items.append(line)
    return items


def pick_today(bank: list[str]) -> str:
    """Deterministic day-of-year rotation."""
    if not bank:
        return ""
    doy = datetime.now().timetuple().tm_yday
    return bank[doy % len(bank)]


# ═══════════════════════════════════════════════════════════════
# SEARXNG
# ═══════════════════════════════════════════════════════════════

def searxng_fetch(base_url: str, query: str, category: str = "news",
                  max_results: int = 5, timeout: int = 15) -> list[str]:
    """Query SearXNG and return deduplicated result titles."""
    url = (f"{base_url.rstrip('/')}/search"
           f"?q={urllib.parse.quote(query)}"
           f"&format=json&categories={category}&pageno=1")
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "HermesRadio/1.0 (zero-llm broadcast)",
            "Accept": "application/json",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())

        seen = set()
        results = []
        for r in data.get("results", []):
            title = r.get("title", "").strip()
            if not title:
                continue
            # Dedup by lowercase alphanumeric prefix
            key = "".join(c.lower() for c in title[:60] if c.isalnum())
            if key and key not in seen:
                seen.add(key)
                results.append(title)
                if len(results) >= max_results:
                    break
        return results
    except Exception as e:
        print(f"[warn] SearXNG ({category}) failed: {e}", file=sys.stderr)
        return []


# ═══════════════════════════════════════════════════════════════
# TTS
# ═══════════════════════════════════════════════════════════════

def generate_tts(text: str, voice: str, output_path: Path) -> Path:
    """Generate speech audio using edge-tts via uv."""
    cmd = ["uv", "run", "edge-tts",
           "--voice", voice,
           "--text", text,
           "--write-media", str(output_path)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if result.returncode != 0:
        raise RuntimeError(f"TTS failed (exit {result.returncode}): {result.stderr}")
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError("TTS produced empty output file")
    return output_path


def get_audio_duration(path: Path) -> float:
    """Get duration in seconds using ffprobe."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration", "-of",
         "default=noprint_wrappers=1:nokey=1",
         str(path)],
        capture_output=True, text=True, timeout=30,
    )
    try:
        return float(result.stdout.strip())
    except (ValueError, TypeError):
        return 0.0


def concat_audio(segments: list[Path], output_path: Path):
    """Concatenate multiple audio files via FFmpeg."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        filelist = f.name
        for seg in segments:
            f.write(f"file '{seg}'\n")
    try:
        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", filelist,
            "-acodec", "libmp3lame", "-ab", "64k",
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg concat failed: {result.stderr}")
    finally:
        Path(filelist).unlink(missing_ok=True)


def cleanup_old(directory: Path, keep_days: int):
    """Remove broadcast files older than keep_days."""
    cutoff = datetime.now().timestamp() - keep_days * 86400
    for f in directory.glob("hermes-radio-*.mp3"):
        if f.stat().st_mtime < cutoff:
            f.unlink(missing_ok=True)


# ═══════════════════════════════════════════════════════════════
# DATA COLLECTION
# ═══════════════════════════════════════════════════════════════

def collect_data(cfg: dict) -> dict:
    """Fetch all show content and return template context."""
    today = datetime.now()
    ctx = {
        "date": today.strftime("%A, %B %d, %Y"),
        "short_date": today.strftime("%Y%m%d"),
        "year": today.year,
        "month": today.strftime("%B"),
    }

    config_dir = cfg["_config_dir"]

    # ── Headlines ──
    h = cfg.get("headlines", {})
    if h.get("enabled", True):
        query = h.get("query", "AI artificial intelligence {month} {year}")
        query = query.format(**ctx)
        ctx["headlines"] = searxng_fetch(
            cfg["searxng"]["base_url"], query, "news",
            h.get("max_results", 4),
            cfg["searxng"]["timeout"],
        )
    else:
        ctx["headlines"] = []

    # ── Music ──
    m = cfg.get("music", {})
    if m.get("enabled", True):
        query = f"new music video trending {ctx['month']} {ctx['year']}"
        songs = searxng_fetch(
            cfg["searxng"]["base_url"], query, "videos",
            m.get("max_results", 2),
            cfg["searxng"]["timeout"],
        )
        ctx["music"] = songs[0] if songs else ""
    else:
        ctx["music"] = ""

    # ── Content banks ──
    for key, bank_path in cfg.get("content", {}).get("banks", {}).items():
        full_path = config_dir / bank_path
        bank = load_bank(full_path)
        ctx[key] = pick_today(bank)

    return ctx


# ═══════════════════════════════════════════════════════════════
# TEMPLATE RENDERING
# ═══════════════════════════════════════════════════════════════

def render_template(template_path: Path, context: dict) -> str:
    """Render a Jinja2 template with context."""
    env = Environment(
        loader=FileSystemLoader(str(template_path.parent)),
        autoescape=select_autoescape(default=False),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template(template_path.name)
    return template.render(**context)


# ═══════════════════════════════════════════════════════════════
# MODE RUNNERS
# ═══════════════════════════════════════════════════════════════

def run_audio_mode(cfg: dict, ctx: dict, templates_dir: Path, output_dir: Path) -> Path:
    """Generate TTS audio, assemble with FFmpeg, return output path."""
    # Render narration script
    tts_text = render_template(templates_dir / "tts_script.txt.j2", ctx)
    if not tts_text.strip():
        print("[error] TTS template rendered empty — check your templates/tts_script.txt.j2",
              file=sys.stderr)
        sys.exit(1)

    # TTS
    voice = cfg.get("tts", {}).get("voice", "en-US-ChristopherNeural")
    output_file = output_dir / f"hermes-radio-{ctx['short_date']}.mp3"
    print(f"  Generating TTS ({voice})...", file=sys.stderr)
    generate_tts(tts_text, voice, output_file)

    # Duration
    duration = get_audio_duration(output_file)
    ctx["duration"] = f"{duration:.0f}"

    # Cleanup old files
    cleanup_old(output_dir, cfg["output"]["cleanup_days"])

    # Render caption
    caption = render_template(templates_dir / "telegram.md.j2", {**ctx, "mode": "audio"})
    print(caption)
    print(f"MEDIA:{output_file}")

    return output_file


def run_text_mode(cfg: dict, ctx: dict, templates_dir: Path):
    """Render text-only briefing from the Telegram template."""
    caption = render_template(templates_dir / "telegram.md.j2", {**ctx, "mode": "text"})
    print(caption)


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Hermes Radio — Zero-LLM Daily Broadcast Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python3 broadcast.py                          # audio mode (default)\n"
            "  python3 broadcast.py --mode text               # text-only briefing\n"
            "  python3 broadcast.py --config /path/to/config  # custom config\n"
        ),
    )
    parser.add_argument("-c", "--config", default="config.yaml",
                        help="Path to config.yaml (default: ./config.yaml)")
    parser.add_argument("-m", "--mode", choices=["audio", "text"], default=None,
                        help="Override mode from config (audio or text)")
    args = parser.parse_args()

    # Load config
    cfg_path = Path(args.config).resolve()
    cfg = load_config(cfg_path)

    # Optional mode override
    if args.mode:
        cfg["mode"] = args.mode

    # Resolve paths relative to config directory
    config_dir = cfg["_config_dir"]
    templates_dir = config_dir / cfg.get("templates_dir", "templates")
    output_dir = config_dir / cfg["output"]["directory"]
    output_dir.mkdir(parents=True, exist_ok=True)

    # Validate templates exist
    template_file = "tts_script.txt.j2" if cfg["mode"] == "audio" else "telegram.md.j2"
    if not (templates_dir / template_file).exists():
        print(f"[error] Template not found: {templates_dir / template_file}", file=sys.stderr)
        sys.exit(1)

    # Collect data
    print(f"Hermes Radio — {datetime.now().strftime('%A, %B %d, %Y')}", file=sys.stderr)
    print(f"Mode: {cfg['mode']}", file=sys.stderr)
    print(f"Collecting data...", file=sys.stderr)
    context = collect_data(cfg)
    print(f"  ✓ Headlines: {len(context.get('headlines', []))}", file=sys.stderr)
    print(f"  ✓ Music: {'yes' if context.get('music') else 'no'}", file=sys.stderr)

    # Run mode
    if cfg["mode"] == "audio":
        run_audio_mode(cfg, context, templates_dir, output_dir)
    else:
        run_text_mode(cfg, context, templates_dir)


if __name__ == "__main__":
    main()
