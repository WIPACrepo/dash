@echo Starting a DAQ run under Windows NT
@SET CONFIGDIR=..\config
@SET LOGADDR=saxony:9001

@echo Starting Pythonic glue processes ...
start DAQRun.py -c %CONFIGDIR% -l ..\log -n
start CnCServer.py -l %LOGADDR%

@echo Bringing up the DAQ components ...

@echo #1 - EventBuilder ...
start java icecube.daq.eventBuilder.EBComponent -g %CONFIGDIR% -l %LOGADDR%
sleep 1

@echo #2 - Triggers
start java icecube.daq.trigger.component.GlobalTriggerComponent -g %CONFIGDIR% -l %LOGADDR%
start java icecube.daq.trigger.component.IniceTriggerComponent -g %CONFIGDIR% -l %LOGADDR%
sleep 1

@echo #3 - StringHub
start java -Dicecube.daq.stringhub.componentId=1001 icecube.daq.stringhub.Shell -g %CONFIGDIR% -l %LOGADDR%
