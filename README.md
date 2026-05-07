# deck-auto-tdp

Auto-learning TDP optimizer for Steam Deck. Finds the minimum TDP each game needs over multiple sessions — no manual tuning, no Decky Loader required.

## How it works

Runs as a systemd user service. On game launch, applies the last known TDP profile. During play, monitors GPU busy % and binary-searches for the lowest TDP that keeps the GPU running without saturation. Saves per-game profiles on exit.

- **GPU < 62% busy** → TDP has headroom, step down 1W
- **GPU > 88% busy** → TDP is limiting, step up 1W
- **GPU 62-88% busy** → stable, save this TDP

Converges over 3-5 sessions. Confidence score tracks how dialed-in each profile is.

## Requirements

- Steam Deck (SteamOS)
- `ryzenadj` — `sudo pacman -S ryzenadj`
- Python 3.10+

## Install

```bash
git clone https://github.com/jeanpascua/deck-auto-tdp ~/projects/deck-auto-tdp
cd ~/projects/deck-auto-tdp
bash scripts/install.sh
```

## Logs

```bash
journalctl --user -u deck-auto-tdp -f
```

## Profiles

Stored at `~/.config/deck-auto-tdp/profiles.json`. Edit manually to override a learned TDP or reset a game's confidence.

## Uninstall

```bash
systemctl --user stop deck-auto-tdp
systemctl --user disable deck-auto-tdp
rm ~/.config/systemd/user/deck-auto-tdp.service
```
