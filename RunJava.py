#!/usr/bin/env python
#
# Run a DAQ Java program
#
# Example:
#    ./RunJava.py -d daq-common -d splicer -d payload -d daq-io \
#        -m log4j:log4j:1.2.7 -m commons-logging:commons-logging:1.0.3 \
#        icecube.daq.io.PayloadDumper physics_123456_0_0_2511.dat

import os
import subprocess


def add_arguments(parser):
    parser.add_argument("-D", "--repo-dir", dest="repoDir",
                        help="Local Maven repository cache")
    parser.add_argument("-d", "--daq-dependency", dest="daqDeps",
                        action="append",
                        help="DAQ project dependency")
    parser.add_argument("-m", "--maven-dependency", dest="mavenDeps",
                        action="append",
                        help="Maven jar dependency")
    parser.add_argument("-r", "--daq-release", dest="daqRelease",
                        help="DAQ Maven release")

    parser.add_argument(dest="app",
                        help="Fully qualified Java application class")
    parser.add_argument(dest="extra", nargs="*")

def findDAQJars(daqDeps, daqRelease, pdaqHome, distDir, repoDir):
    daqRepoSubdir = "edu/wisc/icecube"

    jars = []
    for proj in daqDeps:
        jarname = proj + "-" + daqRelease + ".jar"

        projjar = os.path.join(proj, "target", jarname)
        if os.path.exists(projjar):
            jars.append(projjar)
            continue

        tmpjar = os.path.join("..", projjar)
        if os.path.exists(tmpjar):
            jars.append(tmpjar)
            continue

        if pdaqHome is not None:
            tmpjar = os.path.join(pdaqHome, projjar)
            if os.path.exists(tmpjar):
                jars.append(tmpjar)
                continue

        if distDir is not None:
            tmpjar = os.path.join(distDir, jarname)
            if os.path.exists(tmpjar):
                jars.append(tmpjar)
                continue

        if repoDir is not None:
            tmpjar = os.path.join(repoDir, daqRepoSubdir, proj, daqRelease,
                                  jarname)
            if os.path.exists(tmpjar):
                jars.append(tmpjar)
                continue

        raise SystemExit("Cannot find %s jar file %s" % (proj, jarname))

    return jars


def findMavenJars(mavenJars, repoDir, distDir):
    jars = []
    for tup in mavenJars:
        (proj, name, vers) = tup

        jarname = name + "-" + vers + ".jar"

        tmpjar = os.path.join(repoDir, proj, name, vers, jarname)
        if os.path.exists(tmpjar):
            jars.append(tmpjar)
            continue

        if distDir is not None:
            tmpjar = os.path.join(distDir, jarname)
            if os.path.exists(tmpjar):
                jars.append(tmpjar)
                continue

        raise SystemExit("Cannot find Maven jar file %s" % jarname)

    return jars


def runJava(app, javaArgs, appArgs, daqDeps, mavenDeps, daqRelease=None,
            repoDir=None):

    if daqRelease is None:
        daqRelease = "1.0.0-SNAPSHOT"

    if repoDir is None:
        repoDir = os.path.join(os.environ["HOME"], ".m2", "repository")
        if not os.path.exists(repoDir):
            raise SystemExit("Cannot find Maven repository directory")

    pdaqHome = None
    distDir = None

    if os.environ.has_key("PDAQ_HOME"):
        pdaqHome = os.environ["PDAQ_HOME"]

        tmpDir = os.path.join(pdaqHome, "target",
                              "pDAQ" + daqRelease + "-dist", "lib")
        if os.path.exists(tmpDir):
            distDir = tmpDir

    daqjars = findDAQJars(daqDeps, daqRelease, pdaqHome, distDir, repoDir)

    mavenjars = findMavenJars(mavenDeps, repoDir, distDir)

    setClassPath(daqjars + mavenjars)

    cmd = ["java"]
    if javaArgs is not None and len(javaArgs) > 0:
        cmd += javaArgs
    cmd.append(app)
    if appArgs is not None and len(appArgs) > 0:
        cmd += appArgs

    subprocess.call(cmd)


def setClassPath(jars):
    if not os.environ.has_key("CLASSPATH"):
        cp = jars
    else:
        cp = jars + os.environ["CLASSPATH"].split(":")

    if len(cp) > 0:
        os.environ["CLASSPATH"] = ":".join(cp)


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    add_arguments(p)
    args = p.parse_args()

    # convert java dependencies into triplets
    mavenDeps = []
    for j in args.mavenDeps:
        jtup = j.split(":")
        if len(jtup) < 2 or len(jtup) > 3:
            raise SystemExit("Invalid Maven dependency \"%s\"" % j)

        mavenDeps.append(jtup)

    runJava(args.app, None, args.extra, args.daqDeps, mavenDeps,
            daqRelease=args.daqRelease, repoDir=args.repoDir)
