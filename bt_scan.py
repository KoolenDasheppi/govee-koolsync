#!/usr/bin/env python3
"""Scan for nearby Bluetooth devices using bleak."""

import asyncio
import sys
from bleak import BleakScanner


async def main():
    print("Scanning for Bluetooth devices for 10 seconds...")
    print("-" * 50)

    devices = await BleakScanner.discover(timeout=10.0)

    if not devices:
        print("No devices found.")
        return

    print(f"Found {len(devices)} device(s):\n")

    for device in devices:
        name = device.name or "Unknown"
        print(f"  Name: {name}")
        print(f"  Address: {device.address}")
        print("-" * 50)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nScan interrupted.")
        sys.exit(1)
