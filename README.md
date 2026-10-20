# HVM 8.4 Panel

Source files from the supplied HVM 8.4 archive, organized at the repository root.

## Contents
- Python panel backend and node services
- `templates/` and `static/` for the web interface
- `bot/` for the Discord bot
- `requirements.txt` and `bot/requirements.txt`
- `UPGRADE-8.4.md` for project-specific upgrade notes

## Python setup
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Read `UPGRADE-8.4.md` and inspect configuration before deployment. Do not commit real passwords, API keys, tokens, or private keys. Review code and licensing before making this repository public.
