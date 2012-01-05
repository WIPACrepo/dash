#!/usr/bin/env python

import optparse, sys, time
from DAQFakeRun import ComponentData, DAQFakeRun, FakeClient

if __name__ == "__main__":
    parser = optparse.OptionParser()

    parser.add_option("-c", "--config", type="string", dest="runCfgDir",
                      action="store", default="/tmp/config",
                      help="Run configuration directory")
    parser.add_option("-f", "--forkClients", dest="forkClients",
                      action="store_true", default=False,
                      help="Should clients be run in a separate process")
    parser.add_option("-H", "--numberOfHubs", type="int", dest="numHubs",
                      action="store", default=2,
                      help="Number of fake hubs")
    parser.add_option("-p", "--firstPortNumber", type="int", dest="firstPort",
                      action="store", default=FakeClient.NEXT_PORT,
                      help="First port number used for fake components")
    parser.add_option("-R", "--realNames", dest="realNames",
                      action="store_true", default=False,
                      help="Use component names without numeric prefix")
    parser.add_option("-S", "--small", dest="smallCfg",
                      action="store_true", default=False,
                      help="Use canned 3-element configuration")
    parser.add_option("-T", "--tiny", dest="tinyCfg",
                      action="store_true", default=False,
                      help="Use canned 2-element configuration")
    parser.add_option("-X", "--extraHubs", type="int", dest="extraHubs",
                      action="store", default=0,
                      help="Number of extra hubs to create")

    opt, args = parser.parse_args()

    if opt.firstPort != FakeClient.NEXT_PORT:
        FakeClient.NEXT_PORT = opt.firstPort

    # get list of components
    #
    if opt.tinyCfg:
        compData = ComponentData.createTiny()
    elif opt.smallCfg:
        compData = ComponentData.createSmall()
    else:
        compData = ComponentData.createAll(opt.numHubs, not opt.realNames)


    if opt.extraHubs <= 0:
        extraData = None
    else:
        extraData = ComponentData.createHubs(opt.extraHubs, not opt.realNames, False)

    from DumpThreads import DumpThreadsOnSignal
    DumpThreadsOnSignal()

    # create run object and initial run number
    #
    runner = DAQFakeRun()
    comps = runner.createComps(compData, opt.forkClients)
    if extraData is not None:
        extra = runner.createComps(extraData, opt.forkClients)

    mockRunCfg = runner.createMockRunConfig(opt.runCfgDir, comps)

    runsetId = runner.makeRunset(comps, mockRunCfg)
    print "Created runset #%d" % runsetId

    try:
        while True:
            try:
                time.sleep(120)
            except KeyboardInterrupt:
                break
    finally:
        print >>sys.stderr, "Cleaning up..."
        runner.closeAll(runsetId)
