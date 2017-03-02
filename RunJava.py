#!/usr/bin/env python
#
# Run a DAQ Java program
#
# Example:
#    ./RunJava.py -d daq-common -d splicer -d payload -d daq-io \
#        -m log4j:log4j:1.2.7 -m commons-logging:commons-logging:1.0.3 \
#        icecube.daq.io.PayloadDumper physics_123456_0_0_2511.dat


import datetime
import os
import select
import signal
import subprocess
import sys

from distutils.version import LooseVersion


def add_arguments(parser):
    parser.add_argument("-D", "--repo-dir", dest="repo_dir",
                        help="Local Maven repository cache")
    parser.add_argument("-d", "--daq-dependency", dest="daq_deps",
                        action="append", default=[],
                        help="DAQ project dependency")
    parser.add_argument("-m", "--maven-dependency", dest="maven_deps",
                        action="append", default=[],
                        help="Maven jar dependency")
    parser.add_argument("-r", "--daq-release", dest="daq_release",
                        help="DAQ Maven release")
    parser.add_argument("-X", "--extra-java", dest="extra_java",
                        action="append", default=[],
                        help="Extra Java arguments")

    parser.add_argument(dest="app",
                        help="Fully qualified Java application class")
    parser.add_argument(dest="extra", nargs="*")


def jzmq_native_specifier():
    import platform

    system = platform.system()
    machine = platform.machine()
    if system == "Linux" and machine == "x86_64":
        machine = "amd64"
    return machine + "-" + system


class RunnerException(Exception):
    """Exception in Java code runner"""
    pass


class RunData(object):
    """Run statistics (return code, duration, etc.)"""

    def __init__(self, java_args, main_class, sys_args):
        """
        Create a RunData object

        java_args - arguments for the 'java' program
        main_class - fully-qualified name of class whose main() method
                    will be run
        sys_args - arguments for the class being run
        """
        self.__exitsig = False
        self.__killsig = False

        self.__returncode = None
        self.__run_time = None
        self.__wait_time = None

        self.__cmd = ["java", ]
        if java_args is not None:
            if type(java_args) == str:
                self.__cmd.append(java_args)
            elif type(java_args) == list or type(java_args) == tuple:
                self.__cmd += java_args
            else:
                raise RunnerException("Bad java_args type %s for %s" %
                                      (type(java_args), java_args))

        self.__cmd.append(main_class)
        if sys_args is not None:
            self.__cmd += sys_args

    @classmethod
    def __timediff(cls, start_time, end_time):
        """
        Convert the difference between two times to a floating point value
        """
        diff = end_time - start_time
        return float(diff.seconds) + \
            (float(diff.microseconds) / 1000000.0)

    @property
    def command(self):
        """Return the command which was run"""
        return self.__cmd

    @property
    def exit_signal(self):
        """Return the signal which caused the program to exit (or None)"""
        return self.__exitsig

    @property
    def kill_signal(self):
        """Return the signal which caused the program to be killed (or None)"""
        return self.__killsig

    def process(self, line, is_stderr=False):
        """Process a line of output from the program"""
        if not is_stderr:
            sys.stdout.write(line)
            sys.stdout.flush()
        else:
            sys.stderr.write(line)

    @property
    def returncode(self):
        """Return the POSIX return code"""
        return self.__returncode

    @property
    def run_time(self):
        """Return the time needed to run the program"""
        return self.__run_time

    def set_exit_signal(self, val):
        """Record the signal which caused the program to exit"""
        self.__exitsig = val

    def set_kill_signal(self, val):
        """Record the signal which caused the program to be killed"""
        self.__killsig = val

    def set_return_code(self, val):
        """Record the POSIX return code"""
        self.__returncode = val

    def set_run_time(self, start_time, end_time):
        """Record the run time"""
        self.__run_time = self.__timediff(start_time, end_time)

    def set_wait_time(self, start_time, end_time):
        """Record the wait time"""
        self.__wait_time = self.__timediff(start_time, end_time)

    @property
    def wait_time(self):
        """Return the time spent waiting for the program to finish"""
        return self.__wait_time


