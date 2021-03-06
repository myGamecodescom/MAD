import collections
import logging
import os
import time
from abc import ABC, abstractmethod
from multiprocessing.pool import ThreadPool
from threading import Event, Thread

from utils.hamming import hamming_distance as hamming_dist
from websocket.communicator import Communicator

Location = collections.namedtuple('Location', ['lat', 'lng'])

log = logging.getLogger(__name__)


class WorkerBase(ABC):
    def __init__(self, args, id, last_known_state, websocket_handler, route_manager_daytime,
                 route_manager_nighttime, devicesettings, db_wrapper, NoOcr=False):
        # self.thread_pool = ThreadPool(processes=2)
        self._route_manager_daytime = route_manager_daytime
        self._route_manager_nighttime = route_manager_nighttime
        self._websocket_handler = websocket_handler
        self._communicator = Communicator(websocket_handler, id, args.websocket_command_timeout)
        self._id = id
        self._applicationArgs = args
        self._last_known_state = last_known_state

        self._lastScreenshotTaken = 0
        self._stop_worker_event = Event()
        self._db_wrapper = db_wrapper
        self._redErrorCount = 0
        self._lastScreenHash = None
        self._lastScreenHashCount = 0
        self._devicesettings = devicesettings
        
        if not NoOcr:
            from ocr.pogoWindows import PogoWindows
            self._pogoWindowManager = PogoWindows(self._communicator, args.temp_path)

    def start_worker(self):
        # async_result = self.thread_pool.apply_async(self._main_work_thread, ())
        t_main_work = Thread(target=self._main_work_thread)
        t_main_work.daemon = False
        t_main_work.start()
        # do some other stuff in the main process
        while not self._stop_worker_event.isSet():
            time.sleep(1)
        t_main_work.join()
        # async_result.get()
        return self._last_known_state

    def stop_worker(self):
        self._stop_worker_event.set()

    @abstractmethod
    def _main_work_thread(self):
        log.debug("Base called")
        pass

    @abstractmethod
    def _start_pogo(self):
        pass
    # routine to start pogo. Needs to be overriden since e.g. OCR worker uses screenshots for startup

    def _initRoutine(self):
        if self._applicationArgs.initial_restart is False:
            self._turnScreenOnAndStartPogo()
        else:
            if not self._start_pogo():
                while not self._restartPogo():
                    log.warning("failed starting pogo")

    def _turnScreenOnAndStartPogo(self):
        if not self._communicator.isScreenOn():
            self._communicator.startApp("de.grennith.rgc.remotegpscontroller")
            log.warning("Turning screen on")
            self._communicator.turnScreenOn()
            time.sleep(self._applicationArgs.post_turn_screen_on_delay)
        # check if pogo is running and start it if necessary
        log.warning("turnScreenOnAndStartPogo: (Re-)Starting Pogo")
        self._restartPogo()

    def _stopPogo(self):
        attempts = 0
        stopResult = self._communicator.stopApp("com.nianticlabs.pokemongo")
        pogoTopmost = self._communicator.isPogoTopmost()
        while pogoTopmost:
            attempts += 1
            if attempts > 10:
                return False
            stopResult = self._communicator.stopApp("com.nianticlabs.pokemongo")
            time.sleep(1)
            pogoTopmost = self._communicator.isPogoTopmost()
        return stopResult

    def _restartPogo(self, clear_cache=True):
        successfulStop = self._stopPogo()
        log.debug("restartPogo: stop pogo resulted in %s" % str(successfulStop))
        if successfulStop:
            if clear_cache:
                self._communicator.clearAppCache("com.nianticlabs.pokemongo")
            time.sleep(1)
            return self._start_pogo()
        else:
            return False

    def _reopenRaidTab(self):
        log.debug("_reopenRaidTab: Taking screenshot...")
        log.info("reopenRaidTab: Attempting to retrieve screenshot before checking raidtab")
        if not self._takeScreenshot():
            log.debug("_reopenRaidTab: Failed getting screenshot...")
            log.error("reopenRaidTab: Failed retrieving screenshot before checking for closebutton")
            return
        log.debug("_reopenRaidTab: Checking close except nearby...")
        pathToPass = os.path.join(self._applicationArgs.temp_path, 'screenshot%s.png' % str(self._id))
        log.debug("Path: %s" % str(pathToPass))
        self._pogoWindowManager.checkCloseExceptNearbyButton(pathToPass, self._id, 'True')
        log.debug("_reopenRaidTab: Getting to raidscreen...")
        self._getToRaidscreen(3)
        time.sleep(1)

    def _takeScreenshot(self, delayAfter=0.0, delayBefore=0.0):
        log.debug("Taking screenshot...")
        time.sleep(delayBefore)
        compareToTime = time.time() - self._lastScreenshotTaken
        log.debug("Last screenshot taken: %s" % str(self._lastScreenshotTaken))
        if self._lastScreenshotTaken and compareToTime < 0.5:
            log.debug("takeScreenshot: screenshot taken recently, returning immediately")
            log.debug("Screenshot taken recently, skipping")
            return True
        # TODO: screenshot.png needs identifier in name
        elif not self._communicator.getScreenshot(os.path.join(self._applicationArgs.temp_path, 'screenshot%s.png' % str(self._id))):
            log.error("takeScreenshot: Failed retrieving screenshot")
            log.debug("Failed retrieving screenshot")
            return False
        else:
            log.debug("Success retrieving screenshot")
            self._lastScreenshotTaken = time.time()
            time.sleep(delayAfter)
            return True

    def _checkPogoFreeze(self):
        log.debug("Checking if pogo froze")
        if not self._takeScreenshot():
            log.debug("_checkPogoFreeze: failed retrieving screenshot")
            return
        from utils.image_utils import getImageHash
        screenHash = getImageHash(os.path.join(self._applicationArgs.temp_path, 'screenshot%s.png' % str(self._id)))
        log.debug("checkPogoFreeze: Old Hash: " + str(self._lastScreenHash))
        log.debug("checkPogoFreeze: New Hash: " + str(screenHash))
        if hamming_dist(str(self._lastScreenHash), str(screenHash)) < 4 and str(self._lastScreenHash) != '0':
            log.debug("checkPogoFreeze: New und old Screenshoot are the same - no processing")
            self._lastScreenHashCount += 1
            log.debug("checkPogoFreeze: Same Screen Count: " + str(self._lastScreenHashCount))
            if self._lastScreenHashCount >= 100:
                self._lastScreenHashCount = 0
                self._restartPogo()
        else:
            self._lastScreenHash = screenHash
            self._lastScreenHashCount = 0

            log.debug("_checkPogoFreeze: done")

    def _getToRaidscreen(self, maxAttempts, again=False):
        # check for any popups (including post login OK)
        log.debug("getToRaidscreen: Trying to get to the raidscreen with %s max attempts..." % str(maxAttempts))
        pogoTopmost = self._communicator.isPogoTopmost()
        if not pogoTopmost:
            return False

        self._checkPogoFreeze()
        if not self._takeScreenshot(delayBefore=self._applicationArgs.post_screenshot_delay):
            if again:
                log.error("getToRaidscreen: failed getting a screenshot again")
                return False
            self._getToRaidscreen(maxAttempts, True)
            log.debug("getToRaidscreen: Got screenshot, checking GPS")
        attempts = 0

        if os.path.isdir(os.path.join(self._applicationArgs.temp_path, 'screenshot%s.png' % str(self._id))):
            log.error("getToRaidscreen: screenshot.png is not a file/corrupted")
            return False

        # TODO: replace self._id with device ID
        while self._pogoWindowManager.isGpsSignalLost(os.path.join(self._applicationArgs.temp_path, 'screenshot%s.png' % str(self._id)), self._id):
            log.debug("getToRaidscreen: GPS signal lost")
            time.sleep(1)
            self._takeScreenshot()
            log.warning("getToRaidscreen: GPS signal error")
            self._redErrorCount += 1
            if self._redErrorCount > 3:
                log.error("getToRaidscreen: Red error multiple times in a row, restarting")
                self._redErrorCount = 0
                self._restartPogo()
                return False
        self._redErrorCount = 0
        log.debug("getToRaidscreen: checking raidscreen")
        while not self._pogoWindowManager.checkRaidscreen(os.path.join(self._applicationArgs.temp_path, 'screenshot%s.png' % str(self._id)), self._id):
            log.debug("getToRaidscreen: not on raidscreen...")
            if attempts > maxAttempts:
                # could not reach raidtab in given maxAttempts
                log.error("getToRaidscreen: Could not get to raidtab within %s attempts" % str(maxAttempts))
                return False
            self._checkPogoFreeze()
            # not using continue since we need to get a screen before the next round...
            found = self._pogoWindowManager.lookForButton(os.path.join(self._applicationArgs.temp_path, 'screenshot%s.png' % str(self._id)), 2.20, 3.01)
            if found:
                log.info("getToRaidscreen: Found button (small)")

            if not found and self._pogoWindowManager.checkCloseExceptNearbyButton(
                    os.path.join(self._applicationArgs.temp_path, 'screenshot%s.png' % str(self._id)), self._id):
                log.info("getToRaidscreen: Found (X) button (except nearby)")
                found = True

            if not found and self._pogoWindowManager.lookForButton(os.path.join(self._applicationArgs.temp_path, 'screenshot%s.png' % str(self._id)), 1.05,
                                                             2.20):
                log.info("getToRaidscreen: Found button (big)")
                found = True

            log.info("getToRaidscreen: Previous checks found popups: %s" % str(found))
            if not found:
                log.info("getToRaidscreen: Previous checks found nothing. Checking nearby open")
                if self._pogoWindowManager.checkNearby(os.path.join(self._applicationArgs.temp_path, 'screenshot%s.png' % str(self._id)), self._id):
                    return self._takeScreenshot(delayBefore=self._applicationArgs.post_screenshot_delay)

            if not self._takeScreenshot(delayBefore=self._applicationArgs.post_screenshot_delay):
                return False

            attempts += 1
        log.debug("getToRaidscreen: done")
        return True
    
    
