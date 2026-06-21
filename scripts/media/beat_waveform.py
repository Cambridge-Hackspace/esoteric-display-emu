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
import sys
import time
import threading
import collections
import queue
import numpy as np
import pyaudio
from PIL import Image, ImageDraw

# Audio Constants
CHUNK = 1024
RATE = 44100

# Shared state
state = {
    "running": True
}

def build_ddp_header(data_length):
    """Builds a standard DDP v1 header for 8-bit Grayscale payload."""
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

def audio_listener(device_index, audio_queue, enable_beats):
    """Listens to live audio and pushes amplitudes (and beat triggers) to a queue."""
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

    # Amplitude Tuning
    MAX_RMS = 6000.0  
    
    # Beat Detection Tuning
    history = []
    last_beat_time = time.time()
    DEBOUNCE_SEC = 0.15
    THRESHOLD_MULTIPLIER = 1.5 
    NOISE_FLOOR = 10000 

    while state["running"]:
        try:
            data = stream.read(CHUNK, exception_on_overflow=False)
            samples = np.frombuffer(data, dtype=np.int16)
            
            # 1. Calculate RMS for the waveform envelope
            rms = np.sqrt(np.mean(samples.astype(np.float32)**2))
            amp = min(1.0, (rms / MAX_RMS) ** 0.8)
            
            # 2. Calculate FFT for Bass-heavy beat detection (if enabled)
            is_beat = False
            if enable_beats:
                fft_data = np.abs(np.fft.rfft(samples))
                bass_bins = fft_data[0:7] # 0Hz to ~258Hz
                energy = np.mean(bass_bins)
                
                history.append(energy)
                if len(history) > int(RATE / CHUNK): # ~1 second of history
                    history.pop(0)
                    
                avg_energy = np.mean(history)
                now = time.time()
                
                # Check for an energy spike above the moving average
                if energy > avg_energy * THRESHOLD_MULTIPLIER and energy > NOISE_FLOOR:
                    if now - last_beat_time > DEBOUNCE_SEC:
                        is_beat = True
                        last_beat_time = now

            # 3. Push to the queue: sending both the amplitude and the beat trigger
            try:
                audio_queue.put_nowait((amp, is_beat))
            except queue.Full:
                pass # Drop frame if the display thread is lagging
                
        except Exception as e:
            pass

    stream.stop_stream()
    stream.close()
    p.terminate()

def main():
    parser = argparse.ArgumentParser(description="Synchronized scrolling DDP audio waveform.")
    parser.add_argument("target", nargs='?', help="Target IP:PORT (e.g. 192.168.1.129:4048)")
    parser.add_argument("--width", type=int, default=30, help="Matrix width (default: 30)")
    parser.add_argument("--height", type=int, default=10, help="Matrix height (default: 10)")
    parser.add_argument("--device", type=int, default=None, help="Audio input device index")
    parser.add_argument("--beats", action="store_true", help="Send a fast vertical spike across the screen on bass beats")
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

    # Queue & Waveform Setup
    audio_queue = queue.Queue(maxsize=10)
    wave_data = collections.deque([0.0] * args.width, maxlen=args.width)

    # Start audio thread
    print("> Starting audio listener...")
    audio_thread = threading.Thread(target=audio_listener, args=(args.device, audio_queue, args.beats))
    audio_thread.start()

    print(f"> Streaming synchronized scrolling waveform to {ip}:{port}...")
    if args.beats:
        print("> Beat spikes are ENABLED.")
    print("> Press CTRL+C to stop")

    center_y = args.height // 2
    
    # State for the fast-passing beat spikes
    active_spikes = []

    try:
        while state["running"]:
            try:
                # Block until we get new audio data to lock the visual framerate
                amp, is_beat = audio_queue.get(timeout=0.1)
                wave_data.append(amp)
                
                # Spawn a new spike at the far right of the matrix on a beat
                if is_beat:
                    active_spikes.append(float(args.width - 1))
                    
            except queue.Empty:
                continue
            
            # 1. Create a physical frame canvas (black background)
            frame = Image.new('L', (args.width, args.height), color=0)
            draw = ImageDraw.Draw(frame)
            
            # 2. Draw the rolling waveform from left to right
            for x, current_amp in enumerate(wave_data):
                if current_amp > 0.02:
                    offset = int(current_amp * (args.height / 2.0))
                    offset = max(0, offset) 
                    draw.line([(x, center_y - offset), (x, center_y + offset)], fill=255)
                else:
                    frame.putpixel((x, center_y), 255)
            
            # 3. Draw the fast-passing beat spikes and update their positions
            next_spikes = []
            for sx in active_spikes:
                # Draw a full-height vertical line, now 3 pixels wide
                draw.line([(int(sx), 0), (int(sx), args.height)], fill=255, width=3)
                
                # Move the spike left at 2x the speed of the waveform (2 pixels per frame)
                new_sx = sx - 2.0
                
                # Allow it to reach -3 so the 3px width scrolls completely off screen
                if new_sx >= -3:
                    next_spikes.append(new_sx)
                    
            active_spikes = next_spikes
            
            # 4. Ship it over DDP
            payload = bytearray(frame.getdata())
            packet = ddp_header + payload
            sock.sendto(packet, (ip, port))

    except KeyboardInterrupt:
        print("\n> Shutting down...")
    finally:
        state["running"] = False
        audio_thread.join()
        print("> Goodbye!")

if __name__ == "__main__":
    main()