class JavaRunner(object):
    """Wrapper which runs a Java program"""

    # Default DAQ version string
    __DEFAULT_DAQ_RELEASE = "1.0.0-SNAPSHOT"
    # IceCube subdirectory in Maven repository
    __DAQ_REPO_SUBDIR = "edu/wisc/icecube"

    # current distribution directory
    __DIST_DIR = None
    # release used to find current distribution directory
    __DIST_RELEASE = None
    # Maven repository
    __MAVEN_REPO = None
    # $PDAQ_HOME envvar
    __PDAQ_HOME = None

    def __init__(self, main_class, daq_deps, maven_deps, daq_release=None,
                 repo_dir=None):
        self.__main_class = main_class
        self.__classpath = self.__build_class_path(daq_deps, maven_deps,
                                                   daq_release=daq_release,
                                                   repo_dir=repo_dir)
        self.__proc = None
        self.__killsig = None
        self.__exitsig = None

    @classmethod
    def __build_class_path(cls, daq_deps, maven_deps, daq_release=None,
                           repo_dir=None):
        """
        Build a list of paths which includes all requested pDAQ and external
        jar files.
        """
        if daq_release is None:
            daq_release = cls.__DEFAULT_DAQ_RELEASE

        if repo_dir is None:
            tmpDir = cls.__maven_repository_path()
            if tmpDir is not None:
                repo_dir = tmpDir

        pdaq_home = cls.__pdaq_home()
        dist_dir = cls.__distribution_path(daq_release)

        daqjars = cls.__find_DAQ_jars(daq_deps, daq_release, pdaq_home,
                                      dist_dir, repo_dir)

        mavenjars = cls.__find_maven_jars(maven_deps, repo_dir, dist_dir)

        return daqjars + mavenjars

    @classmethod
    def __build_jar_name(cls, name, vers, extra=None):
        """Build a versioned jar file name"""
        if extra is None:
            return name + "-" + vers + ".jar"
        return name + "-" + vers + "-" + extra + ".jar"

    def __build_java_cmd(self, java_args, app_args):
        """
        Build a command line to run the specified application
        """
        cmd = ["java"]
        if java_args is not None:
            if isinstance(java_args, str):
                cmd.append(java_args)
            elif isinstance(java_args, list) or isinstance(java_args, tuple):
                cmd += java_args
            else:
                raise RunnerException("Bad java_args type %s for %s" %
                                      (type(java_args), java_args))

        cmd.append(self.__main_class)
        if app_args is not None and len(app_args) > 0:
            cmd += app_args

        return cmd

    @classmethod
    def __distribution_path(cls, daq_release):
        """Distribution directory"""
        if cls.__DIST_RELEASE is None or cls.__DIST_RELEASE != daq_release:
            # clear cached path
            cls.__DIST_DIR = None

            pdaq_home = cls.__pdaq_home()
            if pdaq_home is not None:
                tmpDir = os.path.join(pdaq_home, "target",
                                      "pDAQ-" + daq_release + "-dist", "lib")
                if os.path.exists(tmpDir):
                    cls.__DIST_RELEASE = daq_release
                    cls.__DIST_DIR = tmpDir
        return cls.__DIST_DIR

    @classmethod
    def __find_DAQ_jar(cls, proj, daq_release, pdaq_home, dist_dir, repo_dir):
        jarname = cls.__build_jar_name(proj, daq_release)

        # check foo/target/foo-X.Y.Z.jar (if we're in top-level project dir)
        projjar = os.path.join(proj, "target", jarname)
        if os.path.exists(projjar):
            return projjar

        # check ../foo/target/foo-X.Y.Z.jar (in case we're in a project subdir)
        tmpjar = os.path.join("..", projjar)
        if os.path.exists(tmpjar):
            return tmpjar

        # check $PDAQHOME/foo/target/foo-X.Y.Z.jar
        if pdaq_home is not None:
            tmpjar = os.path.join(pdaq_home, projjar)
            if os.path.exists(tmpjar):
                return tmpjar

        if dist_dir is not None:
            # check $PDAQHOME/target/pDAQ-X.Y.Z-dist/lib/foo-X.Y.Z.jar
            tmpjar = os.path.join(dist_dir, jarname)
            if os.path.exists(tmpjar):
                return tmpjar

        if repo_dir is not None:
            # check ~/.m2/repository/edu/wisc/icecube/foo/X.Y.Z/foo-X.Y.Z.jar
            tmpjar = os.path.join(repo_dir, cls.__DAQ_REPO_SUBDIR, proj,
                                  daq_release, jarname)
            if os.path.exists(tmpjar):
                return tmpjar

        raise SystemExit("Cannot find %s jar file %s" % (proj, jarname))

    @classmethod
    def __find_DAQ_jars(cls, daq_deps, daq_release, pdaq_home, dist_dir,
                        repo_dir):
        """
        Find pDAQ jar files in all likely places, starting with the current
        project directory
        """
        jars = []
        if daq_deps is not None:
            for proj in daq_deps:
                jars.append(cls.__find_DAQ_jar(proj, daq_release, pdaq_home,
                                               dist_dir, repo_dir))

        return jars

    @classmethod
    def __find_repo_jar(cls, repo_dir, dist_dir, proj, name, vers, extra=None):
        """
        Find a jar file in the Maven repository which is at or after the
        version specified by 'vers'
        """
        jarname = cls.__build_jar_name(name, vers, extra)

        if repo_dir is not None:
            projdir = os.path.join(repo_dir, proj, name)
            if os.path.exists(projdir):
                tmpjar = os.path.join(projdir, vers, jarname)
                if os.path.exists(tmpjar):
                    return tmpjar

                overs = LooseVersion(vers)
                for entry in os.listdir(projdir):
                    nvers = LooseVersion(entry)
                    if overs < nvers:
                        tmpname = cls.__build_jar_name(name, entry, extra)
                        tmpjar = os.path.join(projdir, entry, tmpname)
                        if os.path.exists(tmpjar):
                            print >>sys.stderr, "WARNING: Using %s version" \
                                "%s instead of requested %s" % \
                                (name, entry, vers)
                            return tmpjar

        if dist_dir is not None:
            tmpjar = os.path.join(dist_dir, jarname)
            if os.path.exists(tmpjar):
                return tmpjar

            overs = LooseVersion(vers)
            namedash = name + "-"
            for entry in os.listdir(dist_dir):
                if entry.startswith(namedash):
                    jarext = entry.find(".jar")
                    if jarext > 0:
                        vstr = entry[len(namedash):jarext]
                        nvers = LooseVersion(vstr)
                        if overs <= nvers:
                            print >>sys.stderr, "WARNING: Using %s version" \
                                " %s instead of requested %s" % \
                                (name, vstr, vers)
                            return os.path.join(dist_dir, entry)

        raise SystemExit("Cannot find Maven jar file %s" % jarname)

    @classmethod
    def __find_maven_jars(cls, maven_jars, repo_dir, dist_dir):
        """
        Find requested jar files in either the Maven repository or in the
        pDAQ distribution directory
        """
        jars = []
        if maven_jars is not None:
            for tup in maven_jars:
                if len(tup) == 3:
                    (proj, name, version) = tup
                    extra = None
                elif len(tup) == 4:
                    (proj, name, version, extra) = tup
                else:
                    raise RunnerException("Bad repository tuple %s" % (tup))

                jars.append(cls.__find_repo_jar(repo_dir, dist_dir, proj, name,
                                                version, extra))

        return jars

    @classmethod
    def __maven_repository_path(cls):
        """Maven repository directory"""
        if cls.__MAVEN_REPO is None and os.environ.has_key("HOME"):
            tmpDir = os.path.join(os.environ["HOME"], ".m2", "repository")
            if tmpDir is not None and os.path.exists(tmpDir):
                cls.__MAVEN_REPO = tmpDir
        return cls.__MAVEN_REPO

    @classmethod
    def __pdaq_home(cls):
        """Current active pDAQ directory"""
        if cls.__PDAQ_HOME is None and os.environ.has_key("PDAQ_HOME"):
            tmpDir = os.environ["PDAQ_HOME"]
            if tmpDir is not None and os.path.exists(tmpDir):
                cls.__PDAQ_HOME = tmpDir
        return cls.__PDAQ_HOME

    def __quickexit(self, sig, frame):
        """Kill the program if we get an interrupt signal"""
        self.__send_signal(sig, frame)
        self.__exitsig = sig

    def __run(self, command, debug=False):
        """Run the Java program"""
        if debug:
            print " ".join(command)

        self.__proc = subprocess.Popen(command, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE,
                                       preexec_fn=os.setsid)
        num_err = 0
        while True:
            reads = [self.__proc.stdout.fileno(), self.__proc.stderr.fileno()]
            try:
                ret = select.select(reads, [], [])
            except select.error:
                 # ignore a single interrupt
                if num_err > 0:
                    break
                num_err += 1
                continue

            for fd in ret[0]:
                if fd == self.__proc.stdout.fileno():
                    line = self.__proc.stdout.readline()
                    sys.stdout.write(line)
                    sys.stdout.flush()
                if fd == self.__proc.stderr.fileno():
                    line = self.__proc.stderr.readline()
                    sys.stderr.write(line)

            if self.__proc.poll() is not None:
                break

        self.__proc.stdout.close()
        self.__proc.stderr.close()

        self.__proc.wait()

        rtncode = self.__proc.returncode
        self.__proc = None
        return rtncode

    def __run_command(self, data, debug=False):
        """Run the Java program, tracking relevant run-related statistics"""
        self.__killsig = None
        self.__exitsig = None

        if debug:
            print " ".join(data.command)

        start_time = datetime.datetime.now()

        self.__proc = subprocess.Popen(data.command, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE,
                                       preexec_fn=os.setsid)
        num_err = 0
        while True:
            reads = [self.__proc.stdout.fileno(), self.__proc.stderr.fileno()]
            try:
                ret = select.select(reads, [], [])
            except select.error:
                 # ignore a single interrupt
                if num_err > 0:
                    break
                num_err += 1
                continue

            for fd in ret[0]:
                if fd == self.__proc.stdout.fileno():
                    line = self.__proc.stdout.readline()
                    data.process(line, False)
                if fd == self.__proc.stderr.fileno():
                    line = self.__proc.stderr.readline()
                    data.process(line, True)

            if self.__proc.poll() is not None:
                break

        self.__proc.stdout.close()
        self.__proc.stderr.close()

        end_time = datetime.datetime.now()

        self.__proc.wait()

        wait_time = datetime.datetime.now()

        data.set_return_code(self.__proc.returncode)

        data.set_run_time(start_time, end_time)
        data.set_wait_time(end_time, wait_time)

        data.set_exit_signal(self.__exitsig)
        data.set_kill_signal(self.__killsig)

        self.__proc = None

    def __send_signal(self, sig, frame):
        """Send a signal to the process"""
        if self.__proc is not None:
            os.killpg(self.__proc.pid, sig)

    def __set_class_path(self, debug=False):
        if not os.environ.has_key("CLASSPATH"):
            cp = self.__classpath
        else:
            cp = self.__classpath[:] + os.environ["CLASSPATH"].split(":")

        if len(cp) > 0:
            os.environ["CLASSPATH"] = ":".join(cp)
            if debug:
                print "export CLASSPATH=\"%s\"" % os.environ["CLASSPATH"]

    def oldrun(self, java_args=None, app_args=None, debug=False):
        cmd = self.__build_java_cmd(java_args, app_args)

        self.__set_class_path(debug=debug)

        signal.signal(signal.SIGINT, self.__quickexit)
        signal.signal(signal.SIGQUIT, self.__send_signal)

        self.__killsig = None
        self.__exitsig = None

        try:
            rtncode = self.__run(cmd, debug)
            killsig = self.__killsig
            exitsig = self.__exitsig
            return rtncode, killsig, exitsig
        finally:
            signal.signal(signal.SIGINT, signal.SIG_DFL)
            signal.signal(signal.SIGQUIT, signal.SIG_DFL)

            self.__killsig = None
            self.__exitsig = None


    def kill(self, sig):
        self.send_signal(sig, None)
        self.__killsig = sig

    def quickexit(self, sig, frame):
        """Kill the program if we get an interrupt signal"""
        self.send_signal(sig, frame)
        self.__exitsig = sig

    def run(self, java_args=None, sys_args=None, debug=False):
        """Run the Java program, handling ^C or ^\ as appropriate"""
        self.__set_class_path(debug=debug)

        signal.signal(signal.SIGINT, self.quickexit)
        signal.signal(signal.SIGQUIT, self.send_signal)

        try:
            rundata = RunData(java_args, self.__main_class, sys_args)
            self.__run_command(rundata, debug)
        finally:
            signal.signal(signal.SIGINT, signal.SIG_DFL)
            signal.signal(signal.SIGQUIT, signal.SIG_DFL)

        return rundata

    def send_signal(self, sig, frame):
        """Send a signal to the process"""
        if self.__proc is not None:
            os.killpg(self.__proc.pid, sig)

def runJava(main_class, java_args, app_args, daq_deps, maven_deps,
            daq_release=None, repo_dir=None):
    """
    Run the Java program after adding all requested pDAQ and external jar
    files in the CLASSPATH envvar
    """
    runner = JavaRunner(main_class, daq_deps, maven_deps,
                        daq_release=daq_release, repo_dir=repo_dir)

    runner.run(java_args, app_args)


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    add_arguments(p)
    args = p.parse_args()

    # convert java dependencies into triplets
    maven_deps = []
    for j in args.maven_deps:
        jtup = j.split(":")
        if len(jtup) < 2 or len(jtup) > 3:
            raise SystemExit("Invalid Maven dependency \"%s\"" % j)

        maven_deps.append(jtup)

    # fix any extra java arguments
    for i in range(len(args.extra_java)):
        args.extra_java[i] = "-X" + args.extra_java[i]
    runJava(args.app, args.extra_java, args.extra, args.daq_deps, maven_deps,
            daq_release=args.daq_release, repo_dir=args.repo_dir)
