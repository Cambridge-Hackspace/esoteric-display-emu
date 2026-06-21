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
from PIL import Image, ImageDraw

# Audio Constants
CHUNK = 1024
RATE = 44100

# Shared state for the equalizer display
state = {
    "running": True,
    "bars": np.array([]) # Will be populated with heights per column
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

def audio_listener(device_index, width, height):
    """Background thread to listen to live audio and map FFT bins to equalizer bars."""
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

    # Using the first 256 bins of the FFT (approx 0 Hz to 11000 Hz)
    max_bins = 256
    
    # Tuning variables for the visualizer
    MIN_LOG = 3.0  # Noise floor threshold
    MAX_LOG = 6.5  # Max volume ceiling
    SMOOTHING = 0.6 # Higher = slower falloff, less flicker

    while state["running"]:
        try:
            data = stream.read(CHUNK, exception_on_overflow=False)
            samples = np.frombuffer(data, dtype=np.int16)
            
            # 1. Run an FFT to split the audio into frequency bins
            fft_data = np.abs(np.fft.rfft(samples))
            
            # 2. Isolate target frequencies
            fft_data = fft_data[:max_bins]
            
            # 3. Split the remaining bins into chunks corresponding to the matrix width
            bands = np.array_split(fft_data, width)
            
            # 4. Calculate energy per frequency band
            energies = np.array([np.mean(band) for band in bands])
            
            # 5. Convert to logarithmic scale for natural visual dynamics
            log_energies = np.log10(energies + 1)
            
            # 6. Normalize and scale to the matrix height
            normalized = np.clip((log_energies - MIN_LOG) / (MAX_LOG - MIN_LOG), 0.0, 1.0)
            target_bars = normalized * height
            
            # 7. Apply smoothing (exponential moving average)
            if len(state["bars"]) != width:
                state["bars"] = target_bars
            else:
                state["bars"] = (state["bars"] * SMOOTHING) + (target_bars * (1.0 - SMOOTHING))
                
        except Exception as e:
            pass

    stream.stop_stream()
    stream.close()
    p.terminate()

def main():
    parser = argparse.ArgumentParser(description="Realtime DDP audio equalizer.")
    parser.add_argument("target", nargs='?', help="Target IP:PORT (e.g. 192.168.1.129:4048)")
    parser.add_argument("--width", type=int, default=30, help="Matrix width (default: 30)")
    parser.add_argument("--height", type=int, default=10, help="Matrix height (default: 10)")
    parser.add_argument("--speed", type=float, default=0.02, help="Delay between frames (default: 0.02)")
    parser.add_argument("--device", type=int, default=None, help="Audio input device index")
    parser.add_argument("--list-devices", action="store_true", help="List audio input devices and exit")
    args = parser.parse_args()

    if args.list_devices:
        list_audio_devices()
        sys.exit(0)

    if not args.target:
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

    # Initialize bars array based on user's matrix width
    state["bars"] = np.zeros(args.width)

    # Start audio thread
    print("> Starting audio listener...")
    audio_thread = threading.Thread(target=audio_listener, args=(args.device, args.width, args.height))
    audio_thread.start()

    print(f"> Streaming realtime equalizer to {ip}:{port}...")
    print("> Press CTRL+C to stop")

    try:
        while state["running"]:
            # 1. Create a blank physical frame canvas
            frame = Image.new('L', (args.width, args.height), color=0)
            draw = ImageDraw.Draw(frame)
            
            # 2. Draw the equalizer bars
            bars = state["bars"]
            for x in range(args.width):
                bar_h = int(bars[x])
                if bar_h > 0:
                    # Draw a vertical line from the bottom (args.height-1) upwards
                    draw.line([(x, args.height - 1), (x, args.height - bar_h)], fill=255)
            
            # 3. Ship it over DDP
            payload = bytearray(frame.getdata())
            packet = ddp_header + payload
            sock.sendto(packet, (ip, port))
            
            # 4. Wait before drawing next frame
            time.sleep(args.speed)

    except KeyboardInterrupt:
        print("\n> Shutting down...")
    finally:
        state["running"] = False
        audio_thread.join()
        print("> Goodbye!")

if __name__ == "__main__":
    main()
