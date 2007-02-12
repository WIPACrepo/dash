#!/usr/bin/env python

import os
import sys
from math import log10

def nicknames(f):
    """
    Parse nicknames.txt file and return list of (mbid, domid, name, loc)
    tuples.
    """
    # Read the header line
    s = f.readline()
    domlist = []
    while 1:
        s = f.readline()
        if len(s) == 0: break
        if s[0] == '#': continue
        mbid, domid, name, loc, description = s.split(None, 4)
        domlist.append((mbid, domid, name, loc))
    return domlist
                                                
def getName(mbid):
    """
    Return DOM Name for given mbid.
    """
    return dom_db[mbid][2]

def getDomId(mbid):
    """
    Return DOM ID for given mbid.
    """
    return dom_db[mbid][1]

def getOmKey(mbid):
    """
    Return the deployed location of the DOM with mbid.
    """
    return dom_db[mbid][3]

def getByOmKey(omKey):
    """
    Return the database record of a given omKey.
    """
    return dom_db_by_omkey[omKey]

def getHV(cursor, domid, gain):
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
    if nrow != 1: return None
    slope, intercept = cursor.fetchone()
    return 10**((log10(gain) - intercept) / slope)

def getTriggerThreshold(cursor, domid, type, q):
    nrow = cursor.execute(
        """
        SELECT slope, intercept FROM DOMCal_Discriminator d
        JOIN DOMCal_DiscrimType dt ON d.dc_discrim_id = dt.dc_discrim_id
        JOIN DOMCalibration c ON d.domcal_id = c.domcal_id
        JOIN Product p ON c.prod_id = p.prod_id
        WHERE p.tag_serial='%s' AND dt.name='%s'
        ORDER BY c.date DESC
        LIMIT 1
        """ % (domid, type)
        )
    if nrow != 1: return None
    slope, intercept = cursor.fetchone()
    return (q - intercept) / slope


def createConfig(cursor, mbid, **kwargs):
    """
    Create XML configuration blob
    """
    global dom_db
    
    # Setup defaults
    gain = 1.0E+07
    mpeQ = 10.0
    speQ = 0.25
    
    lc_type = "hard"

    omKey = getOmKey(mbid)
    pos = int(omKey[3:5])

    if pos == 1:
        lc_mode = "down"
    elif pos == 60:
        lc_mode = "up"
    else:
        lc_mode = "up-or-down"

    # Check for special LC cases
    if omKey in lc_special_modes: lc_mode = lc_special_modes[omKey]
    
    lc_span = 1
    lc_pre_trigger  = 1000
    lc_post_trigger = 1000
    sn_deadtime     = 250000
    scaler_deadtime = 51200
    
    clen_u = { 'up' : (725, 1325, 2125, 2725), 'down' : (550, 1325, 1950, 2725) }
    clen_t = { 'up' : (550, 1325, 1950, 2725), 'down' : (725, 1325, 2125, 2725) }

    domid = getDomId(mbid)
    if domid[0] == 'A' or domid[0] == 'T':
        clen = clen_t
    else:
        clen = clen_u
        
    if "gain" in kwargs: gain = float(kwargs["gain"])
    if "engFormat" not in kwargs and "deltaFormat" not in kwargs:
        kwargs["engFormat"] = [(128, 128, 128, 0), 250]
    if "span" in kwargs: span = kwargs["span"]
    if "pre_trigger" in kwargs: lc_pre_trigger = kwargs["pre_trigger"]
    if "post_trigger" in kwargs: lc_post_trigger = kwargs["post_trigger"]
    
    # Calculate the HC
    dac = getHV(cursor, domid, gain)
    if dac is None: return ""
    hv  = int(2 * dac)
    mpeDisc = getTriggerThreshold(cursor, domid, 'mpe', mpeQ)
    speDisc = getTriggerThreshold(cursor, domid, 'spe', speQ)
    if mpeDisc is None or speDisc is None: return ""
    
    txt  = "<domConfig mbid='%s' name='%s'>\n" % (mbid, getName(mbid))
    txt += "<format>\n"
    if "engFormat" in kwargs:
        txt += "<engineeringFormat>\n"
        txt += "<fadcSamples> %d </fadcSamples>\n" % kwargs["engFormat"][1]
        for ch in range(4):
            txt += "<atwd ch='%d'>\n" % ch
            txt += "<samples> %d </samples>\n" % kwargs["engFormat"][0][ch]
            txt += "</atwd>\n"
        txt += "</engineeringFormat>\n"
    txt += "</format>\n"
    txt += "<triggerMode> spe </triggerMode>\n"
    txt += "<atwd0TriggerBias>         850 </atwd0TriggerBias>\n"
    txt += "<atwd1TriggerBias>         850 </atwd1TriggerBias>\n"
    txt += "<atwd0RampRate>            350 </atwd0RampRate>\n"
    txt += "<atwd1RampRate>            350 </atwd1RampRate>\n"
    txt += "<atwd0RampTop>            2300 </atwd0RampTop>\n"
    txt += "<atwd1RampTop>            2300 </atwd1RampTop>\n"
    txt += "<atwdAnalogRef>           2250 </atwdAnalogRef>\n"
    txt += "<frontEndPedestal>        2130 </frontEndPedestal>\n"
    txt += "<mpeTriggerDiscriminator> %4d </mpeTriggerDiscriminator>\n" % mpeDisc 
    txt += "<speTriggerDiscriminator> %4d </speTriggerDiscriminator>\n" % speDisc
    txt += "<fastAdcRef>               800 </fastAdcRef>\n"
    txt += "<internalPulser>             0 </internalPulser>\n"
    txt += "<ledBrightness>           1023 </ledBrightness>\n"
    txt += "<frontEndAmpLowerClamp>      0 </frontEndAmpLowerClamp>\n"
    txt += "<flasherDelay>               0 </flasherDelay>\n"
    txt += "<muxBias>                  500 </muxBias>\n"
    txt += "<pmtHighVoltage>          %4d </pmtHighVoltage>\n" % hv
    txt += "<analogMux>                off </analogMux>\n"
    txt += "<pulserMode>            beacon </pulserMode>\n"
    txt += "<pulserRate>                 5 </pulserRate>\n"
    txt += "<localCoincidence>\n"
    txt += "<type> %10s </type>\n" % lc_type
    txt += "<mode> %10s </mode>\n" % lc_mode
    txt += "<txMode>     both </txMode>\n"
    txt += "<source>      spe </source>\n"
    txt += "<span>          %d </span>\n" % lc_span
    txt += "<preTrigger>  %4d </preTrigger>\n" % lc_pre_trigger
    txt += "<postTrigger> %4d </postTrigger>\n" % lc_post_trigger
    for dir in ("up", "down"):
        for dist in range(4):
            txt += "<cableLength dir='%s' dist='%d'> %4d </cableLength>\n" % (dir, dist+1, clen[dir][dist])
    txt += "</localCoincidence>\n"
    txt += "<supernovaMode enabled='true'>\n"
    txt += "<deadtime> %d </deadtime>\n" % sn_deadtime
    txt += "<disc> spe </disc>\n"
    txt += "</supernovaMode>\n"
    txt += "<scalerDeadtime> %6d </scalerDeadtime>\n" % scaler_deadtime
    txt += "</domConfig>\n"
    return txt

        
