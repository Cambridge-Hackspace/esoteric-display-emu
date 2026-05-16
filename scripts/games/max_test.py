#!/usr/bin/env python3
import argparse
import socket
import time
import math
import sys
import select


try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Error: Pillow library is required. Run 'pip install pillow'")
    sys.exit(1)

# byte 0: flags             = 0x41 (v1, push)
# byte 1: sequence          = 0x00 (ignore)
# byte 2: data type         = 0x00 (default)
# byte 3: source identifier = 0x01
# bytes 4-7: data offset    = 0x0x00000000
# bytes 8-9: data length    = 0x012C (300)
DDP_HEADER = bytearray([0x41, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x01, 0x2C])

DISPLAY_WIDTH = 30
DISPLAY_HEIGHT = 10


def read_key():
    """
    Non-blocking keyboard reader.

    Returns:
        "up", "down", "left", "right",
        "q", "+", "-", or None
    """
    if not select.select([sys.stdin], [], [], 0)[0]:
        return None

    ch = sys.stdin.read(1)

    # Arrow keys arrive as escape sequences:
    # Up    = ESC [ A
    # Down  = ESC [ B
    # Right = ESC [ C
    # Left  = ESC [ D
    if ch == "\x1b":
        if select.select([sys.stdin], [], [], 0.01)[0]:
            ch2 = sys.stdin.read(1)
            if ch2 == "[" and select.select([sys.stdin], [], [], 0.01)[0]:
                ch3 = sys.stdin.read(1)
                if ch3 == "A":
                    return "up"
                elif ch3 == "B":
                    return "down"
                elif ch3 == "C":
                    return "right"
                elif ch3 == "D":
                    return "left"

    if ch in ("w", "W"):
        return "up"
    elif ch in ("s", "S"):
        return "down"
    elif ch in ("a", "A"):
        return "left"
    elif ch in ("d", "D"):
        return "right"
    elif ch in ("q", "Q"):
        return "q"
    elif ch == "+":
        return "+"
    elif ch == "-":
        return "-"

    return None


def main():
    parser = argparse.ArgumentParser(description="Stream a sweeping sine wave animation via DDP.")
    parser.add_argument("target", help="Target IP:PORT (e.g. 192.168.1.129:4048)")
    args = parser.parse_args()

    # Parse target IP and port
    try:
        ip, port_str = args.target.split(":")
        port = int(port_str)
    except ValueError:
        print("Error: Target must be in the exact format IP:PORT (e.g. 192.168.1.129:4048)")
        sys.exit(1)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    print(f"> sending DDP stream to {ip}:{port}...")
    print(f"> press CTRL+C to stop")





    # frame = Image.new('L', (DISPLAY_WIDTH, DISPLAY_HEIGHT), color=0)

    # pixelArr = []

    pixelArray = [[0 for _ in range(30)] for _ in range(10)]

    playerOrigin = {
        "x": DISPLAY_WIDTH // 2,
        "y": DISPLAY_HEIGHT // 2
    }

    pixelArray[playerOrigin["y"]][playerOrigin["x"]] = 100
    pixelArray[5][5] = 100


    try:
        frame = 0
        while True:
            payload = bytearray(300)

            key = read_key()
            if key == "up":
               pixelArray[playerOrigin["y"]+1][playerOrigin["x"]+1] = 100
            elif key == "down":
                y += 1
            elif key == "left":
                x -= 1
            elif key == "right":
                x += 1

            # 30 columns x 10 rows
            for y in range(10):
                for x in range(30):
                    # print(f"(x,y): {x},{y}")
                    payload[y * 30 + x] = pixelArray[y][x]
                    # sweeping sine wave animation
                    # sine_val = math.sin((x - frame) * 0.4)
                    # brightness = int((sine_val + 1.0) * 50)
                    # payload[y * 30 + x] = brightness
                    # print(brightness)

            packet = DDP_HEADER + payload
            sock.sendto(packet, (ip, port))

            frame += 1
            time.sleep(0.05)

    except KeyboardInterrupt:
        print("\n> goodbye!")

if __name__ == "__main__":
    main()
