#!/usr/bin/env python
#
# Raspberry Pi push button control script for Pi-hole (https://pi-hole.net/).
# Inspired by http://thetimmy.silvernight.org/pages/endisbutton/
#
# Tested with: 
# - Pi-hole 2.9.5
# - Python 2.7.9
# - Raspberry Pi 2 running Raspbian Jessie
#
# Requires pihole command line utility in system path.
#
import RPi.GPIO as GPIO
import subprocess
import time
import threading
import argparse
import logging
import logging.handlers
import sys


# constants
PIN_STATUS_LED = 38
PIN_PUSH_BUTTON = 40

# Pi-hole status  polling interval in seconds
PIHOLE_POLLING_INTERVAL = 10


# variables
buttonEvent = threading.Event()
shutdown = False


def isPiHoleEnabled():
    """
    Returns True if Pi-hole is enabled, False otherwise.
    Calls the command line utility 'pihole' to retrieve the state.
    TODO: use future Pi-hole API once released
    """
    p = subprocess.Popen(['pihole', 'status'], stdout=subprocess.PIPE)
    return "Enabled" in p.communicate()[0]

def enablePiHole():
    """
    Calls the command line utility 'pihole enable' and updates the LED state.
    TODO: use future Pi-hole API once released
    """
    subprocess.call(['pihole', 'enable'])
    setStatusEnabled()
 
def disablePiHole():
    """
    Calls the command line utility 'pihole disable' and updates the LED state.
    TODO: use future Pi-hole API once released
    """
    subprocess.call(['pihole', 'disable'])
    setStatusDisabled()

def setStatusEnabled():
    """
    Switches off LED for enabled state
    """
    GPIO.output(PIN_STATUS_LED, False)
    
def setStatusDisabled():
    """
    Switches on LED for enabled state
    """
    GPIO.output(PIN_STATUS_LED, True)
    
def togglePiHoleStatus():
    """
    Enables Pi-hole if currently disabled or disables Pi-hole if currently enabled.
    """
    if isPiHoleEnabled():
        logger.info("Disabling ad blocking")
        disablePiHole()
    else:
        logger.info("Enabling ad blocking")
        enablePiHole()

def pushButtonHandler(event):
    logging.debug('Starting push button handler thread and waiting for events...')
    while True:
        event.wait()
        if shutdown:
            return
        logger.debug("Button pressed")
        togglePiHoleStatus()
        # get ready for next event
        event.clear()

# GPIO callback handler.
# Attention:
# executed code must return as fast as possible, otherwise callback handler is 
# called twice! Assumption: callback handler must be faster than bouncetime 
# specified in GPIO.add_event_detect
def pushButtonGPIOCallback(channel):
    # signal button handler thread
    buttonEvent.set()

# Polling function retrieving Pi-hole status to react on external status changes
# e.g. web admin gui or pihole tool
def piHoleStatusMonitorTask():
    logger.debug("Starting Pi-hole status monitoring task...")
    lastState = isPiHoleEnabled()
    logger.info("Pi-hole blocking state: %s", "Enabled" if lastState else "Disabled")
    while True:
        time.sleep(PIHOLE_POLLING_INTERVAL)
        state = isPiHoleEnabled()
        if state != lastState:
            logger.info("Pi-hole blocking state changed to: %s", 
                        "Enabled" if state else "Disabled")
        if state:
            setStatusEnabled()
        else:
            setStatusDisabled()
        lastState = state


# -- main

# initialize
parser = argparse.ArgumentParser(description="Pi-hole control button handler", 
                                 epilog="Enables and disables Pi-hole with a physical push button and shows the current state with a LED")
parser.add_argument("-l", "--loglevel", help="logging level", 
                    choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'], 
                    default="INFO")
parser.add_argument("-lf", "--logfile", help="log file")
args = parser.parse_args()

if args.logfile:
    LOG_FILENAME = args.logfile

# Configure logging to log to a file and console
logger = logging.getLogger()
logger.setLevel(args.loglevel)

consoleHandler = logging.StreamHandler()
consoleHandler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
logger.addHandler(consoleHandler)

if args.logfile:
    # Make a handler that writes to a file, making a new file at midnight and keeping some backups
    # based on: http://blog.scphillips.com/posts/2013/07/getting-a-python-script-to-run-in-the-background-as-a-service-on-boot/
    handler = logging.handlers.TimedRotatingFileHandler(args.logfile, when="midnight", backupCount=10)
    formatter = logging.Formatter('%(asctime)s %(levelname)-8s %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    # Make a class we can use to capture stdout and sterr in the log
    class RedirectLogger(object):
        def __init__(self, logger, level):
            """Needs a logger and a logger level."""
            self.logger = logger
            self.level = level

        def write(self, message):
            # Only log if there is a message (not just a new line)
            if message.rstrip() != "":
                self.logger.log(self.level, message.rstrip())

    # Replace stdout with logging to file at INFO level
    sys.stdout = RedirectLogger(logger, logging.INFO)
    # Replace stderr with logging to file at ERROR level
    sys.stderr = RedirectLogger(logger, logging.ERROR)

# start server
logger.info("Starting Pi-hole control button handler")

# turns off text warnings
GPIO.setwarnings(False)

# sets up GPIO Pin Numbering to Raspbery Pi Board Layout;
# pin 1 is 3.3v closest to the status LEDs located in the corner of the Raspberry Pi board.
GPIO.setmode(GPIO.BOARD)

# sets pins as outputs
GPIO.setup(PIN_STATUS_LED, GPIO.OUT)

# sets pins as inputs
GPIO.setup(PIN_PUSH_BUTTON, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.add_event_detect(PIN_PUSH_BUTTON, GPIO.RISING, callback=pushButtonGPIOCallback, bouncetime=500)

buttonHandlerThread = threading.Thread(name='pushButtonHandler',
                  target=pushButtonHandler,
                  args=(buttonEvent,))
buttonHandlerThread.start()

# start main loop
try:
    piHoleStatusMonitorTask()

# proper cleanup of background threads and GPIO settings, e.g. on ctrl+C
finally:
    shutdown = True
    buttonEvent.set()
    GPIO.remove_event_detect(PIN_PUSH_BUTTON)
    GPIO.cleanup()