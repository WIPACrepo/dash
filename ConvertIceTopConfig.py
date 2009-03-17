#!/usr/bin/env python

# ConvertIceTopConfig.py
# John Jacobsen, NPX Designs, Inc., john@mail.npxdesigns.com
# Started: Fri Jan 25 23:10:49 2008

import unittest, optparse, re, sys

def adaptIceTopConfig(data):
    configs = re.findall("""<domConfig.*?>.+?</domConfig>""", data, re.S)
    print """<?xml version='1.0' encoding='UTF-8'?>
<domConfigList>"""
    
    for conf in configs:
        # Turn off LC
        conf = re.sub("<mode>.+?</mode>", "<mode>none</mode>", conf)
        # Look for low gain dom to change to high gain
        m = re.search("<triggerMode>\s*spe\s*</triggerMode>", conf)
        if m: # Do spe->mpe substitutions
            conf = re.sub("<pmtHighVoltage>\s*\d+\s*</pmtHighVoltage>",
                          "<pmtHighVoltage>2500</pmtHighVoltage>", conf)
            conf = re.sub("<triggerMode>\s*spe\s*</triggerMode>",
                          "<triggerMode>mpe</triggerMode>", conf)
            conf = re.sub("<mpeTriggerDiscriminator>\s*\d+\s*</mpeTriggerDiscriminator>",
                          "<mpeTriggerDiscriminator>615</mpeTriggerDiscriminator>", conf)
        print conf
        
    print """
</domConfigList>
"""

def main():
    p = optparse.OptionParser()
    opt, args = p.parse_args()
    try:
        config = file(args[0]).read()
    except IndexError:
        config = sys.stdin.read()
    adaptIceTopConfig(config)

if __name__ == "__main__": main()

