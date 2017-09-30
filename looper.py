#!/usr/bin/env python
"""
UI:
    Display made for https://learn.adafruit.com/adafruit-pioled-128x32-mini-oled-for-raspberry-pi/
    Font are:
        https://fonts2u.com/fairfax.font
        https://fonts2u.com/fairfax-bold.font
"""

import os
import rtmidi
import threading
from time import time
from functools import partial
from pynput.keyboard import Listener, Key, KeyCode
from rtmidi.midiconstants import (ALL_SOUND_OFF, CONTROL_CHANGE,
                                  RESET_ALL_CONTROLLERS, NOTE_ON,
                                  NOTE_OFF)
from PIL import Image, ImageDraw, ImageFont

try:
    import tkinter as tk
    from PIL import ImageTk
except:

    tk = None

global looper
Char = KeyCode.from_char
midi_in_callback = None
SIZE = (128, 32)
DPI = 10
size = [x * DPI for x in SIZE]
image = None


class Track(object):
    def __init__(self, index):
        self.index = index
        self.notes = []
        self.record = False
        self.mute = False
        self.on = []

    def midi_in_callback(self, clock, m, data):
        print("track {}: {} {}".format(self.index, clock, m, data))
        if not self.record:
            return
        status = m[0] & 0xF0
        if status in (NOTE_ON, NOTE_OFF):
            self.notes.append((clock, m, data))

    def start_recording(self):
        self.record = True
        self.notes = []
        self.off()

    def stop_recording(self):
        self.record = False

    def toggle_mute(self):
        self.mute = not self.mute
        if self.mute:
            self.off()

    def get_notes_between(self, start, end):
        if self.record or self.mute:
            return
        for clock, message, data in self.notes:
            if clock >= start and clock < end:
                yield message

    def send_notes_between(self, start, end):
        for note in self.get_notes_between(start, end):
            m = note[0] & 0xF0
            s = (note[0] & 0x0F, note[1])
            if m == NOTE_ON:
                self.on.append(s)
            elif m == NOTE_OFF:
                if s in self.on:
                    self.on.remove(s)
            self.midiout.send_message(note)

    def off(self):
        for chn, note in self.on:
            self.midiout.send_message([NOTE_OFF | chn, note, 0])
        self.on = []


class Player(threading.Thread):
    def __init__(self):
        super(Player, self).__init__()
        self.is_playing = threading.Event()
        self.is_playing.clear()
        self.daemon = True
        self.quit = False
        self.looper = None
        self.restart = False
        self.time_start = 0
        self.start()
        self.midiout = rtmidi.MidiOut()
        self.midiout.open_port(1)

    def run(self):
        prev_deltatime = 0
        deltatime = 0
        play_notes = self.play_notes

        while not self.quit:
            looper = self.looper
            if not looper:
                continue

            if not self.is_playing.is_set():
                self.is_playing.wait()
                continue

            if self.restart:
                prev_deltatime = deltatime = 0
                self.restart = False

            length = looper.length
            prev_deltatime = deltatime
            deltatime = (time() - self.time_start) % length

            if deltatime > prev_deltatime:
                play_notes(looper, prev_deltatime, deltatime)
            else:
                play_notes(looper, prev_deltatime, length)
                play_notes(looper, 0, deltatime)

    def play_notes(self, looper, start, stop):
        for track in list(looper.tracks.values()):
            track.midiout = self.midiout
            track.send_notes_between(start, stop)

    def toggle_play(self):
        if self.is_playing.is_set():
            return self.stop()
        self.play()

    def play(self):
        if self.is_playing.is_set():
            return
        self.time_start = time()
        self.restart = True
        self.is_playing.set()

    def stop(self):
        if not self.is_playing.is_set():
            return
        self.is_playing.clear()
        self.notes_off()

    def panic(self):
        send = self.midiout.send_message
        self.notes_off()
        for channel in range(16):
            send([CONTROL_CHANGE, ALL_SOUND_OFF, 0])
            send([CONTROL_CHANGE, RESET_ALL_CONTROLLERS, 0])

    def notes_off(self):
        for track in list(looper.tracks.values()):
            track.off()

    @property
    def deltatime(self):
        return time() - self.time_start


