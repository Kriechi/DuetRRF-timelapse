#!/usr/bin/env python3

import datetime
import json
import os
import requests
import socket
import sys
import textwrap
import time
import traceback
import urllib3
from requests.auth import HTTPBasicAuth

urllib3.disable_warnings()


def log_print(*msg, file=sys.stdout):
    print(datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S'), *msg, file=file)


class SimpleLineProtocol:
    def __init__(self, sock):
        self.socket = sock
        self.buffer = b''

    def write(self, msg):
        msg = msg.strip()
        msg += '\n'
        self.socket.sendall(msg.encode())

    def read_line(self):
        while b'\n' not in self.buffer:
            d = self.socket.recv(1024)
            if not d:
                raise socket.error()
            self.buffer = self.buffer + d

        i = self.buffer.find(b'\n')
        line = self.buffer[:i]
        self.buffer = self.buffer[i:].lstrip()
        return line

    def read_json_line(self):
        raw_lines = []
        line = b''
        while b'{' not in line and b'}' not in line:
            line = self.read_line()
            raw_lines.append(line)
        json_data = json.loads(line[line.find(b'{'):].decode())
        return json_data, raw_lines


def layer_changed(timelapse_folder, webcam_url, webcam_http_auth, webcam_https_verify):
    r = requests.get(webcam_url, auth=webcam_http_auth, verify=webcam_https_verify, timeout=5, stream=True)
    if r.status_code == 200:
        now = datetime.datetime.now()
        pic = os.path.join(timelapse_folder, now.strftime("%Y%m%dT%H%M%S") + ".jpg")
        with open(pic, 'wb') as f:
            for chunk in r:
                f.write(chunk)
        log_print("Picture taken!", pic)
    else:
        log_print('Failed to get timelapse snapshot.', file=sys.stderr)

def create_video(timelapse_path, current_log_print, snapshots_path, keep_snapshots):
    video_file = os.path.abspath(os.path.join(timelapse_path, current_log_print + ".mp4"))
    snapshots_files = snapshots_path + os.path.sep + "*.jpg"
    cmd = "ffmpeg -r 20 -y -pattern_type glob -i '" + snapshots_files + "' -vcodec libx264 " + video_file
    os.system(cmd)
    log_print(cmd)
    if not keep_snapshots:
        shutil.rmtree(timelapse_folder)
        log_print("Snapshot files deleted")
    log_print("Video created: " + video_file)


def firmware_monitor(timelapse_folder, duet_host, webcam_url, webcam_http_auth, webcam_https_verify, run_ffmpeg, keep_snapshots):
    # time.sleep(30)  # give devices time to boot and join the network

    while True:
        try:
            log_print("Connecting to {}...".format(duet_host))
            sock = socket.create_connection((duet_host, 23), timeout=10)
            time.sleep(4.5)  # RepRapFirmware uses a 4-second ignore period after connecting
            conn = SimpleLineProtocol(sock)
            log_print("Connection established.")

            timelapse_path = None
            snapshots_path = None
            current_log_print = None

            while True:
                conn.write('M408')
                json_data, raw_lines = conn.read_json_line()
                status = json_data['status']

                if status == 'P' and not timelapse_path:
                    # a print is running, but we don't know the filename yet
                    conn.write('M36')
                    json_data, raw_lines = conn.read_json_line()
                    log_print("Print started:", json_data)
                    gcode_filename = os.path.basename(json_data['fileName'])
                    current_log_print = "{}-{}".format(datetime.datetime.now().strftime("%Y-%m-%d-%H-%M"),
                                                       os.path.splitext(gcode_filename)[0])
                    timelapse_path = os.path.expanduser(timelapse_folder)
                    snapshots_path = os.path.abspath(os.path.join(timelapse_path, current_log_print))
                    os.makedirs(snapshots_path, exist_ok=True)
                    log_print("New timelapse folder created: {}{}".format(snapshots_path, os.path.sep))
                    log_print("Waiting for layer changes...")
                if status == 'I' and snapshots_path:
                    if run_ffmpeg: 
                    	create_video(timelapse_path, current_log_print, snapshots_path, keep_snapshots)
                    # a previous print finished and we need to reset and wait for a new print to start
                    snapshots_path = None
                    log_print("Print finished.")

                if snapshots_path:
                    for line in raw_lines:
                        if line.startswith(b"LAYER CHANGE"):
                            layer_changed(snapshots_path, webcam_url, webcam_http_auth, webcam_https_verify)

                time.sleep(1)
        except Exception as e:
            log_print('ERROR', e, file=sys.stderr)
            traceback.print_exc()
        log_print("Sleeping for a bit...", file=sys.stderr)
        time.sleep(15)


################################################################################

if __name__ == "__main__":

    if len(sys.argv) < 2:
        print(textwrap.dedent("""
            Take snapshot pictures of your DuetWifi/DuetEthernet log_printer on every layer change, and generate a timelapse video at the end.
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
            
            Usage: ./timelapse.py <folder> <duet_host> <webcam_url> [<auth>] [--no-verify] [--no-ffmpeg] [--keep-snapshots]
            
                folder            - folder where all videos and snapshots will be collected, e.g., ~/timelapses
                duet_host         - DuetWifi/DuetEthernet hostname or IP address, e.g., mylog_printer.local or 192.168.1.42
                webcam_url        - HTTP or HTTPS URL that returns a JPG picture, e.g., http://127.0.0.1:8080/?action=snapshot
                auth              - optional, HTTP Basic Auth if the webcam_url requires auth credentials, e.g., john:passw0rd
                --no-verify       - optional, disables HTTPS certificate verification
                --no-ffmpeg       - optional, don't run ffmpeg to generate the video and keep snapshots
                --keep-snapshots  - optional, don't delete the JPG snapshot files after ffmpeg
            """).lstrip().rstrip(), file=sys.stderr)
        sys.exit(1)

    timelapse_folder = sys.argv[1]
    duet_host = sys.argv[2]
    webcam_url = sys.argv[3]

    webcam_http_auth = None
    if len(sys.argv) >= 5:
        auth = sys.argv[4].split(':')
        webcam_http_auth = HTTPBasicAuth(auth[0], auth[1])

    webcam_https_verify = True
    run_ffmpeg = True
    keep_snapshots = False
    for arg in sys.argv:
        if arg == '--no-verify':
            webcam_https_verify = False
        if arg == '--no-ffmpeg':
            run_ffmpeg = False
        if arg == '--keep-snapshots':
            keep_snapshots = True

    firmware_monitor(
        timelapse_folder=timelapse_folder,
        duet_host=duet_host,
        webcam_url=webcam_url,
        webcam_http_auth=webcam_http_auth,
        webcam_https_verify=webcam_https_verify,
        run_ffmpeg=run_ffmpeg,
        keep_snapshots=keep_snapshots
    )
