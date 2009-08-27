#!/usr/bin/env python

# ProcessAnvilSummaries.py
# John Jacobsen, NPX Designs, Inc., john@mail.npxdesigns.com
# Started: Sat Jan 19 07:43:50 2008

import optparse, xml.dom.minidom, os, tarfile, re

def getField(xml, name):
    """
    Get xxxx in the form <name>xxxx</name>
    """
    if not xml: return None
    els = xml.getElementsByTagName(name)
    if not els: return None
    return els[0].childNodes[0].data

def getAttribute(xml, attr):
    """
    Get xxx in the form <y attr="xxx">
    """
    if not xml: return None
    return xml.attributes[attr].childNodes[0].data

def getSubTag(xml, tag):
    """
    Get XML in the form <tag>....</tag>
    """
    if not xml: return None
    tags = xml.getElementsByTagName(tag)
    if not tags: return None
    return tags[0]

class DAQRun:
    """
    Storage/parsing class for individual DAQ Run information
    """
    def __init__(self, xml):
        self.runNum = getField(xml, "number")
        self.physicsEvents = None
        self.moniEvents    = None
        self.snEvents      = None
        self.tcalEvents    = None
        eventcounts = xml.getElementsByTagName("events")
        for ev in eventcounts:
            stream = getField(ev, "stream")
            count  = getField(ev, "count")
            if stream == "physics": self.physicsEvents = count
            if stream == "monitor": self.moniEvents = count
            if stream == "sn":      self.snEvents = count
            if stream == "tcal":    self.tcalEvents = count
        
class DaqInfo:
    """
    Storage/parsing class for combined current/previous DAQ Run information
    """
    def __init__(self, xml):
        self.cur  = None
        self.prev = None
        self.ebDiskAvail = None
        self.sbDiskAvail = None
        self.ebDiskWarn  = False
        self.sbDiskWarn  = False
        if not xml: return
        runs = xml.getElementsByTagName("run")
        for run in runs:
            ordering = getAttribute(run, "ordering")
            if ordering == "current":
                self.cur = DAQRun(run)
            if ordering == "previous":
                self.prev = DAQRun(run)
        resources = xml.getElementsByTagName("resource")
        for r in resources:
            try:
                warn  = int(getAttribute(r, "warning"))
                avail = int(getField(r, "available"))
                capy  = int(getField(r, "capacity"))
                name  = getField(r, "name")
            except ValueError:
                continue
            if capy == 0: continue
            if re.search("eventbuilder dispatch", name, re.I):
                self.ebDiskAvail = (100.*avail)/capy
                if self.ebDiskAvail < warn:
                    self.ebDiskWarn = True
            elif re.search("secondary builders dispatch", name, re.I):
                self.sbDiskAvail = (100.*avail)/capy
                if self.sbDiskAvail < warn:
                    self.sbDiskWarn = True

    def __str__(self):
        return "%s %s %s %s" % (self.ebDiskAvail, self.ebDiskWarn, self.sbDiskAvail, self.sbDiskWarn)
        

class PnFInfo:
    """
    Storage/parsing class for PnF information
    """
    def __init__(self, xml):
        #reading = getSubTag(xml, "reading")
        self.readEvent = getField(getSubTag(xml, "reading"), "event")
        processing = getSubTag(xml, "processing")
        try: 
            self.trigRate = "%2.1f" % (float(getField(processing, "trigger-rate")))
        except (ValueError, TypeError):
            self.trigRate = ""
        # Disk usage
        self.pnfDiskPercent = "?"
        resource = getSubTag(xml, "resource")
        try:
            used = int(getField(resource, "used"))
            capy = int(getField(resource, "capacity"))
        except:
            used = None
            capy = None
        if capy is not None and capy > 0:
            self.diskPercent = "%2.1f" % (used*100./capy)
        else:
            self.diskPercent = "?"
        filters = getSubTag(xml, "physics-filters")
        try:
            self.filterRate = "%2.1f" % float(getField(filters, "Total"))
        except (ValueError, TypeError):
            self.filterRate = ""
            
