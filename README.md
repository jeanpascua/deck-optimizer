# deck-optimizer

Steam Deck optimizer — auto-learning TDP + AI-powered game settings. No Decky Loader required.

## How it works

Single service that handles everything:

1. **Game launches** → checks for existing profile
2. **No profile?** → scrapes SteamDeckHQ for community-tested settings
3. **No community data?** → AI predicts optimal settings (TDP, FPS, graphics preset, FSR, etc.)
4. **During gameplay** → monitors GPU usage, fine-tunes TDP in real-time
5. **Game exits** → saves learned TDP + settings to profile

Converges over 1-2 sessions with AI cold start (vs 3-5 without).

### TDP Learning

- **GPU < 62% busy** → TDP has headroom, step down 1W
- **GPU > 88% busy** → TDP is limiting, step up 1W
- **GPU 62-88% busy** → stable, save this TDP

### Settings Sources

- ✅ **Community** — scraped from SteamDeckHQ (tested by real users)
- 🤖 **AI** — predicted by local Ollama model based on game specs
- Profiles store: TDP, GPU clock, FPS limit, FSR, graphics preset, resolution, shadows, AA, textures

## Requirements

- Steam Deck (SteamOS)
- `ryzenadj` — `sudo pacman -S ryzenadj`
- Python 3.10+
- Ollama (optional, for AI predictions) — `curl -fsSL https://ollama.com/install.sh | sh && ollama pull gemma3:4b`

## Install

```bash
git clone https://github.com/jeanpascua/deck-optimizer ~/projects/deck-optimizer
cd ~/projects/deck-optimizer
bash scripts/install.sh
```

## CLI

```bash
cd ~/projects/deck-optimizer/src

# Optimize a single game
python3 -m optimizer.cli --game "Elden Ring" --app-id 1245620

# Optimize all installed games
python3 -m optimizer.cli --library

# Post results to Discord
python3 -m optimizer.cli --library --discord

# JSON output
python3 -m optimizer.cli --game "Balatro" --app-id 2379780 --json
```

## Profiles

Stored at `~/.config/deck-optimizer/profiles.json`. Edit manually to override learned settings.

## Logs

```bash
journalctl --user -u deck-optimizer -f
```

## Uninstall

```bash
systemctl --user stop deck-optimizer
systemctl --user disable deck-optimizer
rm ~/.config/systemd/user/deck-optimizer.service
```
