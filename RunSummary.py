#!/usr/bin/env python


import optparse
from sys import stderr
from os import listdir, mkdir, environ
from os.path import exists, isdir, abspath
from re import *
from shutil import copy
import tarfile

if __name__ == "__main__":

    p = optparse.OptionParser()
    p.add_option("-s", "--spade-dir",   action="store", type="string", dest="spadeDir")
    p.add_option("-o", "--output-dir",  action="store", type="string", dest="outputDir")
    p.add_option("-a", "--replace-all", action="store_true",           dest="replaceAll")
    p.set_defaults(spadeDir   = "/mnt/data/spade/localcopies/daq",
                   outputDir  = "%s/public_html/daq-reports" % environ["HOME"],
                   replaceAll = False)

    opt, args = p.parse_args()

    if not exists(opt.spadeDir):
        print "Can't find %s... giving up." % opt.spadeDir
        raise SystemExit

    def check_make_or_exit(dir):
        if not exists(dir):
            # print ("Creating %s... " % dir),
            try: mkdir(dir, 0755)
            except Exception, e:
                print "Couldn't mkdir %s: %s!" % (dir, e)
                raise SystemExit
            # print "OK."

    check_make_or_exit(opt.outputDir)
    runDir = opt.outputDir+"/runs"
    check_make_or_exit(runDir)

    def generateSnippet(snippetFile, runNum, month, day, year, hr, mins, sec, dur,
                        configName, runDir, status, nEvents):
        
        snippet = open(snippetFile, 'w')

        statusColor = getStatusColor(status)

        evStr = ""
        if nEvents != None: evStr = nEvents
        
        print >>snippet, """
        <tr>
        <td align=center>%d</td>
        <td align=center>%02d/%02d/%02d</td>
        <td align=center>%02d:%02d:%02d</td>
        <td align=center>%d</td>
        <td align=center>%s</td>
        <td align=center>%s</td>
        <td align=center bgcolor=%s><a href="%s">%s</a></td>
        </tr>
        """ % (runNum, month, day, year, hr, mins, sec, dur, evStr,
               configName, statusColor, runDir, status)
        return

    def getStatusColor(status):
        # Calculate status color
        statusColor = "EFEFEF"
        if status == "FAIL":
            statusColor = "FF3300"
        elif status == "SUCCESS":
            statusColor = "CCFFCC"
        return statusColor

    def makeTable(files, name):
        html = ""
        if files:
            html += "<PRE>\n\n</PRE><TABLE>"
            virgin = True
            for l in files:
                html += "<TR>"
                if virgin: html += r'<TD ALIGN="right"><FONT COLOR=888888>%s</FONT></TD>' % name
                else: html += "<TD></TD>"
                virgin = False
                html += r'<TD><A HREF="%s">%s</A></TD>' % (l, l)
                html += "</TR>"
            html += "</TABLE>"
        return html

    def makeSummaryHtml(logLink, runNum, month, day, year, hr,
                        mins, sec, dur, configName, status, nEvents):
        files = listdir(logLink)
        mons  = []
        logs  = []
        for f in files:
            if search(r'\.log$', f): logs.append(f)
            if search(r'\.moni$', f): mons.append(f)

        html = open(logLink+"/run.html", "w")

        eventStr = "(check monitoring files)"
        if nEvents != None: eventStr = nEvents
        
        print >>html, "<HTML>"
        print >>html, "<TABLE><TR><TD BGCOLOR=EEEEEE>"
        print >>html, """
<TABLE>
 <TR><TD ALIGN="right"><FONT COLOR=888888>Run</FONT></TD><TD><FONT SIZE=+3>%d</FONT></TD></TR>
 <TR><TD ALIGN="right"><FONT COLOR=888888>Configuration</FONT></TD><TD>%s</TD></TR>
 <TR><TD ALIGN="right"><FONT COLOR=888888>Date</FONT></TD><TD>%s</TD></TR>
 <TR><TD ALIGN="right"><FONT COLOR=888888>Time</FONT></TD><TD>%s</TD></TR>
 <TR><TD ALIGN="right"><FONT COLOR=888888>Duration</FONT></TD><TD>%d seconds</TD></TR>
 <TR><TD ALIGN="right"><FONT COLOR=888888>Events</FONT></TD><TD>%s</TD></TR>
 <TR><TD ALIGN="right"><FONT COLOR=888888>Status</FONT></TD><TD BGCOLOR=%s>%s</TD></TR>
</TABLE>
        """ % (runNum, configName,
               "%02d/%02d/%02d" % (month, day, year),
               "%02d:%02d:%02d" % (hr, mins, sec),
               dur, eventStr, getStatusColor(status), status)

        print >>html, makeTable(logs, "Logs")
        print >>html, makeTable(mons, "Monitoring")

        print >>html, "</TD><TD>"
        
        dashlog = logLink+"/dash.log"
        if exists(dashlog):
            print >>html, "<PRE>"
            print >>html, open(dashlog).read()
            print >>html, "</PRE>"

        print >>html, "</TD></TR></TABLE>"
        print >>html, "</HTML>"
        html.close()
    
    def makeRunReport(snippetFile, infoPat, runInfo, configName,
                      status, nEvents, absRunDir, relRunDir):

        match = search(infoPat, runInfo)
        if not match: return
        runNum = int(match.group(1))
        year   = int(match.group(2))
        month  = int(match.group(3))
        day    = int(match.group(4))
        hr     = int(match.group(5))
        mins   = int(match.group(6))
        sec    = int(match.group(7))
        dur    = int(match.group(8))

        generateSnippet(snippetFile, runNum, month, day, year, hr, mins, sec, dur,
                        configName, relRunDir+"/run.html", status, nEvents)
        makeSummaryHtml(absRunDir, runNum, month, day, year, hr,
                        mins, sec, dur, configName, status, nEvents)

    infoPat = r'(\d+)_(\d\d\d\d)(\d\d)(\d\d)_(\d\d)(\d\d)(\d\d)_(\d+)'

    def cmp(a, b):
        amatch = search(infoPat, a)
        bmatch = search(infoPat, b)
        if not amatch: return
        if not bmatch: return
        n = 2
        for n in [2, 3, 4, 5, 6, 7, 1, 8]:
            ia = int(amatch.group(n)); ib = int(bmatch.group(n))
            if ia != ib: return ib-ia
        return 0

    def getSnippetHtml(lines):
        return open(snippetFile).read()

    allSummaryHtml = runDir + "/index.html"
    allSummaryFile = open(allSummaryHtml, "w")
    print >>allSummaryFile, """
    <html>
    <table>
    <tr>
     <td align=center><b>Run</b></td>
     <td align=center><b>Start<br>Date</b></td>
     <td align=center><b>Start<br>Time</b></td>
     <td align=center><b>Duration<br>(seconds)</b></td>
     <td align=center><b>Num.<br>Events</b></td>
     <td align=center><b>Config</b></td>
     <td align=center><b>Status</b></td>
     <td><font color=grey>(Click on status link for run details)</font></td>
    </tr>
    """

    l = listdir(opt.spadeDir)
    l.sort(cmp)
    for f in l:
        prefix = 'SPS-pDAQ-run-'
        if search(r'.done$', f): continue # Skip SPADE .done semaphores
        if search(r'.sem$', f): continue # Skip SPADE .done semaphores
        match = search(r'%s(\S+?)\.' % prefix, f)
        if match:
            runInfoString = match.group(1)
            match = search(infoPat, runInfoString)
            if not match: continue
            print "%s -> %s" % (f, runInfoString)
            outDir = runDir + "/" + runInfoString
            check_make_or_exit(outDir)
            tarFile     = opt.spadeDir + "/" + f
            copyFile    = outDir + "/" + f
            datTar      = outDir + "/" + prefix + runInfoString + ".dat.tar"
            snippetFile = outDir + "/.snippet"
            linkDir     = runInfoString + "/"
            nEvents     = None
            # print datTar
            # Skip if tarball has already been copied
            if not exists(copyFile) or not exists(snippetFile) \
               or not exists(datTar) \
               or opt.replaceAll:

                # Move tarballs into target run directories
                if not exists(copyFile):
                    print "%s -> %s/" % (f, outDir)
                    copy(tarFile, copyFile)
                    if not tarfile.is_tarfile(copyFile):
                        raise Exception("Bad tar file %s!" % copyFile)

                    # Extract top tarball
                    if datTar != copyFile:
                        tar = tarfile.open(copyFile)
                        for el in tar.getnames():
                            if search('\.dat\.tar$', el): tar.extract(el, outDir)

                    if not exists(datTar):
                        raise Exception("Tarball %s didn't contain %s!", copyFile, datTar)

                # Extract contents
                status = None; configName = None
                tar = tarfile.open(datTar)
                for el in tar.getnames():
                    tar.extract(el, outDir)
                    # Find dash.log
                    if search(r'dash.log', el):
                        dashFile = outDir + "/" + el
                        dashContents = open(dashFile).read()

                        # Get status
                        s = search(r'Run terminated (.+).', dashContents)
                        if s:
                            if s.group(1)=="SUCCESSFULLY": status = "SUCCESS"
                            else: status = "FAIL"

                        s = search(r'config name (.+?)\n', dashContents)
                        if s: configName = s.group(1)

                        s = search(r'(\d+) events collected', dashContents)
                        if s: nEvents = s.group(1)

                    # Remember more precise unpacked location for link
                    if search(r'(daqrun\d+)/$', el): 
                        linkDir = runInfoString + "/" + el

                tar.close()

                if status == None or configName == None:
                    #print "SKIPPED null run %s" % outDir
                    continue
                    
                # Make HTML snippet for run summaries
                makeRunReport(snippetFile, infoPat, runInfoString, 
                              configName, status, nEvents, runDir+"/"+linkDir,
                              linkDir)

            print >>allSummaryFile, getSnippetHtml(snippetFile)
            allSummaryFile.flush()
            
    print >>allSummaryFile, """
    </table>
    </html>
    """
    allSummaryFile.close()
    
