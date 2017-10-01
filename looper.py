#!/usr/bin/env python
"""
Midi Looper
===========

UI:
    Display made for https://learn.adafruit.com/adafruit-pioled-128x32-mini-oled-for-raspberry-pi/
    Font are:
        https://fonts2u.com/fairfax.font
        https://fonts2u.com/fairfax-bold.font
"""

import io
import os
import json
import rtmidi
import threading
import traceback
from time import time
from pynput.keyboard import Listener, Key, KeyCode
from rtmidi.midiconstants import (ALL_SOUND_OFF, CONTROL_CHANGE,
                                  RESET_ALL_CONTROLLERS, NOTE_ON,
                                  NOTE_OFF, SONG_START,
                                  SONG_CONTINUE, SONG_STOP)
from PIL import Image, ImageDraw, ImageFont

try:
    import tkinter as tk
    from PIL import ImageTk
except:

    tk = None

global looper
Char = KeyCode.from_char
SIZE = (128, 32)
DPI = 5
size = [x * DPI for x in SIZE]
image = None
LAG = 10 / 1000.


class Track(object):
    def __init__(self, index, midiout, looper):
        self.index = index
        self.notes = []
        self.notes_next = []
        self.recording = False
        self.muted = False
        self.on = []
        self.midiout = midiout
        self.looper = looper

    def quantize(self, clock, m):
        clock -= LAG
        diff = (clock % m)
        clock -= diff
        if diff > m / 2:
            clock += m
        return clock

    def midiin_callback(self, clock, m, data):
        # print("track {}: {} {}".format(self.index, clock, m, data))
        if not self.recording:
            return
        status = m[0] & 0xF0
        if status in (NOTE_ON, NOTE_OFF):
            if looper.quantize > 0:
                clock = self.quantize(clock, 60 / looper.bpm / looper.quantize)
            self.notes_next.append((clock, m, data))

    def reset(self):
        self.notes = []
        self.notes_next = []

    def start_recording(self):
        self.recording = True
        self.off()

    def stop_recording(self):
        self.recording = False
        self.merge()

    def toggle_mute(self):
        self.muted = not self.muted
        if self.muted:
            self.off()

    def get_notes_between(self, start, end):
        if self.muted:
            return
        if start == 0:
            start = -1
        for clock, message, data in self.notes:
            if clock >= start and clock <= end:
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

    def merge(self):
        self.notes += self.notes_next
        self.notes_next = []


