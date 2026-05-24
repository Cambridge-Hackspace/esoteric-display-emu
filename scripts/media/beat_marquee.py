# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "pyaudio",
#     "numpy",
#     "pillow",
# ]
# ///

import argparse
import socket
import time
import sys
import threading
import numpy as np
import pyaudio
from PIL import Image, ImageDraw, ImageFont

# Audio Constants
CHUNK = 1024
RATE = 44100

# Shared state for beat detection
state = {
    "flash_intensity": 0.0,
    "running": True
}

def build_ddp_header(data_length):
    """Builds a standard DDP v1 header for 8-bit Grayscale payload."""
    # Byte 2: Data type 0x23 -> 8-bit Grayscale (TTT=100, SSS=011)
    return bytearray([
        0x41, 0x00, 0x23, 0x01, 
        0x00, 0x00, 0x00, 0x00, 
        (data_length >> 8) & 0xFF,
        data_length & 0xFF
    ])

def list_audio_devices():
    """Prints all available PyAudio input devices."""
    p = pyaudio.PyAudio()
    print("\n--- Available Audio Input Devices ---")
    for i in range(p.get_device_count()):
        dev = p.get_device_info_by_index(i)
        if dev.get('maxInputChannels') > 0:
            print(f"[{i}] {dev.get('name')}")
    print("-------------------------------------\n")
    p.terminate()

def audio_listener(device_index):
    """Background thread to listen to live audio and trigger beats."""
    p = pyaudio.PyAudio()
    
    try:
        stream = p.open(format=pyaudio.paInt16,
                        channels=1,
                        rate=RATE,
                        input=True,
                        input_device_index=device_index,
                        frames_per_buffer=CHUNK)
    except Exception as e:
        print(f"\n[!] Failed to open audio stream: {e}")
        state["running"] = False
        return

    history = []
    last_beat_time = time.time()
    
    # Sensitivity tunings for FFT
    DEBOUNCE_SEC = 0.15
    THRESHOLD_MULTIPLIER = 1.5 
    NOISE_FLOOR = 10000 

    while state["running"]:
        try:
            data = stream.read(CHUNK, exception_on_overflow=False)
            samples = np.frombuffer(data, dtype=np.int16)
            
            # --- BASS-FOCUSED FFT LOGIC ---
            # 1. Run an FFT to split the audio into frequency bins
            fft_data = np.abs(np.fft.rfft(samples))
            
            # 2. Isolate the bass frequencies. 
            # With RATE=44100 and CHUNK=1024, each bin is roughly 43Hz.
            # Grabbing bins 0 through 6 gives us 0Hz to ~258Hz (Sub-bass to Low Mid).
            bass_bins = fft_data[0:7]
            
            # 3. Calculate our energy using ONLY the bass frequencies
            energy = np.mean(bass_bins)
            # ------------------------------
            
            history.append(energy)
            if len(history) > int(RATE / CHUNK): # Keep ~1 second of history
                history.pop(0)
                
            avg_energy = np.mean(history)
            
            # Beat logic: energy spikes above the moving average
            now = time.time()
            if energy > avg_energy * THRESHOLD_MULTIPLIER and energy > NOISE_FLOOR:
                if now - last_beat_time > DEBOUNCE_SEC:
                    state["flash_intensity"] = 1.0 # Trigger the flash
                    last_beat_time = now
                    
        except Exception as e:
            pass

    stream.stop_stream()
    stream.close()
    p.terminate()

def main():
    parser = argparse.ArgumentParser(description="Beat-reactive scrolling DDP marquee.")
    parser.add_argument("target", nargs='?', help="Target IP:PORT (e.g. 192.168.1.129:4048)")
    parser.add_argument("text", nargs='?', help="Text to scroll across the screen")
    parser.add_argument("--width", type=int, default=30, help="Matrix width (default: 30)")
    parser.add_argument("--height", type=int, default=10, help="Matrix height (default: 10)")
    parser.add_argument("--speed", type=float, default=0.05, help="Delay between frames (default: 0.05)")
    parser.add_argument("--device", type=int, default=None, help="Audio input device index")
    parser.add_argument("--list-devices", action="store_true", help="List audio input devices and exit")
    args = parser.parse_args()

    if args.list_devices:
        list_audio_devices()
        sys.exit(0)

    if not args.target or not args.text:
        parser.print_help()
        sys.exit(1)

    try:
        ip, port_str = args.target.split(":")
        port = int(port_str)
    except ValueError:
        print("Error: Target must be in the format IP:PORT")
        sys.exit(1)

    # DDP Setup
    payload_size = args.width * args.height
    ddp_header = build_ddp_header(payload_size)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    # Text Setup
    font = ImageFont.load_default()
    
    # Calculate the text bounding box to determine the required image width
    dummy_img = Image.new('L', (1, 1))
    draw = ImageDraw.Draw(dummy_img)
    bbox = draw.textbbox((0, 0), args.text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    text_img = Image.new('L', (text_width, args.height), color=0)
    text_draw = ImageDraw.Draw(text_img)
    
    # Center the text vertically to ensure it fits perfectly within the height
    y_offset = (args.height - text_height) // 2 - bbox[1]
    text_draw.text((0, y_offset), args.text, fill=255, font=font)

    # Start audio thread
    print("> Starting audio listener...")
    audio_thread = threading.Thread(target=audio_listener, args=(args.device,))
    audio_thread.start()

    print(f"> Streaming beat-reactive marquee to {ip}:{port}...")
    print("> Press CTRL+C to stop")

    x_pos = args.width
    flash_decay_rate = 0.15 # Higher number = faster fade back to black

    try:
        while state["running"]:
            # 1. Determine background color based on decaying flash intensity
            current_bg = int(255 * state["flash_intensity"])
            
            # 2. Create the physical frame canvas with the flash background
            frame = Image.new('L', (args.width, args.height), color=current_bg)
            
            # 3. Paste the text. Using text_img as the mask ensures the white 
            # text overrides the background, but the background shows through the empty space.
            frame.paste(text_img, (int(x_pos), 0), text_img)
            
            # 4. Ship it over DDP
            payload = bytearray(frame.getdata())
            packet = ddp_header + payload
            sock.sendto(packet, (ip, port))
            
            # 5. Advance scroll and decay the flash
            x_pos -= 1
            if x_pos < -text_width:
                x_pos = args.width
                
            state["flash_intensity"] = max(0.0, state["flash_intensity"] - flash_decay_rate)
            time.sleep(args.speed)

    except KeyboardInterrupt:
        print("\n> Shutting down...")
    finally:
        state["running"] = False
        audio_thread.join()
        print("> Goodbye!")

if __name__ == "__main__":
    main()