class DetectorSummary:
    def __init__(self, filename):
        parsed = xml.dom.minidom.parse(filename)
        #summary   = getSubTag(parsed, "detector-summary") 
        status    = getSubTag(parsed, "status")
        #twr       = getSubTag(parsed, "twr")
        daq       = getSubTag(parsed, "daq")
        pnf       = getSubTag(parsed, "pnf")
        self.date = getField(status, "date")
        self.day  = None
        self.time = None
        m = re.search("(\S+)T(\S+?):\d+Z", self.date)
        if m:
            self.day  = m.group(1)
            self.time = m.group(2)
        subsystems = status.getElementsByTagName("sub-system")
        self.subStates = {}
        # Get state of subsystems
        for sys in subsystems:
            name  = getField(sys, "name")
            state = getField(sys, "state")
            self.subStates[name] = state
        # Get current run statistics
        self.daqInfo = DaqInfo(daq)
        self.latestDAQRun = None
        self.latestEvents = None
        if self.daqInfo.cur:
            self.latestDAQRun = self.daqInfo.cur.runNum
            self.latestEvents = self.daqInfo.cur.physicsEvents
        elif self.daqInfo.prev:
            self.latestDAQRun = self.daqInfo.prev.runNum
            self.latestEvents = self.daqInfo.prev.physicsEvents
        
        # Get current PnF statistics
        self.pnfInfo        = PnFInfo(pnf)
        self.pnfEvent       = self.pnfInfo.readEvent
        self.pnfTrigRate    = self.pnfInfo.trigRate
        self.pnfDiskPercent = self.pnfInfo.diskPercent
        self.pnfFilterRate  = self.pnfInfo.filterRate
        
    def rowHTML(self, prevDay, prevDAQRun):
        state = self.subStates["daq"]
        if self.latestDAQRun != prevDAQRun:
            daqrun = self.latestDAQRun
        else:
            daqrun = ""
        if self.day != prevDay:
            day = self.day
        else:
            day = ""

        if self.daqInfo:
            ebWarn  = self.daqInfo.ebDiskWarn
            sbWarn  = self.daqInfo.sbDiskWarn
            if self.daqInfo.ebDiskAvail:
                ebAvail = "%2.1f" % self.daqInfo.ebDiskAvail
            else:
                ebAvail = ""
            if self.daqInfo.sbDiskAvail:
                sbAvail = "%2.1f" % self.daqInfo.sbDiskAvail
            else:
                sbAvail = ""
        else:
            ebWarn  = False
            sbWarn  = False
            ebAvail = ""
            sbAvail = ""
            
        return """
<TR>
<TD align="center">%s</TD>
<TD align="center">%s</TD>
<TD align="center" class="runnum">%s</TD>
<TD align="right" class="%s">%s</TD>
<TD align="right" class="%s">%s</TD>
<TD align="right" class="%s">%s</TD>
<TD align="center" class="%s">%s</TD>
<TD align="right" class="%s">%s</TD>
<TD align="center" class="%s">%s</TD>
<TD align="right"  class="%s">%s</TD>
<TD align="center">%s</TD>
</TR>
""" % (day, self.time,
       daqrun,
       state, self.latestEvents,
       ebWarn and "warning" or "ok", ebAvail,
       sbWarn and "warning" or "ok", sbAvail,
       self.subStates["twr"], self.subStates["twr"],
       self.subStates["pnf"], self.pnfEvent,
       self.subStates["pnf"], self.pnfTrigRate,
       self.subStates["pnf"], self.pnfFilterRate,
       self.pnfDiskPercent)
    
    def __str__(self):
        return  "%s %s %s %s" % (self.date,
                                 self.subStates["daq"],
                                 self.subStates["twr"],
                                 self.subStates["pnf"])
            
class XMLExtracter:
    def __init__(self, path):
        self.path = path
    def extract(self):
        files = os.listdir(self.path)
        for f in files:
            if os.path.splitext(f)[1] == '.tar':
                m = re.search('detector-summary_(\d+)_', f)
                if not m: continue
                day = m.group(1)
                daydir = os.path.join(self.path, day)
                tarFileName = os.path.join(self.path, f)
                if not os.path.exists(daydir): os.mkdir(daydir)
                tarball = tarfile.TarFile(tarFileName)
                names = tarball.getnames()
                for f in names:
                    match = re.search('\d+.xml', f)
                    if match:
                        tarball.extract(f, daydir)
                        os.unlink(tarFileName)
                        
    def datedirs(self):
        dirs = []
        files = os.listdir(self.path)
        for f in files:
            m = re.search('^(\d+)$', f)
            if not m: continue
            dirs.append(os.path.join(self.path, f))
        return dirs
    
    def xmls(self):
        """
        Generator to find available XML files (call 'extract' method first to
        update directory structure)
        """
        dirs = self.datedirs()
        dirs.sort()
        dirs.reverse()
        for d in dirs:
            files = os.listdir(d)
            files.sort()
            files.reverse()
            for f in files:
                yield os.path.join(d, f)
        return
        
class WebDisplay:
    def __init__(self):
        self.summaries = []
    
    def add(self, summary):
        self.summaries.append(summary)
    
    def html(self):
        r = """
<HTML>
<HEAD>
<TITLE>IceCube Detector Status</TITLE>
<LINK rel='stylesheet' type='text/css' href='site.css'>
<META http-equiv='refresh' content='300'>
</HEAD>
<BODY background='../../images/icecube_pale.jpg'>
<IMG src="../../images/header.png"><BR>
<TABLE>
<TR class="header">
<TD ALIGN="center">Day</TD>
<TD ALIGN="center">Time (UTC)</TD>
<TD ALIGN="center">Run</TD>
<TD ALIGN="center">pDAQ Events</TD>
<TD ALIGN="center">EB<BR>Disk<BR>%</TD>
<TD ALIGN="center">SB<BR>Disk<BR>%</TD>
<TD ALIGN="center">TWR</TD>
<TD ALIGN="center">PnF event</TD>
<TD ALIGN="center">PnF<BR>trig<BR>rate<BR>(Hz)</TD>
<TD ALIGN="center">PnF<BR>filt<BR>rate<BR>(Hz)</TD>
<TD ALIGN="center">PnF<BR>disk<BR>%</TD>
</TR>
"""
        prevRun = None
        prevDay = None
        for s in self.summaries:
            r += s.rowHTML(prevDay, prevRun)
            prevRun = s.latestDAQRun
            prevDay = s.day
        r += """
</TABLE>
</BODY>
</HTML>
"""
        return r
    
    
