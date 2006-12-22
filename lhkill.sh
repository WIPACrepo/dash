#!/bin/bash

ps='ps axww'

echo "Killing existing components..."
./CnCServer.py -k
./DAQRun.py    -k 

$ps | egrep 'java icecube.daq.juggler.toybox.DAQCompApp' | grep -v grep | awk '{print $1}' | xargs kill -9
$ps | egrep 'java icecube.daq.eventBuilder.EBComponent'  | grep -v grep | awk '{print $1}' | xargs kill -9
$ps | egrep 'java icecube.daq.trigger.component.IniceTriggerComponent'\
                                                         | grep -v grep | awk '{print $1}' | xargs kill -9
$ps | egrep 'java icecube.daq.trigger.component.GlobalTriggerComponent'\
                                                         | grep -v grep | awk '{print $1}' | xargs kill -9
$ps | egrep 'java -Dicecube.daq.stringhub'               | grep -v grep | awk '{print $1}' | xargs kill -9
