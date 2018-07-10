from ..Script import Script

import re
import textwrap

class TimelapseLayerChange(Script):

    def getSettingDataString(self):
        return """{
            "name": "Timelapse on Layer Change for Duet RepRapFirmware and Telnet",
            "key": "TimelapseLayerChange",
            "metadata": {},
            "version": 2,
            "settings": {}
        }"""

    def execute(self, data):
        for layer_number, layer in enumerate(data):
            injected_gcode = textwrap.dedent("""
                ;TYPE:CUSTOM
                ; -- Timelapse layer change -- start
                M400
                M118 P4 S"LAYER CHANGE"
                G4 P500
                ; -- Timelapse layer change -- end
                ;LAYER:
            """).lstrip().rstrip()
            data[layer_number] = re.sub(';LAYER:', injected_gcode, layer)

        return data
