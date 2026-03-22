
# Govee-KoolSync 🚥🎸🎶

Yo... so, okay. I'm writing this while absolutely baked right now lmao, but I just spent like, I don't even know how long, building this thing and my mind is literally blown. XD

Basically, I wanted my room to look like a literal dubstep and tearout festival when I'm jamming out with my Zoom G1X FOUR or my Flatsons FBA-10 amp. The official Govee app music sync is okay, but I wanted absolute control. So, I used some AI coding tools (shoutout to my terminal agents hehe~) because I am very much a novice hobbyist programmer, and we reverse-engineered the secret Govee Bluetooth payloads to make this thing completely zero-latency. 

It's hyper-specific to my setup right now (three H6004 bulbs mapped to lows, mids, and highs), but honestly, it's so freakin' cool. X3

## ✨ What It Actually Does (The Cool Shtuff)

* **Zero-Latency Instant Snaps:** We bypassed Govee's annoying hardware color-fade by sniffing the actual BLE packets (used PacketLogger on my Mac, felt like a hacker or something lmao). It uses a secret `0x05 0x05` payload so the bulbs strobe instantly to the kick drums.
* **3-Way Frequency Splitting:** It uses `scipy` filters to split the aux audio. One bulb ONLY flashes to sub-bass (warm reds/oranges/purples), one flashes to the mids like my guitar or the snare (toxic greens/yellows), and one flashes to the hi-hats (icy blues/whites).
* **Self-Tuning AI Math (Dynamic Thresholding):** It keeps a short-term memory of the song's volume. If the song gets quiet, it gets more sensitive. If a massive deathstep drop hits, it clamps down and only flashes on the hardest kicks so it doesn't just turn into a white blob. OwO
* **Pitch-to-Color Synesthesia:** The Mids and Highs bulbs actually read the musical note using `aubio.pitch` and change their Hue based on the exact frequency of the guitar chord or synth. It's trippy as hell.
* **Preset System:** Everything is controlled by a `config.json` file. You can swap between profiles for `dubstep`, `heavy_guitar`, `clean_guitar`, etc., without touching the main Python code because hardcoding is for nerds. 

## 🛠️ How to Use It (I think?)

I run this on a Mac using BlackHole 2ch to route the audio, but I also just plug an aux cable straight from my Flatsons into it. 
You'll need Python and a few packages: `bleak`, `aubio`, `scipy`, and `pyaudio`.

Just open your terminal and run:
`python visualizer.py --preset dubstep`

(Or whatever preset you want from the config file). Also, make sure to put your own Govee UUIDs in the config, unless you want to accidentally hijack your neighbor's living room lights... which we totally didn't do during testing. >_>

## 🤝 Plz Help Me Build This (Contributing)

Okay look, this is very much a personal project right now because I just wanted to jam out in my room, maybe put on my Quest 3 later, and I barely know what I'm doing half the time. \^w^

BUT! If any real programmers out there want to turn this into a legit open-source lighting engine, **Pull Requests are MORE than welcome!** Got a feature request or found a bug? Drop it in the issues section! I'll try to look at it when I'm not distracted by all the crazy shit I get up to lmao. :3

Enjoy the lights, stay Kool, and play some heavy shtuff! 🤘
