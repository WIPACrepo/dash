#!/usr/bin/env python

import argparse
import sys
import time
from DAQFakeRun import ComponentData, DAQFakeRun, FakeClient

if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument("-D", "--configDir", dest="runCfgDir",
                        default="/tmp/config",
                        help="Run configuration directory")
    parser.add_argument("-f", "--forkClients", dest="forkClients",
                        action="store_true", default=False,
                        help="Should clients be run in a separate process")
    parser.add_argument("-H", "--numberOfHubs", type=int, dest="numHubs",
                        default=2,
                        help="Number of fake hubs")
    parser.add_argument("-p", "--firstPortNumber", type=int, dest="firstPort",
                        default=FakeClient.NEXT_PORT,
                        help="First port number used for fake components")
    parser.add_argument("-q", "--quiet", dest="quiet",
                        action="store_true", default=False,
                        help="Fake components do not announce what they're"
                        " doing")
    parser.add_argument("-R", "--realNames", dest="realNames",
                        action="store_true", default=False,
                        help="Use component names without numeric prefix")
    parser.add_argument("-S", "--small", dest="smallCfg",
                        action="store_true", default=False,
                        help="Use canned 3-element configuration")
    parser.add_argument("-T", "--tiny", dest="tinyCfg",
                        action="store_true", default=False,
                        help="Use canned 2-element configuration")
    parser.add_argument("-X", "--extraHubs", type=int, dest="extraHubs",
                        default=0,
                        help="Number of extra hubs to create")

    args = parser.parse_args()

    if args.firstPort != FakeClient.NEXT_PORT:
        FakeClient.NEXT_PORT = args.firstPort

    # get list of components
    #
    if args.tinyCfg:
        compData = ComponentData.createTiny()
    elif args.smallCfg:
        compData = ComponentData.createSmall()
    else:
        compData = ComponentData.createAll(args.numHubs, not args.realNames)

    if args.extraHubs <= 0:
        extraData = None
    else:
        extraData = ComponentData.createHubs(args.extraHubs,
                                             not args.realNames, False)

    from DumpThreads import DumpThreadsOnSignal
    DumpThreadsOnSignal()

    # create run object and initial run number
    #
    runner = DAQFakeRun()
    comps = runner.createComps(compData, args.forkClients, quiet=args.quiet)
    if extraData is not None:
        extra = runner.createComps(extraData, args.forkClients,
                                   quiet=args.quiet)

    mockRunCfg = runner.createMockRunConfig(args.runCfgDir, comps)

    # run number argument was 0
    runsetId = runner.makeRunset(comps, mockRunCfg, 0)
    print "Created runset #%d" % runsetId

    try:
        while True:
            try:
                time.sleep(120)
            except KeyboardInterrupt:
                break
    finally:
        print >> sys.stderr, "Cleaning up..."
        runner.closeAll(runsetId)