class Player(threading.Thread):
    def __init__(self, looper, midiout):
        super(Player, self).__init__()
        self._is_playing = threading.Event()
        self._is_playing.clear()
        self.daemon = True
        self.quit = False
        self.looper = looper
        self.restart = False
        self.time_start = 0
        self.midiout = midiout
        self.start()

    @property
    def playing(self):
        return self._is_playing.is_set()

    def run(self):
        prev_deltatime = 0
        deltatime = 0
        play_notes = self.play_notes
        looper = self.looper
        tick = 0

        while not self.quit:

            if not self.playing:
                self._is_playing.wait()
                continue

            if self.restart:
                prev_deltatime = deltatime = 0
                self.restart = False

            length = looper.length
            prev_deltatime = deltatime
            now = (time() - self.time_start)
            deltatime = now % length

            interval = looper.beat_length
            if now - tick > interval:
                self.tick()
                tick = now

            if deltatime > prev_deltatime:
                play_notes(looper, prev_deltatime, deltatime)
            else:
                play_notes(looper, prev_deltatime, length)
                self.merge_track_notes()
                play_notes(looper, 0, deltatime)

    def tick(self):
        if self.looper.with_tick:
            self.midiout.send_message([NOTE_ON, 42, 50])
        # self.midiout.send_message([NOTE_ON, 42, 0])

    def play_notes(self, looper, start, stop):
        for track in list(looper.tracks.values()):
            track.send_notes_between(start, stop)

    def merge_track_notes(self):
        for track in list(looper.tracks.values()):
            track.merge()

    def toggle_play(self):
        if self.playing:
            return self.stop()
        self.play()

    def play(self):
        if self.playing:
            return
        self.time_start = time()
        self.restart = True
        self._is_playing.set()
        self.midiout.send_message([SONG_START])
        self.tick()

    def stop(self):
        if not self.playing:
            return
        self._is_playing.clear()
        self.midiout.send_message([SONG_STOP])
        self.notes_off()

    def panic(self):
        send = self.looper.midiout.send_message
        self.stop()
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

        Char("a"): "stop_record",

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

        Char("1"): ("toggle_channel", [1]),
        Char("2"): ("toggle_channel", [2]),
        Char("3"): ("toggle_channel", [3]),
        Char("4"): ("toggle_channel", [4]),
        KeyCode(65437): ("toggle_channel", [5]),
        Char("6"): ("toggle_channel", [6]),
        Char("7"): ("toggle_channel", [7]),
        Char("8"): ("toggle_channel", [8]),

        Char("+"): ("increment_measure", [1]),
        Char("-"): ("increment_measure", [-1]),
        Key.page_up: ("increment_tempo", [10]),
        Key.page_down: ("increment_tempo", [-10]),
        Key.home: ("increment_tempo", [1]),
        Key.end: ("increment_tempo", [-1]),
        Key.insert: "decrease_quantize",
        Key.delete: "increase_quantize",

        Key.f12: "save_settings",
        Key.f11: "load_settings",
        Key.f9: "toggle_tick",

        Key.space: "toggle_play",
        Key.esc: "panic",
        Key.caps_lock: "toggle_record_on_first_note",
        Char("/"): "midi_prev_port",
        Char("*"): "midi_next_port"
    }

    QUANTIZE = (1, 2, 3, 4, 8)

    def __init__(self):
        self.tracks = {}
        self.shift = False
        self.ctrl = False
        self._key_pressed = []
        self.active_track = None
        self.record_on_first_note = True
        self.bpm = 120
        self.beat_per_measures = 4
        self.measures = 4
        self.port = 0
        self.quantize = 16
        self.channels = [False] * 8
        self.with_tick = False
        self.midiin = rtmidi.MidiIn()
        self.midiout = rtmidi.MidiOut()
        self.midiin_name = self.midiout_name = ""
        self.player = Player(self, self.midiout)
        self.recalculate_length()
        self.open_midi_port()
        self.load_settings()

    def increase_quantize(self):
        index = self.QUANTIZE.index(self.quantize)
        index = min(len(self.QUANTIZE) - 1, (index + 1))
        self.quantize = self.QUANTIZE[index]

    def decrease_quantize(self):
        index = self.QUANTIZE.index(self.quantize)
        index = max(0, (index - 1))
        self.quantize = self.QUANTIZE[index]

    def stop_record(self):
        for track in self.tracks.values():
            track.stop_recording()
        self.active_track = None

    def toggle_channel(self, index):
        index -= 1
        self.channels[index] = not self.channels[index]

    def toggle_tick(self):
        self.with_tick = not self.with_tick

    @property
    def settings(self):
        return {
            "__version__": 1,
            "bpm": self.bpm,
            "measures": self.measures,
            "beat_per_measures": self.beat_per_measures,
            "port": self.port,
            "record_on_first_note": self.record_on_first_note,
            "quantize": self.quantize,
            "tracks": self.dump_tracks(),
            "channels": self.channels
        }

    def dump_tracks(self):
        tracks = []
        for track in self.tracks.values():
            tracks.append({
                "index": track.index,
                "notes": track.notes,
                "muted": track.muted
            })
        return tracks

    def save_settings(self):
        with io.open("settings.json", "w", encoding="utf-8") as fd:
            json.dump(self.settings, fd)
        print("Settings saved")

    def load_settings(self):
        try:
            with open("settings.json") as fd:
                settings = json.load(fd)
            if settings["__version__"] <= 1:
                self.bpm = settings["bpm"]
                self.beat_per_measures = settings["beat_per_measures"]
                self.measures = settings["measures"]
                self.record_on_first_note = settings["record_on_first_note"]
                self.port = settings["port"]
                self.quantize = settings["quantize"]
                self.channels = settings["channels"]
                self.recalculate_length()
                self.open_midi_port()

                self.tracks = {}
                for info in settings["tracks"]:
                    track = self.get_track(info["index"])
                    track.notes = info["notes"]
                    track.muted = info["muted"]

            print("Settings loaded")
        except:
            print("Error while loading settings")
            traceback.print_exc()

    def increment_tempo(self, amount):
        self.bpm = min(240, max(60, (self.bpm + amount)))
        self.recalculate_length()

    def increment_measure(self, amount):
        self.measures = min(24, max(1, self.measures + amount))
        self.recalculate_length()

    def recalculate_length(self):
        self.beat_length = 60 / float(self.bpm)
        self.measure_length = self.beat_length * self.beat_per_measures
        self.length = self.measure_length * self.measures

    def open_midi_port(self):
        if self.midiin.is_port_open():
            self.midiin.close_port()
        if self.midiout.is_port_open():
            self.midiout.close_port()
        self.midiin.open_port(self.port)
        self.midiout.open_port(self.port)
        self.midiin.set_callback(self.midiin_callback)
        self.midiin_name = self.midiin.get_port_name(self.port)
        self.midiout_name = self.midiout.get_port_name(self.port)
        self.player.midiout = self.midiout
        for track in self.tracks.values():
            track.midiout = self.midiout
        print("Connected: in={} out={}".format(self.midiin_name, self.midiout_name))

    def midi_next_port(self):
        self.port = (self.port + 1) % len(self.midiin.get_ports())
        self.open_midi_port()

    def midi_prev_port(self):
        self.port = (self.port - 1) % len(self.midiin.get_ports())
        self.open_midi_port()

    @property
    def measure(self):
        if not self.player.playing:
            return 1
        return 1 + int(self.player.deltatime / self.measure_length) % self.measures

    @property
    def beat(self):
        if not self.player.playing:
            return 0
        return 1 + int((self.player.deltatime / self.beat_length) % self.beat_per_measures)

    def reset(self):
        self.stop()
        self.tracks = {}
        if self.active_track:
            self.active_track.stop_recording()
            self.active_track = None

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
        if self.ctrl:
            self.get_track(index).reset()
            return

        active_index = -1
        if self.active_track:
            active_index = self.active_track.index
            self.active_track.stop_recording()
            self.active_track = None
            if active_index == index:
                return
        self.active_track = track = self.get_track(index)
        if track.recording:
            track.stop_recording()
        else:
            if not self.record_on_first_note:
                self.play()
            track.start_recording()

    def mute(self, index):
        self.get_track(index).toggle_mute()

    def _record_after(self, index):
        self.get_track(index).stop_recording()

    def midiin_callback(self, blob, data):
        print("MIDI IN: {}".format(blob))
        message, deltatime = blob

        # control part
        if message[0] == SONG_START:
            return self.play()
        elif message[0] == SONG_STOP:
            return self.stop()

        is_note = (message[0] & 0xF0 == NOTE_ON)
        if not is_note:
            return

        channel = message[0] & 0x0F
        if not self.channels[channel]:
            return
        if not self.active_track:
            return

        if self.record_on_first_note:
            if not self.player.playing:
                self.player.play()
        deltatime = self.player.deltatime % self.length
        self.active_track.midiin_callback(deltatime, message, data)

    def get_track(self, index):
        if index not in self.tracks:
            self.tracks[index] = Track(index, self.midiout, self)
        return self.tracks[index]

    def dispatch_command(self, key, after=False):
        cmd, func, args = self.get_command(key, after)
        if not cmd:
            return
        print("Execute: {} {}".format(cmd, args))
        func(*args)

    def get_command(self, key, after=False):
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
        print("key", key)
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


