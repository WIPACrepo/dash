#!/usr/bin/env python
#
# Run a DAQ Java program
#
# Example:
#    ./RunJava.py -d daq-common -d splicer -d payload -d daq-io \
#        -m log4j:log4j:1.2.7 -m commons-logging:commons-logging:1.0.3 \
#        icecube.daq.io.PayloadDumper physics_123456_0_0_2511.dat


from distutils.version import LooseVersion
import os
import subprocess


def add_arguments(parser):
    parser.add_argument("-D", "--repo-dir", dest="repoDir",
                        help="Local Maven repository cache")
    parser.add_argument("-d", "--daq-dependency", dest="daqDeps",
                        action="append", default=[],
                        help="DAQ project dependency")
    parser.add_argument("-m", "--maven-dependency", dest="mavenDeps",
                        action="append", default=[],
                        help="Maven jar dependency")
    parser.add_argument("-r", "--daq-release", dest="daqRelease",
                        help="DAQ Maven release")
    parser.add_argument("-X", "--extra-java", dest="extraJava",
                        action="append", default=[],
                        help="Extra Java arguments")

    parser.add_argument(dest="app",
                        help="Fully qualified Java application class")
    parser.add_argument(dest="extra", nargs="*")


def buildJarName(name, vers):
    """Build a versioned jar file name"""
    return name + "-" + vers + ".jar"


def findDAQJar(proj, daqRelease):
    jarname = buildJarName(proj, daqRelease)

    # check foo/target/foo-X.Y.Z.jar (if we're in top-level project dir)
    projjar = os.path.join(proj, "target", jarname)
    if os.path.exists(projjar):
        return projjar

    # check ../foo/target/foo-X.Y.Z.jar (in case we're in a project subdir)
    tmpjar = os.path.join("..", projjar)
    if os.path.exists(tmpjar):
        return tmpjar

    # check $PDAQHOME/foo/target/foo-X.Y.Z.jar
    if pdaqHome is not None:
        tmpjar = os.path.join(pdaqHome, projjar)
        if os.path.exists(tmpjar):
            return tmpjar

    if distDir is not None:
        # check $PDAQHOME/target/pDAQ-X.Y.Z-dist/lib/foo-X.Y.Z.jar
        tmpjar = os.path.join(distDir, jarname)
        if os.path.exists(tmpjar):
            return tmpjar

    if repoDir is not None:
        # check ~/.m2/repository/edu/wisc/icecube/foo/X.Y.Z/foo-X.Y.Z.jar
        tmpjar = os.path.join(repoDir, "edu/wisc/icecube", proj, daqRelease,
                              jarname)
        if os.path.exists(tmpjar):
            return tmpjar

    raise SystemExit("Cannot find %s jar file %s" % (proj, jarname))

def findDAQJars(daqDeps, daqRelease, pdaqHome, distDir, repoDir):
    """
    Find pDAQ jar files in all likely places, starting with the current
    project directory
    """
    jars = []
    if daqDeps is not None:
        for proj in daqDeps:
            jars.append(findDAQJar(proj, daqRelease))

    return jars


def findRepoJar(repoDir, distDir, proj, name, vers):
    """
    Find a jar file in the Maven repository which is at or after the version
    specified by 'vers'
    """
    jarname = buildJarName(name, vers)

    projdir = os.path.join(repoDir, proj, name)
    if os.path.exists(projdir):
        tmpjar = os.path.join(projdir, vers, jarname)
        if os.path.exists(tmpjar):
            return tmpjar

        overs = LooseVersion(vers)
        for entry in os.listdir(projdir):
            nvers = LooseVersion(entry)
            if overs < nvers:
                tmpjar = os.path.join(projdir, entry, buildJarName(name, entry))
                if os.path.exists(tmpjar):
                    import sys
                    print >>sys.stderr, "WARNING: Using %s version %s" \
                        " instead of requested %s" % (name, entry, vers)
                    return tmpjar

    if distDir is not None:
        tmpjar = os.path.join(distDir, jarname)
        if os.path.exists(tmpjar):
            return tmpjar

        overs = LooseVersion(vers)
        namedash = name + "-"
        for entry in os.listdir(distDir):
            if entry.startswith(namedash):
                jarext = entry.find(".jar")
                if jarext > 0:
                    vstr = entry[len(namedash):jarext]
                    nvers = LooseVersion(vstr)
                    if overs <= nvers:
                        print >>sys.stderr, "WARNING: Using %s version %s" \
                            " instead of requested %s" % (name, vstr, vers)
                        return os.path.join(distDir, entry)

    raise SystemExit("Cannot find Maven jar file %s" % jarname)


def findMavenJars(mavenJars, repoDir, distDir):
    """
    Find requested jar files in either the Maven repository or in the
    pDAQ distribution directory
    """
    jars = []
    if mavenJars is not None:
        for tup in mavenJars:
            (proj, name, vers) = tup

            jars.append(findRepoJar(repoDir, distDir, proj, name, vers))

    return jars


def runJava(app, javaArgs, appArgs, daqDeps, mavenDeps, daqRelease=None,
            repoDir=None):
    """
    Run the Java program after adding all requested pDAQ and external jar
    files in the CLASSPATH envvar
    """
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

    # fix any extra java arguments
    for i in range(len(args.extraJava)):
        args.extraJava[i] = "-X" + args.extraJava[i]
    runJava(args.app, args.extraJava, args.extra, args.daqDeps, mavenDeps,
            daqRelease=args.daqRelease, repoDir=args.repoDir)
