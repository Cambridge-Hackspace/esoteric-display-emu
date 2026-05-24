# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "requests",
# ]
# ///

import argparse
import os
import sys
import requests
import subprocess
import shlex

def get_headers():
    """Retrieves the API key from the environment and formats the auth headers."""
    api_key = os.environ.get("API_KEY")
    if not api_key:
        print("Error: API_KEY environment variable is not set.")
        sys.exit(1)
    
    return {
        "x-api-key": api_key,
        "Content-Type": "application/json"
    }

def list_displays(base_url):
    """Fetches and prints the list of available displays."""
    url = f"{base_url}/api/displays"
    print(f"> Fetching displays from {url}...")
    
    try:
        response = requests.get(url, headers=get_headers(), timeout=10)
        response.raise_for_status()
        data = response.json()
        
        displays = data.get("data", [])
        if not displays:
            print("No displays found.")
            return

        print("\nAvailable Displays:")
        print("-" * 50)
        print(f"{'ID':<5} | {'Label':<25} | {'IP Address':<15}")
        print("-" * 50)
        for d in displays:
            print(f"{d.get('id', 'N/A'):<5} | {d.get('label', 'N/A'):<25} | {d.get('ip_address', 'N/A'):<15}")
        print("-" * 50)

    except requests.exceptions.RequestException as e:
        print(f"Error fetching displays: {e}")
        sys.exit(1)

def open_stream(base_url, display_ids):
    """Requests a new UDP stream for the given display IDs and returns the port."""
    url = f"{base_url}/api/streams"
    payload = {"display_ids": display_ids}
    
    try:
        response = requests.post(url, json=payload, headers=get_headers(), timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if not data.get("success"):
            print(f"API rejected the stream request: {data.get('message')}")
            sys.exit(1)
            
        port = data.get("port")
        if not port:
            print("Error: API returned success but no port was provided.")
            sys.exit(1)
            
        print(f"> Successfully opened UDP stream on port {port}.")
        return port

    except requests.exceptions.RequestException as e:
        print(f"Error opening stream: {e}")
        sys.exit(1)

def close_stream(base_url, port):
    """Closes an active UDP stream by port."""
    url = f"{base_url}/api/streams/{port}"
    print(f"\n> Cleaning up: Closing stream on port {port}...")
    
    try:
        response = requests.delete(url, headers=get_headers(), timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if data.get("success"):
            print("> Stream successfully closed.")
        else:
            print(f"Warning: API failed to close stream: {data.get('message')}")
            
    except requests.exceptions.RequestException as e:
        print(f"Error closing stream: {e}")

def run_pass_thru(base_url, command_template, display_ids):
    """Opens stream, runs wrapped command, and reliably closes stream."""
    if not display_ids:
        print("Error: --display-ids is required when using --pass-thru")
        sys.exit(1)
        
    port = open_stream(base_url, display_ids)
    
    # Inject the dynamic port into the command string
    try:
        formatted_command = command_template.format(port=port)
    except KeyError as e:
        print(f"Error: Invalid placeholder in command. Make sure to use {{port}}. Missing: {e}")
        close_stream(base_url, port)
        sys.exit(1)

    print(f"\n> Executing pass-thru command:\n$ {formatted_command}\n")
    
    # Use shlex to safely split the command string into a list for subprocess
    cmd_args = shlex.split(formatted_command)
    
    try:
        # Pass control to the child process (stdout/stderr will flow directly to the terminal)
        subprocess.run(cmd_args, check=True)
    except subprocess.CalledProcessError as e:
        print(f"\n> Target command exited with non-zero status: {e.returncode}")
    except KeyboardInterrupt:
        # Let the user gracefully interrupt the child process without breaking the wrapper
        pass
    except Exception as e:
        print(f"\n> Unexpected error executing command: {e}")
    finally:
        # ALWAYS guarantee the stream is closed, regardless of crashes or user interrupts
        close_stream(base_url, port)

def main():
    parser = argparse.ArgumentParser(description="Wrapper script to manage dynamic DDP API streams.")
    parser.add_argument("target", help="The API host and port (e.g., 192.168.1.50:8080)")
    
    # Group modes so they are mutually exclusive
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list-displays", action="store_true", help="List all available display IDs and labels")
    group.add_argument("--pass-thru", type=str, help="Command to run. Use {port} to inject the dynamic port.")
    
    # Required only for --pass-thru
    parser.add_argument("--display-ids", type=str, help="Comma-separated list of display IDs to stream to (e.g., 1,2,5)")
    
    args = parser.parse_args()

    # Format the base URL, assuming HTTP.
    target = args.target if args.target.startswith("http") else f"http://{args.target}"

    if args.list_displays:
        list_displays(target)
    elif args.pass_thru:
        # Parse display IDs from comma-separated string to list of ints
        try:
            display_ids = [int(x.strip()) for x in args.display_ids.split(",")]
        except (ValueError, AttributeError):
            print("Error: --display-ids must be a comma-separated list of integers (e.g., 1,2,5)")
            sys.exit(1)
            
        run_pass_thru(target, args.pass_thru, display_ids)

if __name__ == "__main__":
    main()
