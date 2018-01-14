# coding utf-8

import os
import threading
import collections
import struct
import fcntl

#
# This part is taken from linux-source-2.6.32/include/linux/input.h
#

# Event types
EV_SYN = 0x00
EV_KEY = 0x01
EV_REL = 0x02
EV_ABS = 0x03
EV_MSC = 0x04
EV_SW = 0x05
EV_LED = 0x11
EV_SND = 0x12
EV_REP = 0x14
EV_FF = 0x15
EV_PWR = 0x16
EV_FF_STATUS = 0x17
EV_MAX = 0x1f
EV_CNT = (EV_MAX + 1)

KEY_MAX = 0x2ff

# Synchronization events
SYN_REPORT = 0
SYN_CONFIG = 1
SYN_MT_REPORT = 2

# Misc events
MSC_SERIAL = 0x00
MSC_PULSELED = 0x01
MSC_GESTURE = 0x02
MSC_RAW = 0x03
MSC_SCAN = 0x04
MSC_MAX = 0x07
MSC_CNT = (MSC_MAX + 1)

ABS_X = 0x00
ABS_Y = 0x01
ABS_PRESSURE = 0x18
ABS_MT_TOUCH_MAJOR = 0x30  # Major axis of touching ellipse
ABS_MT_TOUCH_MINOR = 0x31  # Minor axis (omit if circular)
ABS_MT_WIDTH_MAJOR = 0x32  # Major axis of approaching ellipse
ABS_MT_WIDTH_MINOR = 0x33  # Minor axis (omit if circular)
ABS_MT_ORIENTATION = 0x34  # Ellipse orientation
ABS_MT_POSITION_X = 0x35   # Center X ellipse position
ABS_MT_POSITION_Y = 0x36   # Center Y ellipse position
ABS_MT_TOOL_TYPE = 0x37    # Type of touching device
ABS_MT_BLOB_ID = 0x38      # Group a set of packets as a blob
ABS_MT_TRACKING_ID = 0x39  # Unique ID of initiated contact
ABS_MT_PRESSURE = 0x3a     # Pressure on contact area

# some ioctl base (with 0 value)
EVIOCGNAME = 2147501318
EVIOCGBIT = 2147501344
EVIOCGABS = 2149074240

