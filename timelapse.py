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


def firmware_monitor(snapshot_folder, duet_host, webcam_url, webcam_http_auth, webcam_https_verify):
    # time.sleep(30)  # give devices time to boot and join the network

    while True:
        try:
            log_print("Connecting to {}...".format(duet_host))
            sock = socket.create_connection((duet_host, 23), timeout=10)
            time.sleep(4.5)  # RepRapFirmware uses a 4-second ignore period after connecting
            conn = SimpleLineProtocol(sock)
            log_print("Connection established.")

            timelapse_folder = None

            while True:
                conn.write('M408')
                json_data, raw_lines = conn.read_json_line()
                status = json_data['status']

                if status == 'P' and not timelapse_folder:
                    # a print is running, but we don't know the filename yet
                    conn.write('M36')
                    json_data, raw_lines = conn.read_json_line()
                    log_print("Print is running:", json_data)
                    gcode_filename = os.path.basename(json_data['fileName'])
                    current_log_print = "{}-{}".format(datetime.datetime.now().strftime("%Y-%m-%d"),
                                                   os.path.splitext(gcode_filename)[0])
                    timelapse_folder = os.path.expanduser(snapshot_folder)
                    timelapse_folder = os.path.abspath(os.path.join(timelapse_folder, current_log_print))
                    os.makedirs(timelapse_folder, exist_ok=True)
                    log_print("New timelapse folder created: {}{}".format(timelapse_folder, os.path.sep))
                    log_print("Waiting for layer changes...")
                if status == 'I' and timelapse_folder:
                    # a previous print finished and we need to reset and wait for a new print to start
                    timelapse_folder = None

                if timelapse_folder:
                    for line in raw_lines:
                        if line.startswith(b"LAYER CHANGE"):
                            layer_changed(timelapse_folder, webcam_url, webcam_http_auth, webcam_https_verify)

                time.sleep(1)
        except Exception as e:
            log_print('ERROR', e, file=sys.stderr)
            traceback.print_exc()
        log_print("Sleeping for a bit...", file=sys.stderr)
        time.sleep(15)


################################################################################

if __name__ == "__main__":

    if len(sys.argv) < 2:
        log_print(textwrap.dedent("""
            Take snapshot pictures of your DuetWifi/DuetEthernet log_printer on every layer change.
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

            After the log_print is done, use ffmpeg to render a timelapse movie:
                $ ffmpeg -r 20 -y -pattern_type glob -i '*.jpg' -c:v libx264 output.mp4

            Usage: ./timelapse.py <folder> <duet_host> <webcam_url> [<auth>] [--no-verify]

                folder       - folder where all pictures will be collected, e.g., ~/timelapse_pictures
                duet_host    - DuetWifi/DuetEthernet hostname or IP address, e.g., mylog_printer.local or 192.168.1.42
                webcam_url   - HTTP or HTTPS URL that returns a JPG picture, e.g., http://127.0.0.1:8080/?action=snapshot
                auth         - HTTP Basic Auth if you configured a reverse proxy with auth credentials, e.g., log_printer:passw0rd
                --no-verify  - Disables HTTPS certificat verification
              """).lstrip().rstrip(), file=sys.stderr)
        sys.exit(1)

    snapshot_folder = sys.argv[1]
    duet_host = sys.argv[2]
    webcam_url = sys.argv[3]

    webcam_http_auth = None
    if len(sys.argv) >= 5:
        webcam_http_auth = sys.argv[4]

    webcam_https_verify = True
    for arg in sys.argv:
        if arg == '--no-verify':
            webcam_https_verify = False

    firmware_monitor(
        snapshot_folder=snapshot_folder,
        duet_host=duet_host,
        webcam_url=webcam_url,
        webcam_http_auth=webcam_http_auth,
        webcam_https_verify=webcam_https_verify
    )
