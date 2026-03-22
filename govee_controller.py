#!/usr/bin/env python3
"""Single-bulb Govee H6004 test using sniffed 0x0D protocol."""

import asyncio
from bleak import BleakClient

GOVEE_WRITE_CHAR_UUID = "00010203-0405-0607-0809-0a0b0c0d2b11"

BULB_ADDRESS = "A6E68E67-0828-C480-9669-61909A36BAC5"


def make_heartbeat() -> bytearray:
    payload = bytearray(20)
    payload[0] = 0xAA
    payload[1] = 0x01
    payload[19] = 0xAB
    return payload


def make_color(r: int, g: int, b: int) -> bytearray:
    payload = bytearray(20)
    payload[0] = 0x33
    payload[1] = 0x05
    payload[2] = 0x0D
    payload[3] = r
    payload[4] = g
    payload[5] = b
    checksum = 0
    for i in range(19):
        checksum ^= payload[i]
    payload[19] = checksum
    return payload


async def send(client: BleakClient, payload: bytearray, label: str) -> None:
    print(f"  {label}: {payload.hex()}", flush=True)
    await client.write_gatt_char(GOVEE_WRITE_CHAR_UUID, payload, response=False)


async def main():
    print("Connecting to bulb...", flush=True)
    client = BleakClient(BULB_ADDRESS)
    await client.connect()
    print(f"Connected to {BULB_ADDRESS}", flush=True)

    # Send initial heartbeat
    await send(client, make_heartbeat(), "Heartbeat")

    # Let bulb process
    await asyncio.sleep(0.5)

    # Send red color
    await send(client, make_color(255, 0, 0), "Red")

    # Keep connection alive with heartbeat every 2s
    print("Heartbeat loop running (Ctrl+C to stop)...", flush=True)
    while True:
        await asyncio.sleep(2)
        await send(client, make_heartbeat(), "Heartbeat")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nDone.", flush=True)