def main():
    p = optparse.OptionParser()
    opt, args = p.parse_args()
    path = "."
    if len(args) > 0:
        path = args[0]
    xmlExtractor = XMLExtracter(path)
    xmlExtractor.extract()
    display = WebDisplay()
    for xml in xmlExtractor.xmls():
        display.add(DetectorSummary(xml))
    print display.html()
#
if __name__ == "__main__": main()

example = """
<?xml version="1.0" encoding="UTF-8"?>
<?xml-stylesheet type="text/xsl" href="XSL/detector-summary.xsl"?>

<detector-summary>

    <status>
        <date>2008-01-19T07:54:04Z</date>
        <reason-issued>timer</reason-issued>
        <sub-system>
            <name>sn</name>
            <state
                match="yes">Ignored</state>
        </sub-system>
        <sub-system>
            <name>twr</name>
            <state
                match="yes">Started</state>
        </sub-system>
        <sub-system>
            <name>cluster</name>
            <state
                match="yes">Ignored</state>
        </sub-system>
        <sub-system>
            <name>daq</name>
            <state
                match="yes">Started</state>
        </sub-system>
        <sub-system>
            <name>spade</name>
            <state
                match="yes">Ignored</state>
        </sub-system>
        <sub-system>
            <name>pnf</name>
            <state
                match="yes">Started</state>
        </sub-system>
    </status>

    <sn/>

<twr>
    <run
        ordering="previous">
        <number>110114</number>
        <events>
            <stream>physics</stream>
            <count>1099392</count>
        </events>
    </run>
</twr>


    <cluster/>

<daq>
   <run ordering="current">
      <number>110115</number>
      <start-time>2008-01-19 03:10:05.266251</start-time>
      <events><stream>physics</stream><count>12212756</count></events>
      <events><stream>monitor</stream><count>26984528</count></events>
      <events><stream>sn</stream>     <count>23188407</count></events>
      <events><stream>tcal</stream>   <count>23204254</count></events>
   </run>
   <resource warning="10">
     <available>965842</available><capacity>1072621</capacity><units>MB</units>
     <name>EventBuilder dispatch cache</name>
   </resource>
   <resource warning="10">
      <available>214105</available><capacity>227795</capacity><units>MB</units>
      <name>Secondary builders dispatch cache</name>
   </resource>
   <subRunEventCounts>
      <subRun><subRunNum>0</subRunNum><events>12212756</events></subRun>
   </subRunEventCounts>
</daq>

    <spade/>

<pnf>
  <reading>
    <run>110115</run>
    <event>12210000</event>
  </reading>
  <processing>
    <clients>0</clients>
    <trigger-rate>720.232</trigger-rate>
    <processing-rate>684.087</processing-rate>
  </processing>
  <summary>
    <date>2008-01-19T07:54:13+00:00</date>
    <last-report>2008-01-19T07:54:08+00:00</last-report>
    <difference>PT5S</difference>
  </summary>
  <resource>
    <used>641161</used>
    <capacity>1086072</capacity>
    <units>MB</units>
    <name>PnF Disk</name>
  </resource>
<physics-filters>
  <CascadeFilter>21.4786</CascadeFilter>
  <ContainedFilter>12.0571</ContainedFilter>
  <DowngoingContainedFilter>9.90714</DowngoingContainedFilter>
  <EHEFilter>1.75</EHEFilter>
  <FilterMinBias>3.46429</FilterMinBias>
  <I3DAQDecodeException>0</I3DAQDecodeException>
  <IceCubeMuonFilter>24.6214</IceCubeMuonFilter>
  <IceTopSMT>2.65714</IceTopSMT>
  <IceTopSMT_InIceCoincidence>2.6</IceTopSMT_InIceCoincidence>
  <IceTopSMT_Large>0.742857</IceTopSMT_Large>
  <InIceSMT_IceTopCoincidence>4.46429</InIceSMT_IceTopCoincidence>
  <JAMSMuonFilter>8.75714</JAMSMuonFilter>
  <LowEnergyContainedFilter>4.76429</LowEnergyContainedFilter>
  <MoonFilter>0</MoonFilter>
  <MuonFilter>32.6071</MuonFilter>
  <NoClientFilteredIt>0</NoClientFilteredIt>
  <PhysicsMinBiasTrigger>0.414286</PhysicsMinBiasTrigger>
  <TWRDAQDecodeException>0</TWRDAQDecodeException>
  <Total>81.6643</Total>
</physics-filters>
</pnf>


</detector-summary>
"""
