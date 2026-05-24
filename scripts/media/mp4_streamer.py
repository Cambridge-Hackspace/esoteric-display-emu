# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "opencv-python",
#     "pygame",
#     "numpy",
#     "imageio-ffmpeg",
#     "librosa",
#     "soundfile",
#     "windows-curses; sys_platform == 'win32'",
# ]
# ///

import argparse
import socket
import sys
import time
import tempfile
import os
import subprocess
import curses

import cv2
import pygame
import imageio_ffmpeg
import numpy as np
import librosa

# --- DDP Helper Functions ---
def build_ddp_header(data_length, is_grayscale):
    """Builds a standard DDP v1 header for the given payload size."""
    # Byte 2: Data type. 
    # 0x0B -> 8-bit RGB (TTT=001, SSS=011)
    # 0x23 -> 8-bit Grayscale (TTT=100, SSS=011)
    data_type = 0x23 if is_grayscale else 0x0B
    
    header = bytearray([
        0x41, 0x00, data_type, 0x01, 
        0x00, 0x00, 0x00, 0x00, 
        (data_length >> 8) & 0xFF,
        data_length & 0xFF
    ])
    return header

def resize_and_pad(frame, target_w, target_h):
    """Resizes a BGR image to fit within target dimensions, padding with black."""
    h, w = frame.shape[:2]
    scale = min(target_w / w, target_h / h)
    new_w, new_h = int(w * scale), int(h * scale)

    resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)

    top = (target_h - new_h) // 2
    bottom = target_h - new_h - top
    left = (target_w - new_w) // 2
    right = target_w - new_w - left

    padded = cv2.copyMakeBorder(resized, top, bottom, left, right, cv2.BORDER_CONSTANT, value=[0, 0, 0])
    return padded

# --- Audio Extraction ---
def extract_audio(video_path, output_wav_path):
    """Extracts audio from an MP4 file using the embedded ffmpeg binary."""
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    command = [
        ffmpeg_exe, 
        "-y",               
        "-i", video_path,   
        "-vn",              
        "-acodec", "pcm_s16le", 
        "-ar", "44100",     
        "-ac", "2",         
        output_wav_path
    ]
    subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

