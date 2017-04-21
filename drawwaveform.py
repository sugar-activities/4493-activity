#! /usr/bin/python
#
#    Author:  Arjun Sarwal   arjun@laptop.org
#    Copyright (C) 2007, Arjun Sarwal
#    Copyright (C) 2009,10 Walter Bender
#    Copyright (C) 2009, Benjamin Berg, Sebastian Berg
#
#    This program is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program; if not, write to the Free Software
#    Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.

import gtk
from math import floor, ceil
from numpy import array, where, float64, multiply, fft, arange, blackman
from ringbuffer import RingBuffer1d
from gtk import gdk

from config import MAX_GRAPHS

# Initialize logging.
import logging
log = logging.getLogger('Measure')
log.setLevel(logging.DEBUG)
logging.basicConfig()


class DrawWaveform(gtk.DrawingArea):
    """ Handles all the drawing of waveforms """

    __gtype_name__ = "MeasureDrawWaveform"

    TRIGGER_NONE = 0
    TRIGGER_POS = 1
    TRIGGER_NEG = 2

    def __init__(self, msr, playsound, input_frequency=48000):
        """ Initialize drawing area and scope parameter """
        gtk.DrawingArea.__init__(self)

        self.add_events(gtk.gdk.BUTTON_PRESS_MASK | \
                        gtk.gdk.PROPERTY_CHANGE_MASK)

        self.activity = msr
        self.soundplayer = playsound
        self.vrg = 0
        self.topCount = 0
        self.inTop = -6
        self.playingTop = 0
        self.bottomCount = 0
        self.inBottom = -6
        self.playingBottom = 0

        self._input_freq = input_frequency
        self.triggering = self.TRIGGER_NONE
        self.trigger_xpos = 0.0
        self.trigger_ypos = 0.5

        self.active = False
        self._redraw_atom = gtk.gdk.atom_intern('MeasureRedraw')

        self.buffers = array([])
        self.main_buffers = array([])
        self.str_buffer = ''
        self.peaks = []
        self.fftx = []

        self._tick_size = 50

        self.rms = ''
        self.avg = ''
        self.pp = ''
        self.count = 0
        self.invert = False
        self.startbuffer = True

        self.y_mag = 3.0  # additional scale factor for display
        self.gain = 1.0
        self.bias = 0  # vertical position fine-tuning from slider
        self._freq_range = 4
        self.draw_interval = 10
        self.num_of_points = 115
        self.details_iter = 50
        self.c = 1180
        self.m = 0.0238
        self.k = 0.0238
        self.c2 = 139240  # c squared
        self.rms = 0
        self.avg = 0
        self.Rv = 0
        # constant to multiply with self.param2 while scaling values
        self.log_param1 = ""
        self.log_param2 = ""
        self.log_param3 = ""
        self.log_param4 = ""
        self.log_param5 = ""

        self._BACKGROUND_LINE_THICKNESS = 0.8
        self._TRIGGER_LINE_THICKNESS = 3
        self._FOREGROUND_LINE_THICKNESS = 6

        self.stop = False
        self.fft_show = False
        self.side_toolbar_copy = None

        self.scaleX = str(1.04167 / self.draw_interval) + ' ms'
        self.scaleY = ""

        self._back_surf = None
        self.expose_event_id = self.connect('expose_event', self._expose)

        self.pr_time = 0
        self.MAX_GRAPHS = MAX_GRAPHS     # Maximum simultaneous graphs

        self.graph_show_state = []
        self.Xstart = []
        self.Ystart = []
        self.Xend = []
        self.Yend = []
        self.type = []
        self.color = []
        self.source = []
        self.graph_id = []

        for x in range(0, self.MAX_GRAPHS):
            self.graph_show_state.append(False)
            self.Xstart.append(0)
            self.Ystart.append(50)
            self.Xend.append(1000)
            self.Yend.append(500)
            self.type .append(0)
            self.color.append('#FF0000')
            self.source.append(0)
            self.graph_id.append(x)

        self.graph_show_state[0] = True
        self.Xstart[0] = 0
        self.Ystart[0] = 0
        self.Xend[0] = 1150
        self.Yend[0] = 750
        self.type[0] = 0
        self.color[0] = self.activity.stroke_color
        self.source[0] = 0

        """
        self.graph_show_state[1]=True
        self.Xstart[0] = 0
        self.Ystart[1] = 0
        self.Xend[0] = 800
        self.Yend[1] = 600
        self.type[1]  = 0
        self.color[1]  = [0,65535,65535]
        self.source[1] = 0

        self.graph_show_state[2]=True
        self.Xstart[2] = 30
        self.Ystart[2] = 0
        self.Xend[2] = 300
        self.Yend[2] = 300
        self.type[2]  = 0
        self.color[2]  = [0,65535,0]
        self.source[2] = 0

        self.graph_show_state[3]=True
        self.Xstart[3] = 0
        self.Ystart[3] = 300
        self.Xend[3] = 1000
        self.Yend[3] = 700
        self.type[3]  = 0
        self.color[3]  = [65535,65535,0]
        self.source[3] = 0
        """

        self.max_samples = 115
        self.max_samples_fact = 3

        self.time_div = 1.0
        self.freq_div = 1.0
        self.input_step = 1

        self.ringbuffer = RingBuffer1d(self.max_samples, dtype='int16')

        self.debug_str = 'start'

        self.context = True

    def set_max_samples(self, num):
        """ Maximum no. of samples in ringbuffer """
        if self.max_samples == num:
            return
        new_buffer = RingBuffer1d(num, dtype='int16')

        new_buffer.append(self.ringbuffer.read())
        self.ringbuffer = new_buffer
        self.max_samples = num
        return

    def new_buffer(self, buf):
        """ Append a new buffer to the ringbuffer """
        if(self.startbuffer):
            self.ringbuffer.append(buf)
            self.startbuffer = False
        else:
            self.ringbuffer.append([ buf[0] / -2.4 + 100])
            round = 0
            while round < 10:
                b = buf[round]
                if(b < -32000):
                    # closed circuit, little or no resistance
                    if(self.inTop < 0):
                        self.inTop = self.inTop + 1
                    elif(self.inTop == 0):
                        self.inTop = 3
                        self.topCount = self.topCount + 1
                        if(self.activity.closedSound is not None):
                            self.playingBottom = 0
                            self.activity.playsound.setLocation("file://"+self.activity.closedSound.file_path)
                            self.activity.playsound.play()
                            self.playingTop = 1
                else:
                    if(self.inTop > 0):
                        self.inTop = self.inTop - 1
                    elif(self.inTop == 0):
                        self.inTop = -3
                        if(self.playingTop == 1):
                            self.soundplayer.stop()
                            self.playingTop = 0
                if(b > 32000):
                    # open circuit, theoretically infinite resistance
                    if(self.inBottom < 0):
                        self.inBottom = self.inBottom + 1
                    elif(self.inBottom == 0):
                        self.inBottom = 3
                        self.bottomCount = self.bottomCount + 1
                        if(self.activity.openedSound is not None):
                            self.playingTop = 0
                            self.activity.playsound.setLocation("file://"+self.activity.openedSound.file_path)
                            self.activity.playsound.play()
                            self.playingBottom = 1
                else:
                    if(self.inBottom > 0):
                        self.inBottom = self.inBottom - 1
                    elif(self.inBottom == 0):
                        self.inBottom = -3
                        if(self.playingBottom == 1):
                            self.soundplayer.stop()
                            self.playingBottom = 0
                round = round + 1
            
        return True

    def set_context_on(self):
        """ Return to an active state (context on) """
        if not self.context:
            self.handler_unblock(self.expose_event_id)
        self.context = True
        self._indirect_queue_draw()
        return

    def set_context_off(self):
        """ Return to an inactive state (context off) """
        if self.context:
            self.handler_block(self.expose_event_id)
        self.context = False
        self._indirect_queue_draw()
        return

    def set_invert_state(self, invert_state):
        """ In sensor mode, we can invert the plot """
        self.invert = invert_state
        return

    def get_invert_state(self):
        """ Return the current state of the invert flag """
        return self.invert

    def get_drawing_interval(self):
        """Returns the pixel interval horizontally between plots of two
        consecutive points"""
        return self.draw_interval

    def do_size_allocate(self, allocation):
        """ Allocate a drawing area for the plot """
        gtk.DrawingArea.do_size_allocate(self, allocation)
        self._update_mode()
        if self.window is not None:
            self._create_background_pixmap()
        return

    def _indirect_queue_draw(self):
        if self.window is None:
            return
        self.window.property_change(self._redraw_atom, self._redraw_atom,
            32, gtk.gdk.PROP_MODE_REPLACE, [])
        return

    def do_property_notify_event(self, event):
        if event.atom == self._redraw_atom:
            self.queue_draw()
        return

    def do_realize(self):
        """ Called when we are creating all of our window resources """

        gtk.DrawingArea.do_realize(self)

        # Force a native X window to exist
        xid = self.window.xid

        colormap = self.get_colormap()

        self._line_gc = []
        for graph_id in self.graph_id:
            if len(self.color) > graph_id:
                clr = colormap.alloc_color(self.color[graph_id])

                self._line_gc.append(self.window.new_gc(foreground=clr))
                self._line_gc[graph_id].set_line_attributes(
                    self._FOREGROUND_LINE_THICKNESS, gdk.LINE_SOLID,
                    gdk.CAP_ROUND, gdk.JOIN_BEVEL)

                self._line_gc[graph_id].set_foreground(clr)

        # Sugar stroke color
        clr = colormap.alloc_color(self.color[0])

        self._trigger_line_gc = self.window.new_gc(foreground=clr)
        self._trigger_line_gc.set_line_attributes(
            self._TRIGGER_LINE_THICKNESS, gdk.LINE_SOLID,
            gdk.CAP_ROUND, gdk.JOIN_BEVEL)

        self._trigger_line_gc.set_foreground(clr)

        self._create_background_pixmap()
        return

    def _create_background_pixmap(self):
        """ Draw the gridlines for the plot """

        back_surf = gdk.Pixmap(self.window, self._tick_size, self._tick_size)
        cr = back_surf.cairo_create()
        cr.set_source_rgb(0, 0, 0)
        cr.paint()

        cr.set_line_width(self._BACKGROUND_LINE_THICKNESS)
        cr.set_source_rgb(0.2, 0.2, 0.2)

        x = 0
        y = 0

        for j in range(0, 2):
            cr.move_to(x, y)
            cr.rel_line_to(0, self._tick_size)
            x = x + self._tick_size

        x = 0
        y = (self.allocation.height % self._tick_size) / 2 - self._tick_size

        for j in range(0, 3):
            cr.move_to(x, y)
            cr.rel_line_to(self._tick_size, 0)
            y = y + self._tick_size

        cr.set_line_width(self._BACKGROUND_LINE_THICKNESS)
        cr.stroke()

        del cr
        self.window.set_back_pixmap(back_surf, False)
        return

    def do_button_press_event(self, event):
        """ Set the trigger postion on a button-press event """
        self.trigger_xpos = event.x / float(self.allocation.width)
        self.trigger_ypos = event.y / float(self.allocation.height)
        return True

    def _expose(self, widget, event):
        """The 'expose' event handler does all the drawing"""

        # Real time drawing
        if self.context and self.active:

            #Iterate for each graph
            for graph_id in self.graph_id:
                if self.graph_show_state[graph_id]:
                    buf = self.ringbuffer.read(None, self.input_step)
                    samples = ceil(self.allocation.width / self.draw_interval)
                    if len(buf) == 0:
                        # We don't have enough data to plot.
                        self._indirect_queue_draw()
                        return

                    x_offset = 0

                    if not self.fft_show:
                        if self.triggering != self.TRIGGER_NONE:
                            xpos = self.trigger_xpos
                            ypos = self.trigger_ypos
                            samples_to_end = int(samples * (1 - xpos))

                            ypos -= 0.5
                            ypos *= -32767.0 / self.y_mag

                            x_offset = self.allocation.width\
                                * xpos - (samples - samples_to_end)\
                                * self.draw_interval

                            position = -1
                            if self.triggering and self.TRIGGER_POS:
                                ints = buf[samples - samples_to_end:\
                                               - samples_to_end - 3] <= ypos
                                ints &= buf[samples - samples_to_end + 1:\
                                                - samples_to_end - 2] > ypos

                                ints = where(ints)[0]
                                if len(ints) > 0:
                                    position = max(position, ints[-1])

                            if self.triggering and self.TRIGGER_NEG:
                                ints = buf[samples - samples_to_end:\
                                           -samples_to_end - 3] >= ypos
                                ints &= buf[samples - samples_to_end + 1:\
                                            -samples_to_end - 2] < ypos

                                ints = where(ints)[0]
                                if len(ints) > 0:
                                    position = max(position, ints[-1])

                            if position == -1:
                                position = len(buf) - samples_to_end - 2
                            else:
                                position = position + samples - samples_to_end
                                try:
                                    x_offset -=\
                                        int((float(-buf[position] + ypos)\
                                        / (buf[position + 1] - buf[position]))\
                                        * self.draw_interval + 0.5)
                                except:
                                    pass

                            data = buf[position - samples + samples_to_end:\
                                position + samples_to_end + 2].astype(float64)
                        else:
                            data = buf[-samples:].astype(float64)

                    else:
                        # FFT
                        try:
                            # Multiply input with the window
                            multiply(buf, self.fft_window, buf)

                            # Should be fast enough even without pow(2) stuff.
                            self.fftx = fft.rfft(buf)
                            self.fftx = abs(self.fftx)
                            data = multiply(self.fftx, 0.02, self.fftx)
                        except ValueError:
                            # TODO: Figure out how this can happen.
                            #       Shape mismatch between window and buf
                            self._indirect_queue_draw()
                            return True

                    # Scaling the values
                    if self.activity.CONTEXT == 'sensor':
                        self.y_mag = 1.0

                    if self.invert:
                        data *= (self.allocation.height / 32767.0 * self.y_mag)
                    else:
                        data *= (-self.allocation.height / 32767.0 * self.y_mag)
                    data -= self.bias

                    if self.fft_show:
                        data += self.allocation.height - 3
                    else:
                        data += (self.allocation.height / 2.0)

                    # The actual drawing of the graph
                    lines = (arange(len(data), dtype='float32')\
                            * self.draw_interval) + x_offset

                    # Use ints or draw_lines will throw warnings
                    lines = zip(lines.astype('int'), data.astype('int'))

                    if not self.fft_show:
                        if self.triggering != self.TRIGGER_NONE:
                            x = int(self.trigger_xpos * self.allocation.width)
                            y = int(self.trigger_ypos * self.allocation.height)
                            length = int(self._TRIGGER_LINE_THICKNESS * 3.5)
                            self.window.draw_line(self._trigger_line_gc,
                                                  x - length, y,
                                                  x + length, y)
                            self.window.draw_line(self._trigger_line_gc,
                                                  x, y - length,
                                                  x, y - length)

                    if self.type[graph_id] == 0:
                        self.window.draw_lines(self._line_gc[graph_id], lines)
                    else:
                        self.window.draw_points(self._line_gc[graph_id], lines)

            self._indirect_queue_draw()
        return True

    def set_graph_source(self, graph_id, source=0):
        """Sets from where the graph will get data
        0 - uses from audiograb
        1 - uses from file"""
        self.source[graph_id] = source

    def set_div(self, time_div=0.0001, freq_div=10):
        """ Set division """
        self.time_div = time_div
        self.freq_div = freq_div

        self._update_mode()

    def get_trigger(self):
        return self.triggering

    def set_trigger(self, trigger):
        self.triggering = trigger

    def get_ticks(self):
        return self.allocation.width / float(self._tick_size)

    def get_fft_mode(self):
        """Returns if FFT is ON (True) or OFF (False)"""
        return self.fft_show

    def set_fft_mode(self, fft_mode=False):
        """Sets whether FFT mode is ON (True) or OFF (False)"""
        self.fft_show = fft_mode
        self._update_mode()

    def set_freq_range(self, freq_range=4):
        """See sound_toolbar to see what all frequency ranges are"""
        self._freq_range = freq_range

    def _update_mode(self):
        if self.allocation.width <= 0:
            return

        if self.fft_show:
            max_freq = (self.freq_div * self.get_ticks())
            wanted_step = 1.0 / max_freq / 2 * self._input_freq
            self.input_step = max(floor(wanted_step), 1)

            self.draw_interval = 5.0

            self.set_max_samples(ceil(self.allocation.width\
                             / float(self.draw_interval) * 2) * self.input_step)

            # Create the (blackman) window
            self.fft_window = blackman(ceil(self.allocation.width\
                                               / float(self.draw_interval) * 2))

            self.draw_interval *= wanted_step / self.input_step
        else:
            # Factor is just for triggering:
            time = (self.time_div * self.get_ticks())
            if time == 0:
                return
            samples = time * self._input_freq
            self.set_max_samples(samples * self.max_samples_fact)

            self.input_step = max(ceil(samples\
                                           / (self.allocation.width / 3.0)), 1)
            self.draw_interval = self.allocation.width\
                                           / (float(samples) / self.input_step)

            self.fft_window = None

    def set_active(self, active):
        self.active = active
        self._indirect_queue_draw()

    def get_active(self):
        return self.active

    def get_mag_params(self):
        return self.gain, self.y_mag

    def set_mag_params(self, gain=1.0, y_mag=3.0):
        self.gain = gain
        self.y_mag = y_mag

    def get_bias_param(self):
        return self.bias

    def set_bias_param(self, bias=0):
        self.bias = bias