dom_db = dict()
dom_db_by_omkey = dict()
if "NICKNAMES" in os.environ:
    names = nicknames(file(os.environ["NICKNAMES"]))
    for n in names:
        dom_db[n[0]] = n
        if n[3] != "-": dom_db_by_omkey[n[3]] = n
        
lc_special_modes = {
    '29-58' : 'up',     # 29-59 (Nix) is dead
    '30-22' : 'up',     # 30-23 (Peugeot_505) is dead
    '30-24' : 'down',   # 30-23 (Peugeot_505) is dead
    '49-14' : 'up',     # 49-15 (Mercedes_Benz) LC broken to 49-14
    '50-35' : 'up',     # 50-36 (Ocelot) is dead
    '50-37' : 'down',   # 50-36 (Ocelot) is dead
    '59-51' : 'up',     # 59-51 (T_Centraalen) <--> 59-52 (Medborgerplaz) LC broken
    '59-52' : 'down'    # Ibid.
}

if __name__ == '__main__':
    import re
    import MySQLdb
    from getpass import getpass
    from optparse import OptionParser
    parser = OptionParser()
    parser.add_option("-N", "--nicknames", dest="nicknames", default=None,
                      help="Use alternate nicknames file (don't use $NICKNAMES)")
    parser.add_option("-H", "--db-host", dest="dbHost", default="sps-testdaq01",
                      help="Specify domprodtest database host name")
    parser.add_option("-u", "--user", dest="user", default="penguin",
                      help="Specify database user")
    parser.add_option("-p", "--password", dest="passwd", action="store_true", default=False,
                      help="Database user will need a password")
    
    (opts, args) = parser.parse_args()
    if len(args) < 1: sys.exit(1)

    passwd = ""
    if opts.passwd: getpass("Enter password for user " + opts.user + " on " + opts.dbHost + ": ")
        
    db = MySQLdb.connect(host=opts.dbHost, user=opts.user, passwd=passwd, db="domprodtest")

    cmd = re.compile('(\d{1,2})([it])')
    for s in args:
        m = cmd.search(s)
        if m is None: continue
        istr = int(m.group(1))
        if m.group(2) == 'i':
            p0 = 1
            p1 = 61
        else:
            p0 = 61
            p1 = 65
        kList = [ "%2.2d-%2.2d" % (istr, pos) for pos in range(p0, p1) ]
        mbidList = [ getByOmKey(k)[0] for k in kList ]
        print "<?xml version='1.0' encoding='UTF-8'?>"
        print "<domConfigList>"
        for mbid in mbidList: print createConfig(db.cursor(), mbid, engFormat=((128, 32, 32, 0), 100))
        print "</domConfigList>"
        