# --- Main App & TUI ---
class StreamerApp:
    def __init__(self, target_ip, target_port, mp4_path, width, height, canvas_width, canvas_height, is_grayscale):
        self.ip = target_ip
        self.port = target_port
        self.mp4_path = mp4_path
        self.width = width
        self.height = height
        self.canvas_width = canvas_width
        self.canvas_height = canvas_height
        self.is_grayscale = is_grayscale

        # Socket setup
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # Video setup
        self.cap = cv2.VideoCapture(self.mp4_path)
        if not self.cap.isOpened():
            raise ValueError(f"Failed to open video: {self.mp4_path}")
        
        self.fps = self.cap.get(cv2.CAP_PROP_FPS)
        self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.duration_sec = self.total_frames / self.fps if self.fps > 0 else 0

        # DDP setup
        bytes_per_pixel = 1 if self.is_grayscale else 3
        self.payload_size = self.canvas_width * self.canvas_height * bytes_per_pixel
        self.ddp_header = build_ddp_header(self.payload_size, self.is_grayscale)

        # Temp directory for audio
        self.temp_dir = tempfile.TemporaryDirectory()
        self.audio_path = os.path.join(self.temp_dir.name, "audio.wav")

        # Audio Analytics
        self.beat_times = np.array([])

        # Playback State
        self.state = "STOPPED" 
        self.base_time = 0.0
        self.time_offset = 0.0
        self.current_frame_idx = 0

    def format_time(self, seconds):
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        millis = int((seconds * 100) % 100)
        return f"{mins:02d}:{secs:02d}.{millis:02d}"

    def run(self, stdscr):
        curses.curs_set(0)
        stdscr.nodelay(True)
        stdscr.timeout(10) 

        pygame.mixer.init(frequency=44100, size=-16, channels=2)
        
        # Phase 1: Extract Audio
        stdscr.clear()
        stdscr.addstr(0, 0, "> Extracting audio from MP4...", curses.A_BOLD)
        stdscr.refresh()
        
        try:
            extract_audio(self.mp4_path, self.audio_path)
        except Exception as e:
            stdscr.addstr(2, 0, f"Audio extraction failed: {e}")
            stdscr.refresh()
            time.sleep(2)
            return

        # Phase 2: Analyze Beats
        stdscr.addstr(1, 0, "> Analyzing audio beats... This may take a moment.", curses.A_BOLD)
        stdscr.refresh()

        try:
            y, sr = librosa.load(self.audio_path, sr=None)
            _, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
            self.beat_times = librosa.frames_to_time(beat_frames, sr=sr)
            pygame.mixer.music.load(self.audio_path)
        except Exception as e:
            stdscr.addstr(3, 0, f"Beat detection failed: {e}")
            stdscr.refresh()
            time.sleep(2)
        
        # Phase 3: Auto-start playback
        self._start_playback()

        try:
            while True:
                # 1. Handle Key Input
                key = stdscr.getch()
                if key != -1:
                    char = chr(key).lower() if key < 256 else ''
                    if char == 'q':
                        break
                    elif char == ' ' or char == 'p':
                        if self.state == "PLAYING":
                            self._pause_playback()
                        else:
                            self._start_playback()
                    elif char == 's':
                        self._stop_playback()
                    elif char == 'r':
                        self._rewind_playback()

                # 2. Update Playback Logic
                current_time = 0.0
                if self.state == "PLAYING":
                    current_time = (time.time() - self.base_time) + self.time_offset
                    target_frame_idx = int(current_time * self.fps)

                    if target_frame_idx >= self.total_frames:
                        self._stop_playback()
                        current_time = self.duration_sec
                    
                    while self.current_frame_idx < target_frame_idx and self.current_frame_idx < self.total_frames:
                        ret, frame = self.cap.read()
                        if not ret:
                            break
                        self.current_frame_idx += 1
                        
                        if self.current_frame_idx == target_frame_idx:
                            self._send_frame(frame, current_time)
                else:
                    current_time = self.time_offset

                # 3. Render TUI
                self._draw_tui(stdscr, current_time)

        finally:
            pygame.mixer.quit()
            self.cap.release()
            self.temp_dir.cleanup()

    def _get_beat_bg_color(self, current_time):
        """Determines the canvas background color based on the audio beats."""
        if len(self.beat_times) == 0:
            return (0, 0, 0)

        # Calculate pulsing intensity based on distance to closest beat
        idx = np.searchsorted(self.beat_times, current_time)
        candidates = []
        if idx < len(self.beat_times):
            candidates.append(self.beat_times[idx])
        if idx > 0:
            candidates.append(self.beat_times[idx - 1])
        
        closest_beat = min(candidates, key=lambda b: abs(b - current_time))
        dist = abs(current_time - closest_beat)
        
        fade_duration = 0.15 # 150ms fade in/out
        intensity = 0.0
        if dist < fade_duration:
            intensity = 1.0 - (dist / fade_duration)

        if intensity <= 0.0:
            return (0, 0, 0)

        if self.is_grayscale:
            # Grayscale mode: pulse white
            val = int(255 * intensity)
            return (val, val, val) # BGR
        else:
            # RGB mode: pulse through colors on each beat
            passed_beats = np.searchsorted(self.beat_times, current_time, side='right')
            if passed_beats == 0:
                return (0, 0, 0)
                
            # Define colors in BGR
            bgr_colors = [
                (0, 0, 255),   # Red
                (0, 255, 0),   # Green
                (255, 0, 0),   # Blue
                (0, 255, 255), # Yellow
                (255, 255, 0), # Cyan
                (255, 0, 255)  # Magenta
            ]
            color_idx = (passed_beats - 1) % len(bgr_colors)
            base_color = bgr_colors[color_idx]
            
            return (
                int(base_color[0] * intensity),
                int(base_color[1] * intensity),
                int(base_color[2] * intensity)
            )

    def _send_frame(self, frame, current_time):
        # 1. Determine background color based on beat
        bg_color = self._get_beat_bg_color(current_time)

        # 2. Create the canvas (using BGR color space natively for OpenCV)
        canvas = np.full((self.canvas_height, self.canvas_width, 3), bg_color, dtype=np.uint8)

        # 3. Resize and pad the video frame to exact width/height constraints
        padded_vid = resize_and_pad(frame, self.width, self.height)

        # 4. Paste the video exactly in the center of the canvas
        x_off = (self.canvas_width - self.width) // 2
        y_off = (self.canvas_height - self.height) // 2
        canvas[y_off:y_off+self.height, x_off:x_off+self.width] = padded_vid

        # 5. Format color space for DDP payload
        if self.is_grayscale:
            processed = cv2.cvtColor(canvas, cv2.COLOR_BGR2GRAY)
        else:
            processed = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
            
        payload = processed.tobytes()
        packet = self.ddp_header + payload
        self.sock.sendto(packet, (self.ip, self.port))

    def _start_playback(self):
        if self.state == "PLAYING": return
        if self.state == "STOPPED":
            pygame.mixer.music.play()
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            self.current_frame_idx = 0
            self.time_offset = 0.0
        elif self.state == "PAUSED":
            pygame.mixer.music.unpause()
            
        self.base_time = time.time()
        self.state = "PLAYING"

    def _pause_playback(self):
        if self.state != "PLAYING": return
        self.time_offset += time.time() - self.base_time
        pygame.mixer.music.pause()
        self.state = "PAUSED"

    def _stop_playback(self):
        pygame.mixer.music.stop()
        self.time_offset = 0.0
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        self.current_frame_idx = 0
        self.state = "STOPPED"

    def _rewind_playback(self):
        self.time_offset = 0.0
        self.base_time = time.time()
        pygame.mixer.music.play() 
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        self.current_frame_idx = 0
        if self.state != "PLAYING":
            self.state = "PLAYING"

    def _draw_tui(self, stdscr, current_time):
        stdscr.erase()
        
        # Header
        stdscr.addstr(0, 0, "DDP MP4 Streamer (Beat Analyzer Edition)", curses.A_BOLD | curses.A_UNDERLINE)
        
        # Details
        stdscr.addstr(2, 0, f"Target: ", curses.A_BOLD)
        stdscr.addstr(f"{self.ip}:{self.port}")
        
        stdscr.addstr(3, 0, f"File:   ", curses.A_BOLD)
        stdscr.addstr(f"{os.path.basename(self.mp4_path)}")
        
        color_mode = "Grayscale (0x23)" if self.is_grayscale else "RGB (0x0B)"
        stdscr.addstr(4, 0, f"Canvas: ", curses.A_BOLD)
        stdscr.addstr(f"{self.canvas_width}x{self.canvas_height} ({color_mode})")

        stdscr.addstr(5, 0, f"Video:  ", curses.A_BOLD)
        stdscr.addstr(f"{self.width}x{self.height} (Centered)")

        # Playback Status
        status_color = curses.A_REVERSE if self.state == "PLAYING" else curses.A_DIM
        stdscr.addstr(7, 0, f" {self.state} ", status_color)
        
        # Time / Progress
        time_str = f"{self.format_time(current_time)} / {self.format_time(self.duration_sec)}"
        stdscr.addstr(7, 12, time_str)

        # Progress bar
        bar_width = 40
        progress = current_time / self.duration_sec if self.duration_sec > 0 else 0
        filled = int(progress * bar_width)
        bar = "=" * filled + "-" * (bar_width - filled)
        stdscr.addstr(8, 0, f"[{bar}]")

        # Controls
        stdscr.addstr(10, 0, "Controls:", curses.A_BOLD)
        stdscr.addstr(11, 0, "[SPACE] or [P] - Play/Pause")
        stdscr.addstr(12, 0, "[R] - Rewind")
        stdscr.addstr(13, 0, "[S] - Stop")
        stdscr.addstr(14, 0, "[Q] - Quit")

        stdscr.refresh()

