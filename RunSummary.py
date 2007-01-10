#!/usr/bin/env python


import optparse
from sys import stderr
from os import listdir, mkdir
from os.path import exists, isdir, abspath
from re import *
from shutil import copy
import tarfile

if __name__ == "__main__":
    p = optparse.OptionParser()
    p.add_option("-s", "--spade-dir",   action="store", type="string", dest="spadeDir")
    p.add_option("-o", "--output-dir",  action="store", type="string", dest="outputDir")
    p.add_option("-a", "--replace-all", action="store_true",           dest="replaceAll")
    p.set_defaults(spadeDir   = "../spade",
                   outputDir  = "../reports",
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

    # Find all SPADE files in the form:
    # SPS-pDAQ-run-001_20070108_174324_000015.dat.tar

    def makeSnippet(snippetFile, infoPat, runInfo, runLink, status):
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
        snippet = open(snippetFile, 'w')

        # Calculate status color
        statusColor = "EFEFEF"
        if status == "FAIL":
            statusColor = "FF3300"
        elif status == "SUCCESS":
            statusColor = "CCFFCC"
            
        print >>snippet, """
        <tr>
        <td align=center>%d</td>
        <td align=center>%02d/%02d/%02d</td>
        <td align=center>%02d:%02d:%02d</td>
        <td align=center>%d</td>
        <td align=center bgcolor=%s><a href="%s">%s</a></td>
        </tr>
        """ % (runNum, month, day, year, hr, mins, sec, dur, statusColor, runLink, status)

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
     <td align=center><b>Status</b></td>
     <td><font color=grey>(Click on status link for run details)</font></td>
    </tr>
    """
    
    for f in listdir(opt.spadeDir):
        match = search(r'SPS-pDAQ-run-(\S+)\.dat\.tar', f)
        if match:
            runInfoString = match.group(1)
            infoPat = r'(\d+)_(\d\d\d\d)(\d\d)(\d\d)_(\d\d)(\d\d)(\d\d)_(\d+)'
            match = search(infoPat, runInfoString)
            if not match: continue
            # print "%s -> %s" % (f, runInfoString)
            outDir = runDir + "/" + runInfoString
            check_make_or_exit(outDir)
            tarFile     = opt.spadeDir + "/" + f
            copyFile    = outDir + "/" + f
            snippetFile = outDir + "/.snippet.html"
            linkDir     = runInfoString + "/" 
            # Skip if tarball has already been copied
            if not exists(copyFile) or not exists(snippetFile) or opt.replaceAll:
                print "%s -> %s/" % (f, outDir)

                # Move tarballs into target run directories
                copy(tarFile, copyFile)
                if not (exists(copyFile) and tarfile.is_tarfile(copyFile)):
                    raise Exception("Bad tar file %s!" % copyFile)

                # Extract contents
                status = None
                tar = tarfile.open(copyFile)
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

                    # Remember more precise unpacked location for link
                    if search(r'daqrun(\d+)/$', el): 
                        linkDir = runInfoString + "/" + el
                        
                tar.close()

                # Make HTML snippet for run summaries
                makeSnippet(snippetFile, infoPat, runInfoString, linkDir, status)


            lines = open(snippetFile).read()
            print >>allSummaryFile, lines
            
    print >>allSummaryFile, """
    </table>
    </html>
    """
    allSummaryFile.close()
    