class UI(threading.Thread):
    def __init__(self):
        super(UI, self).__init__()
        width, height = size
        self.image = Image.new('1', (width, height))
        self.draw = ImageDraw.Draw(self.image)
        self.font = ImageFont.truetype("fonts/Fairfax.ttf", size=10 * DPI)
        self.daemon = True
        self.cache = None
        self.start()

    def run(self):
        if tk:
            self.root = tk.Tk()
            self.root.title("Midi Looper")
            self.root.geometry("{}x{}+0+0".format(*size))
            self.image1 = ImageTk.PhotoImage(self.image)
            self.panel = tk.Label(self.root, image=self.image1)
            self.panel.pack()
            self.root.after(1, self.render_and_display)
            self.root.mainloop()
            os._exit(0)

    def render_and_display(self):
        if self.render():
            self.display()
        if tk:
            self.root.after(1, self.render_and_display)

    def render(self):
        # ▶■◼⚪⚫ (~25 chars width)
        width, height = size
        d = self.draw
        font = self.font
        player = looper.player

        def text(x, y, message):
            mx = 2
            d.text(((mx + x) * DPI, y * DPI), message, font=font, fill=255)

        state = u"‣" if player.playing else u"■"
        quantize = str(looper.quantize)
        channels = "".join([("+" if x else "-") for x in looper.channels])
        with_tick = "T" if looper.with_tick else " "
        top = "{state} {bpm} {measure}-{measures} {quantize}{tick}{beat}{beatleft} {channels}".format(
            state=state,
            bpm=looper.bpm,
            measure=looper.measure,
            measures=looper.measures,
            beat="⚫" * looper.beat,
            beatleft="⚪" * (looper.beat_per_measures - looper.beat),
            port=looper.midiin_name,
            channels=channels,
            quantize=quantize,
            tick=with_tick
        )

        def render_status(index):
            status = ""
            if index in looper.tracks:
                track = looper.get_track(index)
                status += "⚫" if track.notes else "⚪"
                status += "R" if track.recording else " "
                status += "M" if track.muted else " "
                status += str(len(track.notes) + len(track.notes_next))
            else:
                status = "⚪"
            return status.ljust(8)

        line1 = "".join([render_status(i) for i in (1, 4, 7)])
        line2 = "".join([render_status(i) for i in (2, 5, 8)])
        line3 = "".join([render_status(i) for i in (3, 6, 9)])

        cache = [top, line1, line2, line3]
        if self.cache == cache:
            return False
        self.cache = cache

        d.rectangle((0, 0, width, height), outline=0, fill=0)
        text(0, 0, top)
        text(0, 8, line1)
        text(0, 16, line2)
        text(0, 24, line3)
        return True

    def display(self):
        if tk:
            self.image1 = ImageTk.BitmapImage(self.image)
            self.panel.configure(image=self.image1)
            self.root.update()


def hide_keyboard():
    os.system("stty -echo")


def show_keyboard():
    os.system("stty echo")


try:
    hide_keyboard()

    looper = Looper()

    ui = UI()

    with Listener(
            on_press=looper.on_key_pressed,
            on_release=looper.on_key_released) as listener:
        listener.join()

finally:
    show_keyboard()