keyboard_keys = {
    0x29: ('`', '~'),
    0x02: ('1', '!'),
    0x03: ('2', '@'),
    0x04: ('3', '#'),
    0x05: ('4', '$'),
    0x06: ('5', '%'),
    0x07: ('6', '^'),
    0x08: ('7', '&'),
    0x09: ('8', '*'),
    0x0a: ('9', '('),
    0x0b: ('0', ')'),
    0x0c: ('-', '_'),
    0x0d: ('=', '+'),
    0x0e: ('backspace', ),
    0x0f: ('tab', ),
    0x10: ('q', 'Q'),
    0x11: ('w', 'W'),
    0x12: ('e', 'E'),
    0x13: ('r', 'R'),
    0x14: ('t', 'T'),
    0x15: ('y', 'Y'),
    0x16: ('u', 'U'),
    0x17: ('i', 'I'),
    0x18: ('o', 'O'),
    0x19: ('p', 'P'),
    0x1a: ('[', '{'),
    0x1b: (']', '}'),
    0x2b: ('\\', '|'),
    0x3a: ('caps_lock', ),
    0x1e: ('a', 'A'),
    0x1f: ('s', 'S'),
    0x20: ('d', 'D'),
    0x21: ('f', 'F'),
    0x22: ('g', 'G'),
    0x23: ('h', 'H'),
    0x24: ('j', 'J'),
    0x25: ('k', 'K'),
    0x26: ('l', 'L'),
    0x27: (';', ':'),
    0x28: ("'", '"'),
    0xff: ('non-US-1', ),
    0x1c: ('enter', ),
    0x2a: ('shift', ),
    0x2c: ('z', 'Z'),
    0x2d: ('x', 'X'),
    0x2e: ('c', 'C'),
    0x2f: ('v', 'V'),
    0x30: ('b', 'B'),
    0x31: ('n', 'N'),
    0x32: ('m', 'M'),
    0x33: (',', '<'),
    0x34: ('.', '>'),
    0x35: ('/', '?'),
    0x36: ('shift', ),
    0x56: ('pipe', ),
    0x1d: ('ctrl', ),
    0x7D: ('super', ),
    0x38: ('alt', ),
    0x39: ('space', ),
    0x64: ('alt-gr', ),
    0x7e: ('super', ),
    0x7f: ('compose', ),
    0x61: ('ctrl', ),
    0x45: ('numlock', ),
    0x47: ('numpad7', 'home'),
    0x4b: ('numpad4', 'left'),
    0x4f: ('numpad1', 'end'),
    0x48: ('numpad8', 'up'),
    0x4c: ('numpad5', ),
    0x50: ('numpad2', 'down'),
    0x52: ('numpad0', 'insert'),
    0x37: ('numpadmul', ),
    0x62: ('numpaddivide', ),
    0x49: ('numpad9', 'page_up'),
    0x4d: ('numpad6', 'right'),
    0x51: ('numpad3', 'pagedown'),
    0x53: ('numpaddecimal', 'delete'),
    0x4a: ('numpadsubstract', ),
    0x4e: ('numpadadd', ),
    0x60: ('numpadenter', ),
    0x01: ('esc', ),
    0x3b: ('f1', ),
    0x3c: ('f2', ),
    0x3d: ('f3', ),
    0x3e: ('f4', ),
    0x3f: ('f5', ),
    0x40: ('f6', ),
    0x41: ('f7', ),
    0x42: ('f8', ),
    0x43: ('f9', ),
    0x44: ('f10', ),
    0x57: ('f11', ),
    0x58: ('f12', ),
    0x54: ('Alt+SysRq', ),
    0x46: ('Screenlock', ),
    0x67: ('up', ),
    0x6c: ('down', ),
    0x69: ('left', ),
    0x6a: ('right', ),
    0x6e: ('insert', ),
    0x6f: ('delete', ),
    0x66: ('home', ),
    0x6b: ('end', ),
    0x68: ('page_up', ),
    0x6d: ('page_down', ),
    0x63: ('print', ),
    0x77: ('pause', ),


    # TODO combinations
    # e0-37    PrtScr
    # e0-46    Ctrl+Break
    # e0-5b    LWin (USB: LGUI)
    # e0-5c    RWin (USB: RGUI)
    # e0-5d    Menu
    # e0-5f    Sleep
    # e0-5e    Power
    # e0-63    Wake
    # e0-38    RAlt
    # e0-1d    RCtrl
    # e0-52    Insert
    # e0-53    Delete
    # e0-47    Home
    # e0-4f    End
    # e0-49    PgUp
    # e0-51    PgDn
    # e0-4b    Left
    # e0-48    Up
    # e0-50    Down
    # e0-4d    Right
    # e0-35    KP-/
    # e0-1c    KP-Enter
    # e1-1d-45 77      Pause
}

keys_str = {
    'space': ' ',
    'tab': '	',
    'shift': '',
    'alt': '',
    'ctrl': '',
    'escape': '',
    'numpad1': '1',
    'numpad2': '2',
    'numpad3': '3',
    'numpad4': '4',
    'numpad5': '5',
    'numpad6': '6',
    'numpad7': '7',
    'numpad8': '8',
    'numpad9': '9',
    'numpad0': '0',
    'numpadmul': '*',
    'numpaddivide': '/',
    'numpadadd': '+',
    'numpadsubstract': '-',
}

# sizeof(struct input_event)
struct_input_event_sz = struct.calcsize('LLHHi')
struct_input_absinfo_sz = struct.calcsize('iiiiii')
sz_l = struct.calcsize('Q')


