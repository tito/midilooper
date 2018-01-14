/**
MIDI const: https://github.com/khamaileon/python-rtmidi/blob/master/rtmidi/midiconstants.py
**/

package main
import (
    "log"
    "github.com/rakyll/portmidi"
)

const NOTE_ON = 0x90
const NOTE_OFF = 0x80
const POLY_PRESSURE = 0xA0
const CONTROL_CHANGE = 0xB0
const PROGRAM_CHANGE = 0xC0
const CHANNEL_PRESSURE = 0xD0
const PITCH_BEND = 0xE0

type Track struct {
    Notes []portmidi.Event
}

func NewTrack() (*Track) {
    track := new(Track)
    return track
}

func (track *Track) AddNote(ts int, channel int, note int64, velocity int64) {
    log.Println("Track add note", ts, note, velocity)
    status := int64(NOTE_ON | channel)
    ev := portmidi.Event{Status:status, Data1:note, Data2:velocity}
    track.Notes = append(track.Notes, ev)
    log.Println("Notes are", track.Notes)
}

func GetStatus(event portmidi.Event) (int64) {
    return event.Status & 0xf0
}

func GetChannel(event portmidi.Event) (int64) {
    return event.Status & 0x0f
}
