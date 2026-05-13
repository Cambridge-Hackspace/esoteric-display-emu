#!/usr/bin/env python3
import argparse
import socket
import sys
import time
import select
import termios
import tty

DDP_HEADER = bytearray([
    0x41, 0x00, 0x00, 0x01,
    0x00, 0x00, 0x00, 0x00,
    0x01, 0x2C
])

DISPLAY_WIDTH = 30
DISPLAY_HEIGHT = 10

PLAYER_BRIGHTNESS = 100
BALL_BRIGHTNESS = 60


def read_key():
    if not select.select([sys.stdin], [], [], 0)[0]:
        return None

    ch = sys.stdin.read(1)

    if ch == "\x1b":
        if select.select([sys.stdin], [], [], 0.01)[0]:
            ch2 = sys.stdin.read(1)

            if ch2 == "[" and select.select([sys.stdin], [], [], 0.01)[0]:
                ch3 = sys.stdin.read(1)

                if ch3 == "A":
                    return "up"
                if ch3 == "B":
                    return "down"
                if ch3 == "C":
                    return "right"
                if ch3 == "D":
                    return "left"

    if ch in ("w", "W"):
        return "up"
    if ch in ("s", "S"):
        return "down"
    if ch in ("a", "A"):
        return "left"
    if ch in ("d", "D"):
        return "right"
    if ch in ("q", "Q"):
        return "q"

    return None


def clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def clear_pixels():
    return [
        [0 for _ in range(DISPLAY_WIDTH)]
        for _ in range(DISPLAY_HEIGHT)
    ]


def draw_pixel(pixel_array, x, y, brightness):
    pixel_array[y][x] = brightness


def update_player(player, key):
    if key == "up":
        player["y"] -= 1
    elif key == "down":
        player["y"] += 1
    elif key == "left":
        player["x"] -= 1
    elif key == "right":
        player["x"] += 1

    player["x"] = clamp(player["x"], 0, DISPLAY_WIDTH - 1)
    player["y"] = clamp(player["y"], 0, DISPLAY_HEIGHT - 1)


def update_ball(ball):
    ball["x"] += ball["dx"]
    ball["y"] += ball["dy"]

    if ball["x"] <= 0:
        ball["x"] = 0
        ball["dx"] *= -1
    elif ball["x"] >= DISPLAY_WIDTH - 1:
        ball["x"] = DISPLAY_WIDTH - 1
        ball["dx"] *= -1

    if ball["y"] <= 0:
        ball["y"] = 0
        ball["dy"] *= -1
    elif ball["y"] >= DISPLAY_HEIGHT - 1:
        ball["y"] = DISPLAY_HEIGHT - 1
        ball["dy"] *= -1


def build_payload(pixel_array):
    payload = bytearray(DISPLAY_WIDTH * DISPLAY_HEIGHT)

    for y in range(DISPLAY_HEIGHT):
        for x in range(DISPLAY_WIDTH):
            payload[y * DISPLAY_WIDTH + x] = pixel_array[y][x]

    return payload


def main():
    parser = argparse.ArgumentParser(description="Stream player and bouncing ball via DDP.")
    parser.add_argument("target", help="Target IP:PORT, e.g. 192.168.1.129:4048")
    args = parser.parse_args()

    try:
        ip, port_str = args.target.split(":")
        port = int(port_str)
    except ValueError:
        print("Error: Target must be in the format IP:PORT, e.g. 192.168.1.129:4048")
        sys.exit(1)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    player = {
        "x": DISPLAY_WIDTH // 2,
        "y": DISPLAY_HEIGHT // 2
    }

    ball = {
        "x": 3,
        "y": 3,
        "dx": 1,
        "dy": 1
    }

    print(f"> sending DDP stream to {ip}:{port}...")
    print("> use WASD or arrow keys to move")
    print("> press Q or CTRL+C to stop")

    old_terminal_settings = termios.tcgetattr(sys.stdin)

    try:
        tty.setcbreak(sys.stdin.fileno())

        while True:
            key = read_key()

            if key == "q":
                break

            update_player(player, key)
            update_ball(ball)

            pixel_array = clear_pixels()

            draw_pixel(pixel_array, ball["x"], ball["y"], BALL_BRIGHTNESS)
            draw_pixel(pixel_array, player["x"], player["y"], PLAYER_BRIGHTNESS)

            payload = build_payload(pixel_array)
            packet = DDP_HEADER + payload

            sock.sendto(packet, (ip, port))

            time.sleep(0.05)

    except KeyboardInterrupt:
        print("\n> goodbye!")

    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_terminal_settings)
        sock.close()


if __name__ == "__main__":
    main()
