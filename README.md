# deck-optimizer

AI-powered game settings recommender for Steam Deck. Tells you exactly what to set in the Quick Access Menu for every game — no guessing, no Googling. Powered by community data from SteamDeckHQ + local AI fallback.

## What it does

Runs as a background service on your Steam Deck. When you launch a game, it sends a **Discord notification** with the recommended Quick Access Menu settings:

- **TDP** — optimal wattage for the game
- **GPU Clock** — optimal frequency
- **FPS Limit** — 30/40/60 based on game weight
- **FSR** — on or off
- **Scaling Mode/Filter** — fit/fill, fsr/linear/integer
- **Half Rate Shading** — on or off
- **Allow Tearing** — on or off

Settings come from two sources:
- ✅ **SteamDeckHQ** — community-tested, verified by real users
- 🤖 **AI prediction** — local Ollama model predicts based on game specs when no community data exists

You apply the settings yourself via the Quick Access Menu (`...` button). Steam's Quick Access settings are stored in an internal binary format that can't be modified programmatically — this is why tools like Decky Loader exist as plugins inside Steam itself.

## Requirements

### On the Steam Deck
- SteamOS
- Python 3.10+

### On your PC (for AI optimizer)
- Python 3.10+
- [Ollama](https://ollama.com) with a model (e.g. `gemma3:4b`)
- SSH access to your Deck
- `pip install -r requirements.txt`

## Install

### 1. Clone on Steam Deck

```bash
git clone https://github.com/jeanpascua/deck-optimizer ~/projects/deck-optimizer
cd ~/projects/deck-optimizer
bash scripts/install.sh
```

The installer will:
- Run interactive setup (Deck IP, Discord webhook, display model)
- Check for ryzenadj
- Install and start the systemd service

### 2. Install ryzenadj (Steam Deck)

```bash
sudo steamos-readonly disable
sudo pacman-key --init && sudo pacman-key --populate
sudo pacman -S base-devel cmake git pciutils
git clone https://github.com/FlyGoat/RyzenAdj ~/ryzenadj
cd ~/ryzenadj && mkdir build && cd build && cmake .. && make
sudo cp ryzenadj /usr/local/bin/ && sudo chmod +s /usr/local/bin/ryzenadj
sudo steamos-readonly enable
```

### 3. Set up PC-side optimizer (optional)

On your PC:

```bash
git clone https://github.com/jeanpascua/deck-optimizer ~/projects/deck-optimizer
cd ~/projects/deck-optimizer
pip install -r requirements.txt
ollama pull gemma3:4b
python3 src/config.py  # interactive setup
```

Set up SSH key access to your Deck:

```bash
ssh-copy-id deck@steamdeck.local
```

## Usage

### Optimize all games (from PC)

```bash
cd ~/projects/deck-optimizer/src
python3 -m optimizer.sync_deck
```

Fetches your Deck's game library, optimizes each game (community + AI), and syncs profiles to the Deck.

### Optimize a single game

```bash
python3 -m optimizer.cli --game "Elden Ring" --app-id 1245620
```

### Post results to Discord

```bash
python3 -m optimizer.cli --library --discord
```

### JSON output

```bash
python3 -m optimizer.cli --game "Cyberpunk 2077" --app-id 1091500 --json
```

## Configuration

Config file: `~/.config/deck-optimizer/config.json`

See `config/config.example.json` for all options. Key settings:

| Setting | Default | Description |
|---|---|---|
| `deck_host` | `deck@steamdeck.local` | SSH host for your Deck |
| `ollama_model` | `gemma3:4b` | Local LLM for predictions |
| `display_model` | `lcd` | `lcd` (60Hz) or `oled` (90Hz) |
| `discord_webhook_file` | `~/.config/deck-optimizer/discord-webhook` | Path to webhook URL file |

## How learning works

### Real-time TDP (during play)

- **GPU < 62% busy** → TDP has headroom, step down 1W
- **GPU > 88% busy** → TDP is limiting, step up 1W
- **GPU 62-88% busy** → stable, save this TDP

Converges over 1-2 sessions with AI cold start, 3-5 without.

### AI post-session analysis (on exit)

After each session (>5 min), the local Ollama model analyzes GPU%, power draw, temps, and battery drain against current settings and recommends adjustments for TDP, FPS limit, GPU clock, FSR, and scaling options.

- **Confidence ≥ 85%** → adjustments auto-applied to profile (`settings_source: ai_learned`)
- **Confidence ≥ 70%** → Discord embed sent with recommendation and whether it was applied

## Profiles

Stored at `~/.config/deck-optimizer/profiles.json`. Each game profile contains:

```json
{
  "app_id": "292030",
  "game_name": "The Witcher 3: Wild Hunt",
  "learned_tdp": 12.0,
  "session_count": 3,
  "confidence": 0.6,
  "target_fps": 40,
  "gpu_clock": 1200,
  "fsr": true,
  "graphics_preset": "medium",
  "resolution": "1280x800",
  "shadows": "medium",
  "scaling_filter": "fsr",
  "settings_source": "ai"
}
```

Edit manually to override any value.

## Logs

```bash
journalctl --user -u deck-optimizer -f
```

## Uninstall

```bash
systemctl --user stop deck-optimizer
systemctl --user disable deck-optimizer
rm ~/.config/systemd/user/deck-optimizer.service
rm -rf ~/.config/deck-optimizer
```

## License

MIT
