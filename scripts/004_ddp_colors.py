#!/usr/bin/env python3
import argparse
import socket
import time
import sys
import colorsys

# byte 0: flags             = 0x41 (v1, push)
# byte 1: sequence          = 0x00 (ignore)
# byte 2: data type         = 0x0B (0000 1011 -> TTT=001 [RGB], SSS=011 [8-bit])
# byte 3: source identifier = 0x01
# bytes 4-7: data offset    = 0x00000000
# bytes 8-9: data length    = 0x0384 (900 bytes -> 30x10 pixels * 3 channels)
DDP_HEADER = bytearray([0x41, 0x00, 0x0B, 0x01, 0x00, 0x00, 0x00, 0x00, 0x03, 0x84])

def main():
    parser = argparse.ArgumentParser(description="Stream a sweeping RGB rainbow animation via DDP.")
    parser.add_argument("target", help="Target IP:PORT (e.g. 127.0.0.1:4048)")
    args = parser.parse_args()

    # Parse target IP and port
    try:
        ip, port_str = args.target.split(":")
        port = int(port_str)
    except ValueError:
        print("Error: Target must be in the exact format IP:PORT (e.g. 127.0.0.1:4048)")
        sys.exit(1)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    print(f"> sending RGB DDP stream to {ip}:{port}...")
    print(f"> press CTRL+C to stop")

    try:
        frame = 0
        while True:
            payload = bytearray(900)

            # 30 columns x 10 rows
            for y in range(10):
                for x in range(30):
                    # Sweeping diagonal rainbow animation
                    hue = (x * 0.05 + y * 0.05 + frame * 0.02) % 1.0
                    
                    # Convert HSV to RGB, scale to 0-255
                    r, g, b = [int(c * 255) for c in colorsys.hsv_to_rgb(hue, 1.0, 1.0)]
                    
                    # Calculate byte index (3 bytes per pixel)
                    idx = (y * 30 + x) * 3
                    payload[idx] = r
                    payload[idx + 1] = g
                    payload[idx + 2] = b

            packet = DDP_HEADER + payload
            sock.sendto(packet, (ip, port))

            frame += 1
            time.sleep(0.05) # ~20 FPS

    except KeyboardInterrupt:
        print("\n> goodbye!")

if __name__ == "__main__":
    main()
