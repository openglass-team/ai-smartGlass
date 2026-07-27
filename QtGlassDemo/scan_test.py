"""扫描附近 BLE 设备"""
import asyncio
from bleak import BleakScanner

async def main():
    print("Scanning for 10 seconds...")
    devices = await BleakScanner.discover(timeout=10.0, return_adv=True)
    print(f"\nFound {len(devices)} devices:\n")
    for d, adv in devices.values():
        if d.name:
            print(f"  [{d.address}]  {d.name}")
    print()

asyncio.run(main())
