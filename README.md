# Timelapse videos with your DuetWifi / Duet Ethernet / Duet 2 Maestro 3D printer!

## Requirements

  * DuetWifi or Duet Ethernet or Duet 2 Maestro controlled printer
    - RepRapFirmware v1.21 or v2 or v3 or higher
    - with enabled WiFi or Ethernet protocol
    - with enabled Telnet protocol: `M586 P2 S1` in `config.g`
    - **DOES NOT work in Duet+SBC mode!**
  * Raspberry Pi / Single-Board Computer on the same network as your Duet
    - with Python 3 and the `requests` package: `sudo apt install python3 python3-requests`
    - with ffmpeg: `sudo apt install ffmpeg`
  * Webcam that returns snapshot pictures (still image) via an URL
    - mjpg-streamer or similiar, e.g., `http://127.0.0.1:8080/?action=snapshot`
  * Slicer that can insert custom G-code for every new layer
    - for Cura you can use the `TimelapseLayerChange.py` post-processing script. Enable it in the post-processing GUI window, after restarting Cura and copying it into:
      - Linux: `~/.local/share/cura/<version>/scripts`
      - macOS: `~/Library/Application Support/cura/<version>/scripts`
      - Windows: `C:\Users\<username>\AppData\Roaming\cura\<version>\scripts`

## Usage
```
Take snapshot pictures of your Duet-based printer on every layer change and generate a timelapse video.

The filename of the timelapse video will have the starting print timestamp and g-code filename.
You can choose to disable the video generator and keep the individual snapshot files instead.
A new subfolder will be created with a timestamp and g-code filename for every new log_print.

This script connects via Telnet to your log_printer, make sure to enable it in your config.g:
    M586 P2 S1 ; enable Telnet

You need to inject the following G-Code before a new layer starts:
    M400 ; wait for all movement to complete
    M118 P4 S"LAYER CHANGE" ; take a picture
    G4 P500 ; wait a bit

If you are using Cura, you can use the TimelapseLayerChange.py script with the Cura Post-Processing plugin.
If you are using Simplify3D, you can enter the above commands in the "Layer Change Script" section of your process.
Slicer-generated z-hops might cause erronously taken pictures, use firmware-retraction with z-hop instead.

You can disable the video and render a timelapse movie manually with the program ffmpeg:
    $ ffmpeg -r 20 -y -pattern_type glob -i '*.jpg' -c:v libx264 output.mp4

positional arguments:
  folder            folder where all videos and snapshots will be collected, e.g., ~/timelapses
  duet_host         hostname or IP address of your Duet printer, e.g., mylog_printer.local or 192.168.1.42
  webcam_url        HTTP or HTTPS URL that returns a JPG picture, e.g., http://127.0.0.1:8080/?action=snapshot

optional arguments:
  -h, --help        show this help message and exit
  --debug           set the log level to debug
  --auth AUTH       HTTP Basic Auth if the webcam_url requires auth credentials, e.g., john:passw0rd
  --no-verify       disables HTTPS certificate verification
  --run-ffmpeg      run ffmpeg to generate the video after a print finishes
  --keep-snapshots  keep all JPG snapshots after running ffmpeg instead of deleting them
```

## Autostart on a Raspbarry Pi (or any modern Linux system)

* Copy `duet_timelapse.py` into `/usr/local/bin/`
* Make it executable: `sudo chmod +x /usr/local/bin/duet_timelapse.py`
* Copy `duet_timelapse.service` into `/etc/systmed/system/`
* Edit `/etc/systemd/system/duet_timelapse.service`
  - change the `ExecStart` line to include your config arguments
* Run these commands:
  - `sudo systemctl daemon-reload`
  - `sudo systemctl enable --now duet_timelapse.service`
* Check the that it started correctly:
  - `sudo systemctl status duet_timelapse.service`
* Check the logs:
  - `sudo journalctl -t duet_timelapse`

## Troubleshooting

* Do not run multiple instances of the `duet_timelapse.py` script!
  - The Telnet connection pool on the Duet board can most likely only handle one
  - Reset your Duet board to clear any potential connection errors.