class Looper(object):
    commands = {
        Char("r"): "reset",

        Char("w"): ("record", [1]),
        Char("x"): ("record", [2]),
        Char("c"): ("record", [3]),
        Char("v"): ("record", [4]),
        Char("b"): ("record", [5]),
        Char("n"): ("record", [6]),
        Char(","): ("record", [7]),
        Char(";"): ("record", [8]),

        Char("q"): ("mute", [1]),
        Char("s"): ("mute", [2]),
        Char("d"): ("mute", [3]),
        Char("f"): ("mute", [4]),
        Char("g"): ("mute", [5]),
        Char("h"): ("mute", [6]),
        Char("j"): ("mute", [7]),
        Char("k"): ("mute", [8]),

        Key.space: "toggle_play",
        Key.esc: "panic",
        Key.caps_lock: "toggle_record_on_first_note"
    }

    shift_commands = {}
    ctrl_commands = {}

    def __init__(self):
        self.tracks = {}
        self.shift = False
        self.ctrl = False
        self._key_pressed = []
        self._record_to_track = None
        self.record_on_first_note = True
        self.player = Player()
        self.player.looper = self
        self.bpm = 120
        self.beat_per_measures = 4
        self.measures = 4
        self.recalculate_length()

    def recalculate_length(self):
        self.beat_length = 60 / float(self.bpm)
        self.measure_length = self.beat_length * self.beat_per_measures
        self.length = self.measure_length * self.measures

    @property
    def measure(self):
        if not self.player.is_playing.is_set():
            return 1
        return 1 + int(self.player.deltatime / self.measure_length) % self.measures

    @property
    def beat(self):
        if not self.player.is_playing.is_set():
            return 1
        return 1 + int((self.player.deltatime / self.beat_length) % self.beat_per_measures)

    def reset(self):
        self.stop()
        self.length = None
        self.tracks = {}

    def panic(self):
        self.player.panic()

    def toggle_play(self):
        self.player.toggle_play()

    def play(self):
        if self.length is None:
            return
        self.player.play()

    def stop(self):
        self.player.stop()

    def toggle_record_on_first_note(self):
        self.record_on_first_note = not self.record_on_first_note

    def record(self, index):
        if not self.record_on_first_note:
            self.play()
        self._record_to_track = track = self.get_track(index)
        track.start_recording()

    def mute(self, index):
        self.get_track(index).toggle_mute()

    def record_after(self, index):
        self._record_to_track.stop_recording()
        self._record_to_track = None

    def midi_in_callback(self, wallclock, message, data):
        if not self._record_to_track:
            return

        is_note = (message[0] & 0xF0 == NOTE_ON)
        if not is_note:
            return
        if self.record_on_first_note:
            if not self.player.is_playing.is_set():
                self.player.play()
        deltatime = self.player.deltatime % self.length
        self._record_to_track.midi_in_callback(deltatime, message, data)

    def get_track(self, index):
        if index not in self.tracks:
            self.tracks[index] = Track(index)
        return self.tracks[index]

    def dispatch_command(self, key, after=False):
        cmd, func, args = self.get_command(key, after)
        if not cmd:
            return
        print("Execute: {}".format(cmd))
        func(*args)

    def get_command(self, key, after=False):
        if self.shift:
            commands = self.shift_commands
        elif self.ctrl:
            commands = self.ctrl_commands
        else:
            commands = self.commands
        cmd = commands.get(key)
        if not cmd:
            return None, None, None
        if isinstance(cmd, tuple):
            cmd, args = cmd
        else:
            args = []
        if after:
            cmd += "_after"
        if hasattr(self, cmd):
            func = getattr(self, cmd)
        else:
            cmd = func = args = None
        return cmd, func, args

    def on_key_pressed(self, key):
        if key == Key.shift:
            self.shift = True
        elif key == Key.ctrl:
            self.ctrl = True
        else:
            if key in self._key_pressed:
                return
            self._key_pressed.append(key)
            self.dispatch_command(key)

    def on_key_released(self, key):
        if key == Key.shift:
            self.shift = False
        elif key == Key.ctrl:
            self.ctrl = False
        elif key in self._key_pressed:
            self._key_pressed.remove(key)
            self.dispatch_command(key, after=True)


class MidiInputHandler(object):
    def __init__(self, port):
        self.port = port
        self._wallclock = time()

    def __call__(self, event, data=None):
        message, deltatime = event
        self._wallclock += deltatime
        if looper:
            looper.midi_in_callback(self._wallclock, message, data)
        print("[%s] @%0.6f %r" % (self.port, self._wallclock, message))


class UI(threading.Thread):
    def __init__(self):
        super(UI, self).__init__()
        width, height = size
        self.image = Image.new('1', (width, height))
        self.draw = ImageDraw.Draw(self.image)
        self.font = ImageFont.truetype("fonts/Fairfax.ttf", size=10 * DPI)
        self.daemon = True
        self.start()

    def run(self):
        if tk:
            self.root = tk.Tk()
            self.root.title("Midi Looper")
            self.root.geometry("{}x{}+0+0".format(*size))
            self.image1 = ImageTk.PhotoImage(self.image)
            self.panel = tk.Label(self.root, image=self.image1)
            self.panel.pack()
            self.root.after(50, self.render_and_display)
            self.root.mainloop()

    def render_and_display(self):
        self.render()
        self.display()
        self.root.after(50, self.render_and_display)

    def render(self):
        # ▶◼⚪⚫ (~25 chars width)
        width, height = size
        d = self.draw
        font = self.font
        player = looper.player

        def text(x, y, message):
            d.text((x * DPI, y * DPI), message, font=font, fill=255)

        d.rectangle((0, 0, width, height), outline=0, fill=0)

        state = u"‣" if player.is_playing.is_set() else u"▪"
        top = "{state} {bpm} {measure}-{measures} {beat}{beatleft}".format(
            state=state,
            bpm=looper.bpm,
            measure=looper.measure,
            measures=looper.measures,
            beat="⚫" * looper.beat,
            beatleft="⚪" * (looper.beat_per_measures - looper.beat)
        )

    def display(self):
        if tk:
            self.image1 = ImageTk.PhotoImage(self.image)
            self.panel.configure(image=self.image1)


def on_keyboard_pressed(key):
    if looper:
        looper.on_key_pressed(key)


def on_keyboard_released(key):
    if looper:
        looper.on_key_released(key)


def hide_keyboard():
    os.system("stty -echo")


def show_keyboard():
    os.system("stty echo")


try:
    hide_keyboard()

    looper = Looper()
    midi_in = rtmidi.MidiIn()
    port = 1
    port_name = midi_in.get_ports()[port]
    midi_in.set_callback(MidiInputHandler(port_name))
    midi_in.open_port(port)

    ui = UI()

    with Listener(on_press=on_keyboard_pressed, on_release=on_keyboard_released) as listener:
        listener.join()

finally:
    show_keyboard()
