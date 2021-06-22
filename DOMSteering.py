#!/usr/bin/env python

from __future__ import print_function

import os
import sys
from math import log10


def nicknames(fhndl):
    """
    Parse nicknames.txt file and return list of (mbid, domid, name, loc)
    tuples.
    """
    # Ignore the header line
    _ = fhndl.readline()
    domlist = []
    for line in fhndl:
        if line[0] == '#':
            continue

        mbid, domid, domname, loc, _ = line.split(None, 4)
        domlist.append((mbid, domid, domname, loc))
    return domlist


def get_name(mbid):
    """
    Return DOM Name for given mbid.
    """
    return DOM_DB[mbid][2]


def get_dom_id(mbid):
    """
    Return DOM ID for given mbid.
    """
    return DOM_DB[mbid][1]


def get_om_key(mbid):
    """
    Return the deployed location of the DOM with mbid.
    """
    return DOM_DB[mbid][3]


def get_by_om_key(om_key):
    """
    Return the database record of a given om_key.
    """
    return DOM_DB_BY_OMKEY[om_key]


def get_hv(cursor, domid, gain):
    """
    Function to obtain the HV (in Volts)
    for a particular DOM "domid" at a given
    gain.  It will use the DOMCal SQL database
    """
    nrow = cursor.execute(
        """
        SELECT slope, intercept FROM DOMCal_HvGain hv
        JOIN DOMCalibration c ON hv.domcal_id = c.domcal_id
        JOIN Product p ON c.prod_id = p.prod_id
        WHERE p.tag_serial='%s'
        ORDER BY c.date DESC
        LIMIT 1
        """ % domid
        )
    if nrow != 1:
        return None
    slope, intercept = cursor.fetchone()
    return 10 ** ((log10(gain) - intercept) / slope)


def get_trigger_threshold(cursor, domid, domtype, qval):
    nrow = cursor.execute(
        """
        SELECT slope, intercept FROM DOMCal_Discriminator d
        JOIN DOMCal_DiscrimType dt ON d.dc_discrim_id = dt.dc_discrim_id
        JOIN DOMCalibration c ON d.domcal_id = c.domcal_id
        JOIN Product p ON c.prod_id = p.prod_id
        WHERE p.tag_serial='%s' AND dt.name='%s'
        ORDER BY c.date DESC
        LIMIT 1
        """ % (domid, domtype)
        )
    if nrow != 1:
        return None
    slope, intercept = cursor.fetchone()
    return (qval - intercept) / slope


