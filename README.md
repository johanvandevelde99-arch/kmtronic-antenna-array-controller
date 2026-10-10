# KMTRONIC Antenna Array Controller

A Python-based controller for a switchable antenna array driven by a KMTRONIC relay board.
This project packages the original single-file `9CA_KMTronic_Controller.py` app into a cleaner Python package layout while keeping the desktop app runnable from the repo root.

## What this project does

- controls relay-based antenna direction selection
- supports KMTronic UDP or HTTP relay endpoints
- works in demo mode without hardware attached
- exposes a Tkinter desktop UI for direction switching and relay status
- keeps configuration in a local JSON file next to the app

## Repository layout

- `9CA_KMTronic_Controller.py` — thin launcher entry point
- `src/kmtronic_antenna_array/` — packaged application code
- `LICENSE` — MIT license

## Quick start

### 1) Install

```bash
git clone https://github.com/johanvandevelde99-arch/kmtronic-antenna-array-controller.git
cd kmtronic-antenna-array-controller
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
```

### 2) Run the desktop controller

```bash
python 9CA_KMTronic_Controller.py
```

or

```bash
python -m kmtronic_antenna_array
```

## Configuration

The app writes settings to a local config file named `9ca_cfg.json` in the same directory as the script or executable. This makes it easy to carry the configuration with the program.

Typical settings include:

- transport: `udp` or `http`
- host / IP address of the KMTronic relay
- port
- optional username/password for web-relay mode
- direction-to-relay map
- auxiliary relay labels/colors
- beam offset in degrees

## Hardware notes

This project was designed around the KMTronic relay board family and can work with either:

- UDP relay control on classic KMTronic boards
- HTTP control for web-interface KMTronic boards

If your hardware firmware differs slightly, the relay transport code is isolated in the package so it can be adapted without changing the UI logic.

## Development notes

The code is organized into modules under `src/kmtronic_antenna_array/` for easier maintenance:

- `config.py` — default settings and JSON persistence
- `relay.py` — KMTronic communication logic
- `app.py` — Tkinter UI and controller logic
- `__main__.py` — command-line startup

## License

MIT License. See `LICENSE` for details.
