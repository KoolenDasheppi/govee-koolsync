import asyncio
import time
import random
import numpy as np
import pyaudio
import aubio
import colorsys
import json
import argparse
from scipy import signal
from bleak import BleakClient
from collections import deque

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

# Palettes
PALETTE_LOWS = [(255, 0, 0), (255, 80, 0), (128, 0, 128), (255, 0, 255)]

# --- PRESET LOADING ---
# Load config early to populate help text
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

# Start with defaults and override with preset
settings = config_data["defaults"].copy()
if args.preset in config_data["presets"]:
    print(f"Applying Preset: {args.preset} - {config_data['presets'][args.preset].get('description', '')}")
    settings.update(config_data["presets"][args.preset])
else:
    print(f"Preset '{args.preset}' not found. Using defaults/dubstep.")

# Global settings injection
SENSITIVITY_MULTIPLIERS = settings["SENSITIVITY_MULTIPLIERS"]
COOLDOWNS = settings["COOLDOWNS"]
ABS_NOISE_FLOOR = settings["ABS_NOISE_FLOOR"]
HUE_BOUNDARIES = settings["HUE_BOUNDARIES"]

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
                    state.target_colors[mac] = random.choice(PALETTE_LOWS)
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
    print(f"Running visualizer with preset: {args.preset}")
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
                        await asyncio.sleep(0.04)
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
    await asyncio.gather(*(connect_and_manage(mac) for mac in DEVICE_MACS))
    if len(state.clients) == 0: return
    stream = p.open(format=pyaudio.paFloat32, channels=1, rate=SAMPLE_RATE, input=True, input_device_index=device_index, frames_per_buffer=CHUNK_SIZE, stream_callback=audio_callback)
    stream.start_stream()
    try: await ble_consumer_loop()
    except asyncio.CancelledError: pass
    finally:
        state.running = False; stream.stop_stream(); stream.close(); p.terminate()
        for client in state.clients.values(): await client.disconnect()

if __name__ == "__main__":
    try: asyncio.run(run_visualizer())
    except KeyboardInterrupt: pass
