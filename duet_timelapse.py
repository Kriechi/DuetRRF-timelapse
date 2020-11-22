#!/usr/bin/env python3

import argparse
import logging
import datetime
import json
import os
import socket
import textwrap
import time
import urllib3
import shutil
import subprocess

import requests
from requests.auth import HTTPBasicAuth

urllib3.disable_warnings()

# create logger
logger = logging.getLogger('timelapse')
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
ch.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger.addHandler(ch)


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
        logger.info("Picture taken! " + pic)
    else:
        logger.warning('Failed to get timelapse snapshot.')

def create_video(timelapse_path, current_log_print, snapshots_path, keep_snapshots):
    video_file = os.path.abspath(os.path.join(timelapse_path, current_log_print + ".mp4"))
    snapshots_files = os.path.join(snapshots_path, "*.jpg")
    logger.info("Running ffmpeg to create the video...")
    subprocess.run(
        [
            "ffmpeg",
            "-r", "20",
            "-y",
            "-pattern_type", "glob",
            "-i", snapshots_files,
            "-vcodec", "libx264",
            video_file,
        ],
        check=True,
    )
    if not keep_snapshots:
        shutil.rmtree(snapshots_path)
        logger.info("Snapshot files deleted.")
    logger.info("Video created: " + video_file)


def firmware_monitor(timelapse_folder, duet_host, webcam_url, webcam_http_auth, webcam_https_verify, run_ffmpeg, keep_snapshots):
    logger.info("Sleeping for a bit to let everything initialize...")
    time.sleep(15)  # give devices time to boot and join the network

    while True:
        try:
            logger.info("Connecting to {}...".format(duet_host))
            sock = socket.create_connection((duet_host, 23), timeout=10)
            time.sleep(4.5)  # RepRapFirmware uses a 4-second ignore period after connecting
            conn = SimpleLineProtocol(sock)
            logger.info("Connection established.")

            timelapse_path = None
            snapshots_path = None
            current_log_print = None

            while True:
                conn.write('M408')
                json_data, raw_lines = conn.read_json_line()
                logger.debug(json_data)
                status = json_data['status']

                if status == 'P' and not timelapse_path:
                    # a print is running, but we don't know the filename yet
                    conn.write('M36')
                    json_data, raw_lines = conn.read_json_line()
                    logger.info("Print started:", json_data)
                    gcode_filename = os.path.basename(json_data['fileName'])
                    current_log_print = "{}-{}".format(datetime.datetime.now().strftime("%Y-%m-%dT%H%M"),
                                                       os.path.splitext(gcode_filename)[0])
                    timelapse_path = os.path.expanduser(timelapse_folder)
                    snapshots_path = os.path.abspath(os.path.join(timelapse_path, current_log_print))
                    os.makedirs(snapshots_path, exist_ok=True)
                    logger.info("New timelapse folder created: {}{}".format(snapshots_path, os.path.sep))
                    logger.info("Waiting for layer changes...")
                if status == 'I' and snapshots_path:
                    if run_ffmpeg:
                        try:
                            create_video(timelapse_path, current_log_print, snapshots_path, keep_snapshots)
                        except Exception as e:
                            logger.error("Failed creating video: {}".format(e))
                    # a previous print finished and we need to reset and wait for a new print to start
                    snapshots_path = None
                    logger.info("Print finished.")

                if snapshots_path:
                    for line in raw_lines:
                        if line.startswith(b"LAYER CHANGE"):
                            layer_changed(snapshots_path, webcam_url, webcam_http_auth, webcam_https_verify)

                time.sleep(0.5)
        except Exception as e:
            logger.exception("ERROR: {}".format(e))
        logger.info("Sleeping for a bit...")
        time.sleep(10)


################################################################################

def main():
    parser = argparse.ArgumentParser(
        usage=textwrap.dedent("""
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
        """)
    )
    parser.add_argument(
        "folder",
        help="folder where all videos and snapshots will be collected, e.g., ~/timelapses",
    )
    parser.add_argument(
        "duet_host",
        help="hostname or IP address of your Duet printer, e.g., mylog_printer.local or 192.168.1.42",
    )
    parser.add_argument(
        "webcam_url",
        help="HTTP or HTTPS URL that returns a JPG picture, e.g., http://127.0.0.1:8080/?action=snapshot",
    )
    parser.add_argument(
        "--debug",
        action='store_true',
        help="set the log level to debug",
    )
    parser.add_argument(
        "--auth",
        help="HTTP Basic Auth if the webcam_url requires auth credentials, e.g., john:passw0rd",
    )
    parser.add_argument(
        "--no-verify",
        action='store_false',
        help="disables HTTPS certificate verification",
    )
    parser.add_argument(
        "--run-ffmpeg",
        action='store_true',
        help="run ffmpeg to generate the video after a print finishes",
    )
    parser.add_argument(
        "--keep-snapshots",
        action='store_true',
        help="keep all JPG snapshots after running ffmpeg instead of deleting them",
    )

    args = parser.parse_args()
    print(args)

    if args.debug:
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)

    webcam_http_auth = None
    if args.auth:
        webcam_http_auth = HTTPBasicAuth(*args.auth.split(':'))

    firmware_monitor(
        timelapse_folder=args.folder,
        duet_host=args.duet_host,
        webcam_url=args.webcam_url,
        webcam_http_auth=webcam_http_auth,
        webcam_https_verify=not args.no_verify,
        run_ffmpeg=args.run_ffmpeg,
        keep_snapshots=args.keep_snapshots,
    )

if __name__ == "__main__":
    main()