def main():
    parser = argparse.ArgumentParser(description="Stream an MP4 over DDP with beat-reactive canvas & local audio.")
    parser.add_argument("target", help="Target IP:PORT (e.g. 192.168.1.129:4048)")
    parser.add_argument("mp4_path", help="Path to the MP4 file")
    parser.add_argument("width", type=int, help="Video width (pixels)")
    parser.add_argument("height", type=int, help="Video height (pixels)")
    parser.add_argument("--canvas-width", type=int, help="Overall canvas width (defaults to video width)")
    parser.add_argument("--canvas-height", type=int, help="Overall canvas height (defaults to video height)")
    parser.add_argument("--grayscale", action="store_true", help="Convert entire canvas to grayscale")
    
    args = parser.parse_args()

    # Apply defaults if canvas dimensions are missing
    canvas_w = args.canvas_width if args.canvas_width is not None else args.width
    canvas_h = args.canvas_height if args.canvas_height is not None else args.height

    # Validate canvas constraints
    if canvas_w < args.width:
        sys.exit(f"Error: --canvas-width ({canvas_w}) must be greater than or equal to video width ({args.width}).")
    if canvas_h < args.height:
        sys.exit(f"Error: --canvas-height ({canvas_h}) must be greater than or equal to video height ({args.height}).")

    # Parse target
    try:
        ip, port_str = args.target.split(":")
        port = int(port_str)
    except ValueError:
        print("Error: Target must be in the exact format IP:PORT")
        sys.exit(1)

    if not os.path.exists(args.mp4_path):
        print(f"Error: File not found: {args.mp4_path}")
        sys.exit(1)

    app = StreamerApp(ip, port, args.mp4_path, args.width, args.height, canvas_w, canvas_h, args.grayscale)
    curses.wrapper(app.run)

if __name__ == "__main__":
    main()
