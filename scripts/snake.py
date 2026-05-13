#!/usr/bin/env python3
import argparse
import random
import select
import socket
import sys
import termios
import time
import tty

DDP_HEADER = bytearray([
    0x41, 0x00, 0x00, 0x01,
    0x00, 0x00, 0x00, 0x00,
    0x01, 0x2C
])

DISPLAY_WIDTH = 30
DISPLAY_HEIGHT = 10

SNAKE_BRIGHTNESS = 100
FOOD_BRIGHTNESS = 50

FRAME_DELAY = 0.12


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


def clear_pixels():
    return [
        [0 for _ in range(DISPLAY_WIDTH)]
        for _ in range(DISPLAY_HEIGHT)
    ]


def draw_pixel(pixel_array, x, y, brightness):
    if 0 <= x < DISPLAY_WIDTH and 0 <= y < DISPLAY_HEIGHT:
        pixel_array[y][x] = brightness


def build_payload(pixel_array):
    payload = bytearray(DISPLAY_WIDTH * DISPLAY_HEIGHT)

    for y in range(DISPLAY_HEIGHT):
        for x in range(DISPLAY_WIDTH):
            payload[y * DISPLAY_WIDTH + x] = pixel_array[y][x]

    return payload


def get_direction_delta(direction):
    if direction == "up":
        return 0, -1
    if direction == "down":
        return 0, 1
    if direction == "left":
        return -1, 0
    if direction == "right":
        return 1, 0

    return 0, 0


def is_opposite_direction(current, new):
    opposites = {
        "up": "down",
        "down": "up",
        "left": "right",
        "right": "left"
    }

    return opposites[current] == new


def spawn_food(snake):
    snake_cells = set((cell["x"], cell["y"]) for cell in snake)

    available_cells = []

    for y in range(DISPLAY_HEIGHT):
        for x in range(DISPLAY_WIDTH):
            if (x, y) not in snake_cells:
                available_cells.append({"x": x, "y": y})

    if not available_cells:
        return None

    return random.choice(available_cells)


def reset_game():
    start_x = DISPLAY_WIDTH // 2
    start_y = DISPLAY_HEIGHT // 2

    snake = [
        {"x": start_x, "y": start_y},
        {"x": start_x - 1, "y": start_y},
        {"x": start_x - 2, "y": start_y}
    ]

    direction = "right"
    food = spawn_food(snake)

    return snake, direction, food


def update_snake(snake, direction, food):
    dx, dy = get_direction_delta(direction)

    head = snake[0]

    new_head = {
        "x": head["x"] + dx,
        "y": head["y"] + dy
    }

    hit_wall = (
        new_head["x"] < 0 or
        new_head["x"] >= DISPLAY_WIDTH or
        new_head["y"] < 0 or
        new_head["y"] >= DISPLAY_HEIGHT
    )

    if hit_wall:
        return False, food

    hit_self = any(
        new_head["x"] == cell["x"] and new_head["y"] == cell["y"]
        for cell in snake
    )

    if hit_self:
        return False, food

    snake.insert(0, new_head)

    ate_food = (
        food is not None and
        new_head["x"] == food["x"] and
        new_head["y"] == food["y"]
    )

    if ate_food:
        food = spawn_food(snake)
    else:
        snake.pop()

    return True, food


def draw_game(pixel_array, snake, food):
    if food is not None:
        draw_pixel(pixel_array, food["x"], food["y"], FOOD_BRIGHTNESS)

    for index, cell in enumerate(snake):
        brightness = SNAKE_BRIGHTNESS if index == 0 else 75
        draw_pixel(pixel_array, cell["x"], cell["y"], brightness)


def main():
    parser = argparse.ArgumentParser(description="Play Snake on a DDP display.")
    parser.add_argument("target", help="Target IP:PORT, e.g. 192.168.1.129:4048")
    args = parser.parse_args()

    try:
        ip, port_str = args.target.split(":")
        port = int(port_str)
    except ValueError:
        print("Error: Target must be in the format IP:PORT, e.g. 192.168.1.129:4048")
        sys.exit(1)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    snake, direction, food = reset_game()

    print(f"> sending DDP snake game to {ip}:{port}...")
    print("> use WASD or arrow keys to move")
    print("> press Q or CTRL+C to stop")
    print("> crashing resets the game")

    old_terminal_settings = termios.tcgetattr(sys.stdin)

    try:
        tty.setcbreak(sys.stdin.fileno())

        while True:
            key = read_key()

            if key == "q":
                break

            if key in ("up", "down", "left", "right"):
                if not is_opposite_direction(direction, key):
                    direction = key

            alive, food = update_snake(snake, direction, food)

            if not alive:
                snake, direction, food = reset_game()

            pixel_array = clear_pixels()
            draw_game(pixel_array, snake, food)

            payload = build_payload(pixel_array)
            packet = DDP_HEADER + payload

            sock.sendto(packet, (ip, port))

            time.sleep(FRAME_DELAY)

    except KeyboardInterrupt:
        print("\n> goodbye!")

    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_terminal_settings)
        sock.close()


if __name__ == "__main__":
    main()
