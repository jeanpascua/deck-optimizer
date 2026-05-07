# Steam Deck Auto Optimizer

## The Problem

Steam Deck has per-game profiles but you still have to configure them manually. Every new game means figuring out the right TDP, GPU clock, and resolution settings yourself. Nothing is automatic.

## The Idea

A background Python service that detects which game is running and automatically applies the right performance settings — no manual configuration needed after initial setup.

## How It Works

- Runs as a background service on the Deck
- Watches for the active game process
- Looks it up in a JSON config file with your saved optimal settings
- Applies TDP and GPU clock settings via ryzenadj or Steam Deck's built-in tools
- Logs what it applied and when

## Settings Data

Start with a hardcoded JSON database of your own games and their optimal settings. You control the data, no dependency on external sources staying consistent. Expand later if needed.

```json
{
  "Elden Ring": { "tdp": 12, "gpu_clock": 1200, "refresh_rate": 60 },
  "Stardew Valley": { "tdp": 6, "gpu_clock": 800, "refresh_rate": 60 }
}
```

## Why This Approach

- You control the data
- You can actually test it on games you play
- The hard part is the detection and auto-apply logic, not the data
- Easy to expand — add auto-learning from your own settings, pull from an API, etc.

## Stack

- Python
- ryzenadj (TDP/GPU control)
- systemd service (runs in background)
- JSON config

## Why It's a Good GitHub Project

- Solves a real problem
- Linux service setup — connects to existing skills
- Clean automation project
- Something you'd actually use and maintain
- Easy to document and demo

## Next Steps

- [ ] Research how to detect the active game process on SteamOS
- [ ] Test ryzenadj commands on the Deck
- [ ] Build the JSON config structure
- [ ] Write the core detection + apply loop
- [ ] Set it up as a systemd service
- [ ] Document it properly on GitHub
