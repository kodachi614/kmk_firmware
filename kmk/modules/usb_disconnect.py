import board
import digitalio
from supervisor import ticks_ms, runtime

from time import sleep

from kmk.handlers.stock import passthrough as handler_passthrough
from kmk.keys import make_key
from kmk.kmktime import check_deadline
from kmk.modules import Module


class USBDisconnect(Module):
    """
    This module will disable the keyboard, by triggering a powersave, when the runtime
    indicates that the USB is disconnected. The point is to save power by disabling LEDs
    and such when the keyboard is connected to a computer that goes to sleep.

    This module is not compatible with the Power module.
    """

    def __init__(self, powersave_pin=None):
        self.enable = False
        self.powersave_pin = powersave_pin  # Powersave pin board object
        self._powersave_start = ticks_ms()
        self._usb_last_scan = ticks_ms() - 5000
        self._psp = None  # Powersave pin object
        self._i2c = 0
        self._disconnect_time = None

        make_key(
            names=('PS_TOG',), on_press=self._ps_tog, on_release=handler_passthrough
        )
        make_key(
            names=('PS_ON',), on_press=self._ps_enable, on_release=handler_passthrough
        )
        make_key(
            names=('PS_OFF',), on_press=self._ps_disable, on_release=handler_passthrough
        )

    def __repr__(self):
        return f'USBDisconnect({self._to_dict()})'

    def _to_dict(self):
        return {
            'enable': self.enable,
            'powersave_pin': self.powersave_pin,
            '_powersave_start': self._powersave_start,
            '_usb_last_scan': self._usb_last_scan,
            '_psp': self._psp,
        }

    def during_bootup(self, keyboard):
        self._i2c_scan()
        keyboard._powerevents = []

    def before_matrix_scan(self, keyboard):
        return

    def after_matrix_scan(self, keyboard):
        if keyboard.matrix_update or keyboard.secondary_matrix_update:
            self.psave_time_reset()

    def before_hid_send(self, keyboard):
        return

    def after_hid_send(self, keyboard):
        now = ticks_ms()

        if not self.usb_scan():
            # USB isn't connected. Are we already in powersave mode?
            if self.enable:
                # Yes. Sleep for a bit to save power further.
                self.psleep()
                return

            # OK, USB isn't connected and we're not yet fully into powersave mode.
            # Do we already have a time to shut down established?

            if self._disconnect_time:
                # Yes. Is that time past?
                if now > self._disconnect_time:
                    keyboard._powerevents.append(("TIMER_FIRED", now, self._disconnect_time))
                    # Yes. Shut down the world.
                    self.enable_powersave(keyboard)
                    self._disconnect_time = None
                else:
                    # It's not time yet. Just be done.
                    pass
            else:
                # We haven't established a time yet. Do that now.
                self._disconnect_time = now + 1000
                keyboard._powerevents.append(("TIMER_START", now, self._disconnect_time))
                keyboard._trigger_powersave_enable = True
        else:
            # USB is connected. Are we in powersave mode?
            if self.enable:
                # Yes. Time to wake up!
                keyboard._powerevents.append(("WAKEUP", now, None))
                self.disable_powersave(keyboard)
            else:
                # We weren't in powersave mode, so there's nothing to do.
                pass

    def on_powersave_enable(self, keyboard):
        keyboard._trigger_powersave_enable = False
        return

    def on_powersave_disable(self, keyboard):
        keyboard._trigger_powersave_enable = False
        return

    def enable_powersave(self, keyboard):
        '''Enables power saving features'''
        if keyboard.i2c_deinit_count >= self._i2c and self.powersave_pin:
            # Allows power save to prevent RGB drain.
            # Example here https://docs.nicekeyboards.com/#/nice!nano/pinout_schematic

            if not self._psp:
                self._psp = digitalio.DigitalInOut(self.powersave_pin)
                self._psp.direction = digitalio.Direction.OUTPUT
            if self._psp:
                self._psp.value = True

        self.enable = True
        return

    def disable_powersave(self, keyboard):
        '''Disables power saving features'''
        if self._psp:
            self._psp.value = False
            # Allows power save to prevent RGB drain.
            # Example here https://docs.nicekeyboards.com/#/nice!nano/pinout_schematic

        keyboard._trigger_powersave_disable = True
        self.enable = False
        return

    def psleep(self):
        '''
        Sleeps longer and longer to save power the more time in between updates.
        '''
        if check_deadline(ticks_ms(), self._powersave_start, 60000):
            sleep(8 / 1000)
        elif check_deadline(ticks_ms(), self._powersave_start, 240000) is False:
            sleep(180 / 1000)

        return

    def psave_time_reset(self):
        self._powersave_start = ticks_ms()

    def _i2c_scan(self):
        try:
            i2c = board.I2C()
        except Exception as e:
            # No I2C.
            return

        while not i2c.try_lock():
            pass
        try:
            self._i2c = len(i2c.scan())
        finally:
            i2c.unlock()
        return

    def usb_rescan_timer(self):
        return bool(check_deadline(ticks_ms(), self._usb_last_scan, 5000) is False)

    def usb_time_reset(self):
        self._usb_last_scan = ticks_ms()
        return

    def usb_scan(self):
        return runtime.usb_connected

    def _ps_tog(self, key, keyboard, *args, **kwargs):
        if self.enable:
            keyboard._trigger_powersave_disable = True
        else:
            keyboard._trigger_powersave_enable = True

    def _ps_enable(self, key, keyboard, *args, **kwargs):
        if not self.enable:
            keyboard._trigger_powersave_enable = True

    def _ps_disable(self, key, keyboard, *args, **kwargs):
        if self.enable:
            keyboard._trigger_powersave_disable = True
