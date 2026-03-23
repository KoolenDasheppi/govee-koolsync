# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview
`govee-koolsync` is a professional-grade, zero-latency music visualizer for Govee H6004 bulbs on macOS.
It bypasses the Govee app's latency by reverse-engineering the "Instant Snap" BLE protocol.

## Architecture
- **3-Bulb Routing**: Lows (<150Hz), Mids (150-2000Hz), Highs (>2000Hz).
- **Asynchronous BLE**: Uses `bleak` for non-blocking Bluetooth communication and `asyncio` for the consumer loop.
- **Audio Pipeline**: Uses `pyaudio` (blocking callback) + `scipy` (SOS filters) + `aubio` (onset/pitch detection).
- **State Machine**: Audio thread writes to `state.target_colors`; BLE consumer loop polls and sends, preventing stale packets.
- **Preset System**: All tuning parameters (multipliers, palettes, cooldowns) are externalized in `config.json` and deep-merged via `deep_update`.

## Key Components
- `visualizer.py`: Main logic. **MAC addresses are placeholders here.**
- `main_personal.py`: Contains real hardware MACs and is gitignored.
- `config.json`: Tuning profiles (dubstep, metal, etc.).

## How to Run
```bash
# Requires BlackHole 2ch for audio routing on macOS.
pip install bleak aubio scipy pyaudio numpy colorsys
python visualizer.py --preset dubstep
```

## Development Notes
- **Protocol**: Uses 20-byte XOR-checksum payloads (`0x33...`) and 2.0s heartbeats (`0xAA...`).
- **Payload**: `0x33, 0x05, 0x05, 0x00, R, G, B, ...CHECKSUM`.
- **Anti-Crash**: Staggered 40ms sleep between bulb updates to prevent BLE congestion.