class HIDInputProvider(threading.Thread):

    options = ('min_position_x', 'max_position_x',
               'min_position_y', 'max_position_y',
               'min_pressure', 'max_pressure',
               'invert_x', 'invert_y', 'rotation')

    def __init__(self, input_fn, callback):
        super(HIDInputProvider, self).__init__()
        self.callback = callback
        self.input_fn = input_fn
        self.default_ranges = dict()
        self.uid = 0
        self.queue = collections.deque()
        self.dispatch_queue = []
        self.daemon = True

    def run(self, **kwargs):
        input_fn = self.input_fn
        dispatch_queue = self.dispatch_queue
        point = {}
        self.modifiers = []

        def process_keyboard(tv_sec, tv_usec, ev_type, ev_code, ev_value):
            if ev_type == EV_KEY:
                buttons = {
                    272: 'left',
                    273: 'right',
                    274: 'middle',
                    275: 'side',
                    276: 'extra',
                    277: 'forward',
                    278: 'back',
                    279: 'task',
                    330: 'touch',
                    320: 'pen'}

                if ev_code in buttons.keys():
                    if ev_value:
                        if 'button' not in point:
                            point['button'] = buttons[ev_code]
                            point['id'] += 1
                            if '_avoid' in point:
                                del point['_avoid']
                    elif 'button' in point:
                        if point['button'] == buttons[ev_code]:
                            del point['button']
                            point['id'] += 1
                            point['_avoid'] = True
                else:
                    if ev_value == 1:
                        z = keyboard_keys[ev_code][
                            -1 if 'shift' in self.modifiers else 0]
                        if z == 'shift' or z == 'alt':
                            self.modifiers.append(z)
                        self.callback('key_down', (
                            z.lower(), ev_code,
                            keys_str.get(z, z), self.modifiers))
                    elif ev_value == 0:
                        z = keyboard_keys[ev_code][
                            -1 if 'shift' in self.modifiers else 0]
                        self.callback('key_up', (
                            z.lower(), ev_code,
                            keys_str.get(z, z), self.modifiers))
                        if z == 'shift':
                            self.modifiers.remove('shift')

        # read until the end
        try:
            # open the input
            fd = open(input_fn, 'rb')

            # get the controler name (EVIOCGNAME)
            device_name = fcntl.ioctl(
                fd, EVIOCGNAME + (256 << 16), " " * 256).split(b'\x00')[0].decode("utf-8")
            print("Connected to {}".format(device_name))

            while fd:

                data = fd.read(struct_input_event_sz)
                if len(data) < struct_input_event_sz:
                    break

                # extract each event
                for i in range(int(len(data) / struct_input_event_sz)):
                    ev = data[i * struct_input_event_sz:]
                    # extract timeval + event infos
                    infos = struct.unpack('LLHHi', ev[:struct_input_event_sz])
                    process_keyboard(*infos)
        finally:
            fd.close()


class Listener(HIDInputProvider):
    # compatibility with pynput
    def __init__(self, on_press, on_release):
        self.on_press = on_press
        self.on_release = on_release
        super(Listener, self).__init__("/dev/input/event0", self._callback)

    def __enter__(self, *largs):
        self.start()
        while True:
            import time
            time.sleep(1)

    def __exit__(self, *largs):
        pass

    def _callback(self, name, key):
        # print("keyboard", name, key)
        if name == "key_up":
            self.on_release(key[0])
        elif name == "key_down":
            self.on_press(key[0])


class KeyCode(object):
    @classmethod
    def from_char(cls, char):
        return char


class _Key(object):
    def __getattr__(self, name):
        return name

Key = _Key()


if __name__ == "__main__":
    import time

    def on_events(*largs):
        print("event", largs)

    hid = HIDInputProvider("/dev/input/event0", on_events)
    hid.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
