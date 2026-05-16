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
PLAYER_HEIGHT = 3

MIN_BALL_SPEED = 0.05
MAX_BALL_SPEED = 1.00
BALL_SPEED_STEP = 0.05


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
    if ch == "+":
        return "+"
    if ch == "-":
        return "-"

    return None


def clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def clear_pixels():
    return [
        [0 for _ in range(DISPLAY_WIDTH)]
        for _ in range(DISPLAY_HEIGHT)
    ]


def draw_pixel(pixel_array, x, y, brightness):
    if 0 <= x < DISPLAY_WIDTH and 0 <= y < DISPLAY_HEIGHT:
        pixel_array[y][x] = brightness


def get_player_cells(player):
    cells = []
    half_height = PLAYER_HEIGHT // 2

    for offset in range(-half_height, half_height + 1):
        cells.append({
            "x": player["x"],
            "y": player["y"] + offset
        })

    return cells


def draw_player(pixel_array, player):
    for cell in get_player_cells(player):
        draw_pixel(pixel_array, cell["x"], cell["y"], PLAYER_BRIGHTNESS)


def update_player(player, key):
    if key == "up":
        player["y"] -= 1
    elif key == "down":
        player["y"] += 1
    elif key == "left":
        player["x"] -= 1
    elif key == "right":
        player["x"] += 1

    half_height = PLAYER_HEIGHT // 2

    player["x"] = clamp(player["x"], 0, DISPLAY_WIDTH - 1)
    player["y"] = clamp(
        player["y"],
        half_height,
        DISPLAY_HEIGHT - 1 - half_height
    )


def update_ball_speed(ball, key):
    if key == "+":
        ball["speed"] = clamp(
            ball["speed"] + BALL_SPEED_STEP,
            MIN_BALL_SPEED,
            MAX_BALL_SPEED
        )
    elif key == "-":
        ball["speed"] = clamp(
            ball["speed"] - BALL_SPEED_STEP,
            MIN_BALL_SPEED,
            MAX_BALL_SPEED
        )


def ball_hits_player(ball, player):
    next_x = round(ball["x"])
    next_y = round(ball["y"])

    for cell in get_player_cells(player):
        if next_x == cell["x"] and next_y == cell["y"]:
            return True

    return False


def update_ball(ball, player):
    ball["x"] += ball["dx"] * ball["speed"]
    ball["y"] += ball["dy"] * ball["speed"]

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

    if ball_hits_player(ball, player):
        ball["dx"] *= -1

        if ball["x"] < player["x"]:
            ball["x"] = player["x"] - 1
        else:
            ball["x"] = player["x"] + 1


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
        "x": 3.0,
        "y": 3.0,
        "dx": 1,
        "dy": 1,
        "speed": 0.25
    }

    print(f"> sending DDP stream to {ip}:{port}...")
    print("> use WASD or arrow keys to move")
    print("> use + / - to adjust ball speed")
    print("> press Q or CTRL+C to stop")

    old_terminal_settings = termios.tcgetattr(sys.stdin)

    try:
        tty.setcbreak(sys.stdin.fileno())

        while True:
            key = read_key()

            if key == "q":
                break

            update_player(player, key)
            update_ball_speed(ball, key)
            update_ball(ball, player)

            pixel_array = clear_pixels()

            draw_pixel(
                pixel_array,
                round(ball["x"]),
                round(ball["y"]),
                BALL_BRIGHTNESS
            )

            draw_player(pixel_array, player)

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