def create_config(cursor, mbid, **kwargs):
    """
    Create XML configuration blob
    """
    # Setup defaults
    gain = 1.0E+07
    trigger_mode = "spe"

    lc_type = "hard"

    om_key = get_om_key(mbid)
    pos = int(om_key[3:5])

    lc_mode = "up-or-down"
    lc_tx_mode = "both"

    if pos == 1:
        lc_mode = "down"
    elif pos == 60:
        lc_mode = "up"
    elif pos == 61:     # IceTop HG tank A
        gain = 5.0E+06
        trigger_mode = "mpe"
    elif pos == 62:     # IceTop LG tank A
        gain = 5.0E+05
        mpe_q = 8.0
        spe_q = 1.0
        lc_tx_mode = "none"
    elif pos == 63:     # IceTop HG tank B
        gain = 5.0E+06
        trigger_mode = "mpe"
    elif pos == 64:     # IceTop LG tank B
        gain = 5.0E+05
        mpe_q = 8.0
        spe_q = 1.0
        lc_tx_mode = "none"

    # Check for special LC cases
    lc_mode = LC_SPECIAL_MODES.get(om_key, lc_mode)

    lc_span = 1
    lc_pre_trigger = 1000
    lc_post_trigger = 1000
    sn_deadtime = 250000
    scaler_deadtime = 51200

    clen_u = {'up': (725, 1325, 2125, 2725), 'down': (550, 1325, 1950, 2725)}
    clen_t = {'up': (550, 1325, 1950, 2725), 'down': (725, 1325, 2125, 2725)}

    domid = get_dom_id(mbid)
    if domid[0] == 'A' or domid[0] == 'T':
        clen = clen_t
    else:
        clen = clen_u

    gain = kwargs.get("gain", gain)
    mpe_q = 16.0 * gain / 1.0e+7
    spe_q = 0.4 * gain / 1.0e+7

    lc_span = kwargs.get("span", 1)
    lc_pre_trigger = kwargs.get("pre_trigger", 1000)
    lc_post_trigger = kwargs.get("post_trigger", 1000)
    if "eng_format" not in kwargs and "deltaFormat" not in kwargs:
        kwargs["eng_format"] = [(128, 128, 128, 0), 250]

    # Calculate the HV
    if om_key in HV_SPECIALS:  # pylint: disable=consider-using-get
        dac = HV_SPECIALS[om_key]
    else:
        dac = get_hv(cursor, domid, gain)
    if dac is None:
        return ""
    hv_val = int(2 * dac)
    mpe_disc = get_trigger_threshold(cursor, domid, 'mpe', mpe_q)
    spe_disc = get_trigger_threshold(cursor, domid, 'spe', spe_q)
    if mpe_disc is None or spe_disc is None:
        return ""

    txt = '<domConfig mbid="%s" name="%s">\n' % (mbid, get_name(mbid))
    txt += '<format>\n'
    if "eng_format" in kwargs:
        txt += '<engineeringFormat>\n'
        txt += '<fadcSamples> %d </fadcSamples>\n' % kwargs["eng_format"][1]
        for chan_num in range(4):
            txt += '<atwd ch="%d">\n' % chan_num
            txt += '<samples> %d </samples>\n' % \
              kwargs["eng_format"][0][chan_num]
            txt += '</atwd>\n'
        txt += '</engineeringFormat>\n'

    txt += '</format>\n'
    txt += "<triggerMode> %3s </triggerMode>\n" % trigger_mode
    txt += "<atwd0TriggerBias>         850 </atwd0TriggerBias>\n"
    txt += "<atwd1TriggerBias>         850 </atwd1TriggerBias>\n"
    txt += "<atwd0RampRate>            350 </atwd0RampRate>\n"
    txt += "<atwd1RampRate>            350 </atwd1RampRate>\n"
    txt += "<atwd0RampTop>            2300 </atwd0RampTop>\n"
    txt += "<atwd1RampTop>            2300 </atwd1RampTop>\n"
    txt += "<atwdAnalogRef>           2250 </atwdAnalogRef>\n"
    txt += "<frontEndPedestal>        2130 </frontEndPedestal>\n"
    txt += "<mpeTriggerDiscriminator> %4d </mpeTriggerDiscriminator>\n" % \
        mpe_disc
    txt += "<speTriggerDiscriminator> %4d </speTriggerDiscriminator>\n" % \
        spe_disc
    txt += "<fastAdcRef>               800 </fastAdcRef>\n"
    txt += "<internalPulser>             0 </internalPulser>\n"
    txt += "<ledBrightness>           1023 </ledBrightness>\n"
    txt += "<frontEndAmpLowerClamp>      0 </frontEndAmpLowerClamp>\n"
    txt += "<flasherDelay>               0 </flasherDelay>\n"
    txt += "<muxBias>                  500 </muxBias>\n"
    txt += "<pmtHighVoltage>          %4d </pmtHighVoltage>\n" % hv_val
    txt += "<analogMux>                off </analogMux>\n"
    txt += "<pulserMode>            beacon </pulserMode>\n"
    txt += "<pulserRate>                 1 </pulserRate>\n"
    txt += "<localCoincidence>\n"
    txt += "<type> %10s </type>\n" % lc_type
    txt += "<mode> %10s </mode>\n" % lc_mode
    txt += "<txMode> %8s</txMode>\n" % lc_tx_mode
    txt += "<source>      spe </source>\n"
    txt += "<span>          %d </span>\n" % lc_span
    txt += "<preTrigger>  %4d </preTrigger>\n" % lc_pre_trigger
    txt += "<postTrigger> %4d </postTrigger>\n" % lc_post_trigger
    for direction in ("up", "down"):
        for dist in range(4):
            txt += '<cableLength dir="%s" dist="%d"> %4d </cableLength>\n' % \
                (direction, dist + 1, clen[direction][dist])
    txt += "</localCoincidence>\n"
    txt += '<supernovaMode enabled="true">\n'
    txt += "<deadtime> %d </deadtime>\n" % sn_deadtime
    txt += "<disc> spe </disc>\n"
    txt += "</supernovaMode>\n"
    txt += "<scalerDeadtime> %6d </scalerDeadtime>\n" % scaler_deadtime
    txt += "</domConfig>\n"
    return txt


