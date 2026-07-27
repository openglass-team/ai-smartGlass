"""最小 BLE 连接测试 - 只连接，不做任何操作，看会不会断"""
import asyncio
from bleak import BleakScanner, BleakClient
import time

SERVICE_UUID = "19b10000-e8f2-537e-4f6c-d104768a1214"
PHOTO_DATA_UUID = "19b10005-e8f2-537e-4f6c-d104768a1214"

async def main():
    print("[1] Scanning...")
    devices = await BleakScanner.discover(timeout=10.0, return_adv=True)
    device = None
    for d, adv in devices.values():
        if d.name == "OpenGlass":
            device = d
            break
    if not device:
        print("NOT FOUND")
        return

    print(f"[2] Found: {device.name} [{device.address}]")

    print("[3] Connecting...")
    client = BleakClient(device.address, timeout=30.0)
    await client.connect()
    print(f"[4] Connected: {client.is_connected}")

    print("[5] Discovering services...")
    await asyncio.sleep(1)
    services = client.services
    for s in services:
        print(f"  Service: {s.uuid}")

    print("[6] Subscribing to photo data...")
    def on_data(_h, data):
        print(f"  DATA: {len(data)} bytes")
    await client.start_notify(PHOTO_DATA_UUID, on_data)

    print("[7] Waiting 15 seconds (does connection stay?)...")
    for i in range(15):
        await asyncio.sleep(1)
        print(f"  ...{i+1}s  connected={client.is_connected}")
        if not client.is_connected:
            print("[FAIL] Disconnected during idle wait!")
            break

    if client.is_connected:
        print("[8] Now writing photo control (0x05)...")
        control_char = None
        for s in services:
            for c in s.characteristics:
                if c.uuid == "19b10006-e8f2-537e-4f6c-d104768a1214":
                    control_char = c
        if control_char:
            await client.write_gatt_char(control_char, b'\x05', response=False)
            print("[9] Wrote control. Waiting 5 more seconds...")
            for i in range(5):
                await asyncio.sleep(1)
                print(f"  ...{i+1}s  connected={client.is_connected}")
        else:
            print("Control char not found!")

    print(f"[10] Final status: connected={client.is_connected}")
    await client.disconnect()

asyncio.run(main())
