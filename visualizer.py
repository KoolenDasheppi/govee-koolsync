import asyncio
import time
import random
import numpy as np
import pyaudio
import aubio
import colorsys
import json
import argparse
import copy
import os
from scipy import signal
from bleak import BleakClient
from collections import deque
from aiohttp import web

# --- CONFIGURATION (STRICT ROUTING) ---
MAC_LOWS  = "PLACEHOLDER_MAC_1"
MAC_MIDS  = "PLACEHOLDER_MAC_2"
MAC_HIGHS = "PLACEHOLDER_MAC_3"

DEVICE_MACS = [MAC_LOWS, MAC_MIDS, MAC_HIGHS]
SERVICE_UUID = "00010203-0405-0607-0809-0a0b0c0d1910"
CHAR_UUID = "00010203-0405-0607-0809-0a0b0c0d2b11"

AUDIO_DEVICE_NAME = "BlackHole 2ch"
CHUNK_SIZE = 256
SAMPLE_RATE = 44100

# --- SMART PRESET SYSTEM ---
def deep_update(base_dict, update_dict):
    """Recursively update a dictionary."""
    for key, value in update_dict.items():
        if isinstance(value, dict) and key in base_dict:
            deep_update(base_dict[key], value)
        else:
            base_dict[key] = value

with open("config.json", "r") as f:
    config_data = json.load(f)

preset_help = "Available presets:\n"
for p_name, p_data in config_data["presets"].items():
    desc = p_data.get("description", "No description")
    preset_help += f"  {p_name}: {desc}\n"

parser = argparse.ArgumentParser(
    description="Govee KoolSync Music Visualizer",
    formatter_class=argparse.RawTextHelpFormatter
)
parser.add_argument("--preset", type=str, default="dubstep", help=preset_help)
args = parser.parse_args()

settings = copy.deepcopy(config_data["defaults"])
if args.preset in config_data["presets"]:
    print(f"Applying Preset: {args.preset} - {config_data['presets'][args.preset].get('description', '')}")
    deep_update(settings, config_data["presets"][args.preset])
else:
    print(f"Preset '{args.preset}' not found. Using defaults.")

# Active parameters (can be updated via web dashboard)
active_params = {
    "SENSITIVITY_MULTIPLIERS": settings["SENSITIVITY_MULTIPLIERS"],
    "COOLDOWNS": settings["COOLDOWNS"],
    "ABS_NOISE_FLOOR": settings["ABS_NOISE_FLOOR"],
    "HUE_BOUNDARIES": settings["HUE_BOUNDARIES"],
    "PALETTES": settings["PALETTES"]
}

SENSITIVITY_MULTIPLIERS = active_params["SENSITIVITY_MULTIPLIERS"]
COOLDOWNS = active_params["COOLDOWNS"]
ABS_NOISE_FLOOR = active_params["ABS_NOISE_FLOOR"]
HUE_BOUNDARIES = active_params["HUE_BOUNDARIES"]
PALETTES = active_params["PALETTES"]

# --- STATE MACHINE ---
class VisualizerState:
    def __init__(self):
        self.target_colors = {mac: (0, 0, 0) for mac in DEVICE_MACS}
        self.last_sent_colors = {mac: (0, 0, 0) for mac in DEVICE_MACS}
        self.last_beat_times = {mac: 0 for mac in DEVICE_MACS}
        self.clients = {}
        self.running = True
        self.history_length = 80
        self.rms_history = {band: deque([0.01]*self.history_length, maxlen=self.history_length) for band in ["lows", "mids", "highs"]}
        self.onset_history = {band: deque([0.1]*self.history_length, maxlen=self.history_length) for band in ["lows", "mids", "highs"]}
        # Filters
        self.sos_low = signal.butter(10, 150, 'lp', fs=SAMPLE_RATE, output='sos')
        self.zi_low = signal.sosfilt_zi(self.sos_low)
        self.sos_mid = signal.butter(10, [150, 2000], 'bp', fs=SAMPLE_RATE, output='sos')
        self.zi_mid = signal.sosfilt_zi(self.sos_mid)
        self.sos_high = signal.butter(10, 2000, 'hp', fs=SAMPLE_RATE, output='sos')
        self.zi_high = signal.sosfilt_zi(self.sos_high)

