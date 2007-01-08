#!/bin/bash

ps='ps axww'

echo "Killing servers..."
./CnCServer.py -k
./DAQRun.py    -k 

echo "Killing components..."
for class in \
        icecube.daq.juggler.toybox.DAQCompApp \
        icecube.daq.eventBuilder.EBComponent \
        icecube.daq.trigger.component.IniceTriggerComponent \
        icecube.daq.trigger.component.GlobalTriggerComponent \
        icecube.daq.stringhub
do
    for p in `ps axww | egrep "java $class" | grep -v grep | awk '{print $1}'`
    do
        kill -9 $p
    done
done