DOM_DB = dict()
DOM_DB_BY_OMKEY = dict()
if "NICKNAMES" in os.environ:
    NICKNAMES = nicknames(file(os.environ["NICKNAMES"]))
    for nickname in NICKNAMES:
        DOM_DB[nickname[0]] = nickname
        if nickname[3] != "-":
            DOM_DB_BY_OMKEY[nickname[3]] = nickname

LC_SPECIAL_MODES = {
    '29-58': 'up',     # 29-59 (Nix) is dead
    '30-22': 'up',     # 30-23 (Peugeot_505) is dead
    '30-24': 'down',   # 30-23 (Peugeot_505) is dead
    '49-14': 'up',     # 49-15 (Mercedes_Benz) LC broken to 49-14
    '50-35': 'up',     # 50-36 (Ocelot) is dead
    '50-37': 'down',   # 50-36 (Ocelot) is dead
    # 59-51 (T_Centraalen) <--> 59-52 (Medborgerplaz) LC broken
    '59-51': 'up',
    '59-52': 'down',   # Ibid.
    '65-33': 'up',     # Broken LC between Michael Myers & Williwaw
    '65-34': 'down'
}

HV_SPECIALS = {
    '21-30': 1250      # Phenol
}


def main():
    "Main program"

    import re
    import MySQLdb
    from getpass import getpass
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("-N", "--nicknames", dest="nicknames",
                        help=("Use alternate nicknames file "
                              "(don't use $NICKNAMES)"))
    parser.add_argument("-H", "--db-host", dest="dbHost",
                        default="sps-testdaq01",
                        help="Specify domprodtest database host name")
    parser.add_argument("-u", "--user", dest="user", default="penguin",
                        help="Specify database user")
    parser.add_argument("-p", "--password", dest="passwd", action="store_true",
                        default=False,
                        help="Database user will need a password")
    parser.add_argument("-E", "--engineering-readout", dest="eng_fmt",
                        default="128,128,128,0,250",
                        help="Use engineering format readout")
    parser.add_argument("-S", "--lc-span", dest="span", type=int, default=1,
                        help="Set LC span parameter.")
    parser.add_argument("-G", "--gain", dest="gain", type=float,
                        default=1.0E+07,
                        help="Set PMT gain")
    parser.add_argument("hubname", nargs="+")

    args = parser.parse_args()

    # Extract the engineering format
    vec = args.eng_fmt.split(",")
    if len(vec) != 5:
        print("ERROR: engineering format spec is"
              " --E ATWD0,ATWD1,ATWD2,ATWD3,FADC", file=sys.stderr)
        sys.exit(1)
    eng_fmt = (tuple([int(x) for x in vec[0:4]]), int(vec[4]))

    passwd = ""
    if args.passwd:
        getpass("Enter password for user %s on %s: " %
                (args.user, args.dbHost))

    dbconn = MySQLdb.connect(host=args.dbHost, user=args.user,
                             passwd=passwd, db="domprodtest")

    cmd = re.compile(r'(\d{1,2})([it])')
    print("<?xml version='1.0' encoding='UTF-8'?>")
    print("<domConfigList>")
    for hname in args.hubname:
        mtch = cmd.search(hname)
        if mtch is None:
            continue
        istr = int(mtch.group(1))
        if mtch.group(2) == 'i':
            pos0 = 1
            pos1 = 61
        else:
            pos0 = 61
            pos1 = 65
        keylist = ["%2.2d-%2.2d" % (istr, pos) for pos in range(pos0, pos1)]
        mbid_list = []
        for key in keylist:
            try:
                mbid = get_by_om_key(key)[0]
                mbid_list.append(mbid)
            except KeyError:
                print("WARN: \"%s\" not found in nicknames" % key,
                      file=sys.stderr)

        for mbid in mbid_list:
            print(create_config(dbconn.cursor(), mbid,
                                eng_format=eng_fmt,
                                span=args.span,
                                gain=args.gain))
    print("</domConfigList>")


if __name__ == '__main__':
    main()