state = VisualizerState()
onset_detectors = {}
pitch_detectors = {}

# --- WEB DASHBOARD ---
HTML_CONTENT = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>KoolSync Live Tweaker</title>
    <style>
        :root {
            --bg: #121212;
            --surface: #1e1e1e;
            --primary: #bd93f9;
            --accent: #50fa7b;
            --text: #f8f8f2;
            --muted: #6272a4;
        }
        body { background-color: var(--bg); color: var(--text); font-family: -apple-system, sans-serif; margin: 0; padding: 20px; display: flex; justify-content: center; }
        .container { max-width: 800px; width: 100%; display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; }
        .card { background: var(--surface); padding: 20px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }
        h2 { color: var(--primary); margin-top: 0; border-bottom: 2px solid var(--muted); padding-bottom: 10px; }
        .control-group { margin-bottom: 15px; }
        label { display: flex; justify-content: space-between; margin-bottom: 5px; font-size: 0.9em; color: var(--muted); }
        input[type="range"] { width: 100%; accent-color: var(--primary); cursor: pointer; }
        .header { grid-column: 1 / -1; text-align: center; margin-bottom: 20px; }
        .btn { background: var(--primary); color: #000; border: none; padding: 10px 20px; border-radius: 6px; cursor: pointer; font-weight: bold; margin-top: 10px; width: 100%; transition: transform 0.1s; }
        .btn:hover { transform: scale(1.02); background: #a779e6; }
        .btn:active { transform: scale(0.98); }
        .status { margin-top: 10px; text-align: center; font-size: 0.8em; min-height: 1.2em; color: var(--accent); }
    </style>
</head>
<body>
    <div class="container">
        <div class="header card">
            <h1>🎛️ KoolSync Live Tweaker</h1>
            <p style="color:var(--muted)">Real-time adjustments for your lights</p>
            <div id="status" class="status">System Online</div>
            <button class="btn" onclick="saveSettings()">💾 Save to Config</button>
        </div>

        <div class="card">
            <h2>🔊 Sensitivity Multipliers</h2>
            <div class="control-group">
                <label>Lows (Sub-Bass) <span id="l_mul_val">1.8</span></label>
                <input type="range" id="l_mul" min="1.0" max="5.0" step="0.1" value="1.8">
            </div>
            <div class="control-group">
                <label>Mids (Guitar/Synth) <span id="m_mul_val">2.2</span></label>
                <input type="range" id="m_mul" min="1.0" max="5.0" step="0.1" value="2.2">
            </div>
            <div class="control-group">
                <label>Highs (Hi-Hats) <span id="h_mul_val">2.5</span></label>
                <input type="range" id="h_mul" min="1.0" max="5.0" step="0.1" value="2.5">
            </div>
        </div>

        <div class="card">
            <h2>⏱️ Cooldowns (s)</h2>
            <div class="control-group">
                <label>Lows <span id="l_cool_val">0.10</span></label>
                <input type="range" id="l_cool" min="0.01" max="0.30" step="0.01" value="0.10">
            </div>
            <div class="control-group">
                <label>Mids <span id="m_cool_val">0.08</span></label>
                <input type="range" id="m_cool" min="0.01" max="0.30" step="0.01" value="0.08">
            </div>
            <div class="control-group">
                <label>Highs <span id="h_cool_val">0.08</span></label>
                <input type="range" id="h_cool" min="0.01" max="0.30" step="0.01" value="0.08">
            </div>
        </div>

        <div class="card">
            <h2>🔇 Noise Floor</h2>
            <div class="control-group">
                <label>Abs Threshold <span id="abs_val">0.020</span></label>
                <input type="range" id="abs" min="0.001" max="0.100" step="0.001" value="0.020">
            </div>
        </div>
    </div>

    <script>
        const ids = {
            l_mul: 'SENSITIVITY_MULTIPLIERS', m_mul: 'SENSITIVITY_MULTIPLIERS', h_mul: 'SENSITIVITY_MULTIPLIERS',
            l_cool: 'COOLDOWNS', m_cool: 'COOLDOWNS', h_cool: 'COOLDOWNS',
            abs: 'ABS_NOISE_FLOOR'
        };
        const maps = {
            l_mul: ['lows', 0], m_mul: ['mids', 0], h_mul: ['highs', 0],
            l_cool: ['lows', 0], m_cool: ['mids', 0], h_cool: ['highs', 0]
        };

        async function loadSettings() {
            try {
                const res = await fetch('/api/config');
                const data = await res.json();

                document.getElementById('l_mul').value = data.SENSITIVITY_MULTIPLIERS.lows;
                document.getElementById('l_mul_val').innerText = data.SENSITIVITY_MULTIPLIERS.lows;
                document.getElementById('m_mul').value = data.SENSITIVITY_MULTIPLIERS.mids;
                document.getElementById('m_mul_val').innerText = data.SENSITIVITY_MULTIPLIERS.mids;
                document.getElementById('h_mul').value = data.SENSITIVITY_MULTIPLIERS.highs;
                document.getElementById('h_mul_val').innerText = data.SENSITIVITY_MULTIPLIERS.highs;

                document.getElementById('l_cool').value = data.COOLDOWNS.lows;
                document.getElementById('l_cool_val').innerText = data.COOLDOWNS.lows;
                document.getElementById('m_cool').value = data.COOLDOWNS.mids;
                document.getElementById('m_cool_val').innerText = data.COOLDOWNS.mids;
                document.getElementById('h_cool').value = data.COOLDOWNS.highs;
                document.getElementById('h_cool_val').innerText = data.COOLDOWNS.highs;

                document.getElementById('abs').value = data.ABS_NOISE_FLOOR;
                document.getElementById('abs_val').innerText = data.ABS_NOISE_FLOOR;
            } catch (e) { console.error(e); }
        }

        async function updateSetting(key, id, type, sub_key) {
            const el = document.getElementById(id);
            const val = parseFloat(el.value);
            document.getElementById(id + '_val').innerText = val.toFixed(type === 'floor' ? 3 : 1);

            const body = {};
            if (sub_key) body[ids[id]] = { [sub_key]: val };
            else body[ids[id]] = val;

            await fetch('/api/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            });
        }

        ['l_mul', 'm_mul', 'h_mul', 'l_cool', 'm_cool', 'h_cool', 'abs'].forEach(id => {
            const el = document.getElementById(id);
            const sub_key = maps[id] ? maps[id][0] : null;
            const type = id === 'abs' ? 'floor' : 'mult';
            el.addEventListener('input', () => updateSetting(ids[id], id, type, sub_key));
        });

        async function saveSettings() {
            const btn = document.querySelector('.btn');
            const status = document.getElementById('status');
            btn.disabled = true;
            status.innerText = "Saving...";
            try {
                await fetch('/api/save', { method: 'POST' });
                status.innerText = "✅ Saved to config.json!";
            } catch (e) { status.innerText = "❌ Error saving"; }
            setTimeout(() => { btn.disabled = false; }, 1000);
        }

        loadSettings();
    </script>
</body>
</html>
"""

async def get_config(request):
    return web.json_response(active_params)

async def update_config(request):
    global SENSITIVITY_MULTIPLIERS, COOLDOWNS, ABS_NOISE_FLOOR
    data = await request.json()

    if "SENSITIVITY_MULTIPLIERS" in data:
        SENSITIVITY_MULTIPLIERS = data["SENSITIVITY_MULTIPLIERS"]
    if "COOLDOWNS" in data:
        COOLDOWNS = data["COOLDOWNS"]
    if "ABS_NOISE_FLOOR" in data:
        ABS_NOISE_FLOOR = data["ABS_NOISE_FLOOR"]

    return web.json_response({"status": "ok"})

async def save_config(request):
    deep_update(config_data["defaults"], active_params)
    with open("config.json", "w") as f:
        json.dump(config_data, f, indent=2)
    return web.json_response({"status": "saved"})

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', lambda r: web.Response(text=HTML_CONTENT, content_type='text/html'))
    app.router.add_get('/api/config', get_config)
    app.router.add_post('/api/config', update_config)
    app.router.add_post('/api/save', save_config)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()
    print("🌐 Web Dashboard running at http://localhost:8080")

# --- MATH HELPERS ---
def get_color_from_pitch(freq, min_hz, max_hz, min_hue, max_hue):
    if freq <= 0:
        mid_hue = (min_hue + max_hue) / 2
        rgb = colorsys.hsv_to_rgb(mid_hue, 1.0, 1.0)
        return tuple(int(c * 255) for c in rgb)
    norm = (np.log10(freq) - np.log10(min_hz)) / (np.log10(max_hz) - np.log10(min_hz))
    norm = np.clip(norm, 0.0, 1.0)
    hue = min_hue + (norm * (max_hue - min_hue))
    value = 0.7 + (norm * 0.3)
    rgb = colorsys.hsv_to_rgb(hue, 1.0, value)
    return tuple(int(c * 255) for c in rgb)

# --- GOVEE PROTOCOL ---
def calculate_checksum(data):
    checksum = 0
    for b in data: checksum ^= b
    return checksum

def build_color_payload(r, g, b):
    payload = bytearray([0x33, 0x05, 0x05, 0x00, r, g, b])
    payload.extend([0x00] * 12)
    payload.append(calculate_checksum(payload))
    return payload

def build_heartbeat_payload():
    payload = bytearray([0xAA, 0x01])
    payload.extend([0x00] * 17)
    payload.append(0xAB)
    return payload

def build_streaming_wakeup_payload():
    payload = bytearray([0x33, 0x05, 0x05, 0x01, 0xFF, 0x00])
    payload.extend([0x00] * 13)
    payload.append(calculate_checksum(payload))
    return payload

# --- BLE WORKERS ---
async def heartbeat_loop(client, mac):
    payload = build_heartbeat_payload()
    while state.running:
        try:
            if client.is_connected:
                await client.write_gatt_char(CHAR_UUID, payload, response=False)
        except Exception: pass
        await asyncio.sleep(2.0)

async def connect_and_manage(mac):
    print(f"Connecting to {mac}...")
    client = BleakClient(mac)
    try:
        await client.connect()
        print(f"Connected to {mac}")
        wakeup = build_streaming_wakeup_payload()
        await client.write_gatt_char(CHAR_UUID, wakeup, response=False)
        await asyncio.sleep(0.1)
        state.clients[mac] = client
        asyncio.create_task(heartbeat_loop(client, mac))
    except Exception as e:
        print(f"Failed to connect to {mac}: {e}")

# --- AUDIO ENGINE ---
def audio_callback(in_data, frame_count, time_info, status):
    global state, onset_detectors, pitch_detectors
    raw_audio = np.frombuffer(in_data, dtype=np.float32)

    low_data, state.zi_low = signal.sosfilt(state.sos_low, raw_audio, zi=state.zi_low)
    mid_data, state.zi_mid = signal.sosfilt(state.sos_mid, raw_audio, zi=state.zi_mid)
    high_data, state.zi_high = signal.sosfilt(state.sos_high, raw_audio, zi=state.zi_high)
    bands = {"lows": low_data.astype(np.float32), "mids": mid_data.astype(np.float32), "highs": high_data.astype(np.float32)}

    now = time.time()
    for name, data in bands.items():
        mac = MAC_LOWS if name == "lows" else (MAC_MIDS if name == "mids" else MAC_HIGHS)
        current_rms = np.sqrt(np.mean(data**2))
        if current_rms < ABS_NOISE_FLOOR: continue
        detector_result = bool(onset_detectors[name](data))
        current_onset = onset_detectors[name].get_last() if detector_result else 0.0
        state.rms_history[name].append(current_rms)
        state.onset_history[name].append(current_onset)
        if not detector_result: continue
        local_rms_avg = np.mean(state.rms_history[name])
        local_onset_avg = np.mean(state.onset_history[name])
        multiplier = SENSITIVITY_MULTIPLIERS[name]

        if (current_rms > local_rms_avg * multiplier or current_onset > local_onset_avg * multiplier):
            if now - state.last_beat_times[mac] > COOLDOWNS[name]:
                if name == "lows":
                    # Externalized palette for Lows
                    state.target_colors[mac] = tuple(random.choice(PALETTES["lows"]))
                elif name == "mids":
                    freq = pitch_detectors[name](data)[0]
                    min_h, max_h = HUE_BOUNDARIES["mids"]
                    state.target_colors[mac] = get_color_from_pitch(freq, 150, 1500, min_h, max_h)
                elif name == "highs":
                    freq = pitch_detectors[name](data)[0]
                    min_h, max_h = HUE_BOUNDARIES["highs"]
                    state.target_colors[mac] = get_color_from_pitch(freq, 1500, 5000, min_h, max_h)
                state.last_beat_times[mac] = now
    return (None, pyaudio.paContinue)

# --- CONSUMER LOOP ---
async def ble_consumer_loop():
    print(f"🚀 Launching strictly routed visualizer with preset: {args.preset}")
    while state.running:
        for mac in [MAC_LOWS, MAC_MIDS, MAC_HIGHS]:
            if state.target_colors[mac] != state.last_sent_colors[mac]:
                client = state.clients.get(mac)
                if client and client.is_connected:
                    try:
                        color = state.target_colors[mac]
                        payload = build_color_payload(*color)
                        await client.write_gatt_char(CHAR_UUID, payload, response=False)
                        state.last_sent_colors[mac] = color
                        await asyncio.sleep(0.04) # Anti-crash stagger
                    except Exception: pass
        await asyncio.sleep(0.02)

async def run_visualizer():
    global onset_detectors, pitch_detectors
    for name in ["lows", "mids", "highs"]:
        det = aubio.onset("specflux", 1024, CHUNK_SIZE, SAMPLE_RATE)
        det.set_threshold(0.1); onset_detectors[name] = det
        if name != "lows":
            pitch_det = aubio.pitch("yinfft", 1024, CHUNK_SIZE, SAMPLE_RATE)
            pitch_det.set_unit("Hz"); pitch_detectors[name] = pitch_det
    p = pyaudio.PyAudio()
    device_index = None
    for i in range(p.get_device_count()):
        dev = p.get_device_info_by_index(i)
        if AUDIO_DEVICE_NAME in dev['name']: device_index = i; break
    if device_index is None: return

    # Start Web Dashboard
    await start_web_server()

    await asyncio.gather(*(connect_and_manage(mac) for mac in DEVICE_MACS))
    if len(state.clients) == 0: return
    stream = p.open(format=pyaudio.paFloat32, channels=1, rate=SAMPLE_RATE, input=True,
                    input_device_index=device_index, frames_per_buffer=CHUNK_SIZE,
                    stream_callback=audio_callback)
    stream.start_stream()
    try: await ble_consumer_loop()
    except asyncio.CancelledError: pass
    finally:
        state.running = False; stream.stop_stream(); stream.close(); p.terminate()
        for client in state.clients.values(): await client.disconnect()

if __name__ == "__main__":
    try: asyncio.run(run_visualizer())
    except KeyboardInterrupt: pass
