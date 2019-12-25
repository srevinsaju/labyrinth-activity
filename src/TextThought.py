#! /usr/bin/env python
# Thoughts.py
# This file is part of Labyrinth
#
# Copyright (C) 2006 - Don Scorgie <Don@Scorgie.org>
#
# Labyrinth is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# Labyrinth is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.    See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Labyrinth; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor,
# Boston, MA  02110-1301  USA
#

# In order to support an on-screen keyboard, a textview widget is used
# instead of capturing individual keyboard events. The down side to
# this is that the maintenance of text attributes is mangled. The good
# news is that much of the complexity disappears.
# --Walter Bender <walter@sugarlabs.org> 2013

from gi.repository import Gtk, Gdk, Pango, PangoCairo

import os
import xml.dom

from . import utils
from . import BaseThought
from . import UndoManager
from .BaseThought import *
from . import prefs

UNDO_ADD_ATTR = 64
UNDO_ADD_ATTR_SELECTION = 65
UNDO_REMOVE_ATTR = 66
UNDO_REMOVE_ATTR_SELECTION = 67


class TextThought (ResizableThought):
    def __init__(self, coords, pango_context, thought_number, save, undo,
                 loading, background_color, foreground_color, name="thought",
                 fixed=None, parent=None):
        super(TextThought, self).__init__(coords, save,
                                          name, undo, background_color, foreground_color)

        self.index = 0
        self.end_index = 0
        self.bytes = ""
        self.bindex = 0
        self.text_element = save.createTextNode("GOOBAH")
        self.element.appendChild(self.text_element)
        self.layout = None
        self.identity = thought_number
        self.pango_context = pango_context
        self.moving = False
        self.preedit = None
        self.current_attrs = []
        self.double_click = False
        self.orig_text = None
        self._parent = parent
        self._fixed = fixed
        self.textview = None
        self._textview_handler = None
        self._clipboard = None

        self.attributes = {"bold": False,
                           "italic": False,
                           "underline": False,
                           "font": "Sans"}

        self.tag_bold = None
        self.tag_italic = None
        self.tag_underline = None

        if prefs.get_direction() == Gtk.TextDirection.LTR:
            self.pango_context.set_base_dir(Pango.Direction.LTR)
        else:
            self.pango_context.set_base_dir(Pango.Direction.RTL)

        self.b_f_i = self.bindex_from_index
        margin = utils.margin_required(utils.STYLE_NORMAL)

        if coords:
            self.ul = (coords[0]-margin[0], coords[1] - margin[1])

        else:
            self.ul = None

        self.all_okay = True

    def make_tags(self):
        buffer = self.textview.get_buffer()
        self.tag_bold = buffer.create_tag("bold", weight=Pango.Weight.BOLD)
        self.tag_italic = buffer.create_tag("italic", style=Pango.Style.ITALIC)
        self.tag_underline = buffer.create_tag(
            "underline", underline=Pango.Underline.SINGLE)
        self.tag_font = buffer.create_tag("font", font=self.attributes["font"])

    def index_from_bindex(self, bindex):
        if bindex == 0:
            return 0

        index = 0
        for x in range(bindex):
            index += int(self.bytes[x])

        return index

    def bindex_from_index(self, index):
        if index == 0:
            return 0

        bind = 0
        nbytes = 0

        for x in self.bytes:
            nbytes += int(x)
            bind += 1
            if nbytes == index:
                break

        if nbytes < index:
            bind = len(self.bytes)

        return bind

    def recalc_text_edges(self):
        if (not hasattr(self, "layout")):
            return

        self.layout = Pango.Layout(self.pango_context)

        if self.textview != None:
            start, end = self.textview.get_buffer().get_bounds()
            text = self.textview.get_buffer().get_text(start, end, True)
            self.layout.set_text(text, len(text))

        # self.layout.set_attributes(self.attrlist)

        margin = utils.margin_required(utils.STYLE_NORMAL)
        text_w, text_h = self.layout.get_pixel_size()
        text_w += margin[0] + margin[2]
        text_h += margin[1] + margin[3]

        self.width = max(self.width, text_w)
        self.height = max(self.height, text_h)

        self.min_x = self.ul[0] + (self.width - text_w)/2 + margin[0]
        self.min_y = self.ul[1] + (self.height - text_h)/2 + margin[1]
        self.max_x = self.min_x + text_w
        self.max_y = self.min_y + text_h

    def recalc_edges(self):
        self.lr = (self.ul[0] + self.width, self.ul[1] + self.height)
        if not self.creating:
            self.recalc_text_edges()

    def commit_text(self, context, string, mode, font_combo_box, font_sizes_combo_box):
        font_name = font_combo_box.get_active_text()
        font_size = utils.default_font_size  # font_sizes_combo_box.get_active_text()
        self.set_font(font_name, font_size)
        self.add_text(string)
        self.recalc_edges()
        self.emit("title_changed", self.text)
        self.emit("update_view")

    def add_text(self, string):
        if self.index > self.end_index:
            left = self.text[:self.end_index]
            right = self.text[self.index:]
            bleft = self.bytes[:self.b_f_i(self.end_index)]
            bright = self.bytes[self.b_f_i(self.index):]
            change = self.end_index - self.index + len(string)
            old = self.index
            self.index = self.end_index
            self.end_index = old
        elif self.index < self.end_index:
            left = self.text[:self.index]
            right = self.text[self.end_index:]
            bleft = self.bytes[:self.b_f_i(self.index)]
            bright = self.bytes[self.b_f_i(self.end_index):]
            change = self.index - self.end_index + len(string)
        else:
            left = self.text[:self.index]
            right = self.text[self.index:]
            bleft = self.bytes[:self.b_f_i(self.index)]
            bright = self.bytes[self.b_f_i(self.index):]
            change = len(string)

        self.text = left + string + right
        self.undo.add_undo(UndoManager.UndoAction(self, UndoManager.INSERT_LETTER, self.undo_text_action,
                                                  self.bindex, string, len(string), self.attributes, []))
        self.index += len(string)
        self.bytes = bleft + str(len(string)) + bright
        self.bindex = self.b_f_i(self.index)
        self.end_index = self.index

    def draw(self, context):
        self.recalc_edges()
        ResizableThought.draw(self, context)
        if self.creating:
            return

        (textx, texty) = (self.min_x, self.min_y)
        if self.am_primary:
            r, g, b = utils.primary_colors["text"]
        elif (self.foreground_color):
            r, g, b = utils.gtk_to_cairo_color(self.foreground_color)
        else:
            r, g, b = utils.gtk_to_cairo_color(utils.default_colors["text"])
        context.set_source_rgb(r, g, b)
        self.layout.set_alignment(Pango.Alignment.CENTER)
        context.move_to(textx, texty)
        ##context.show_layout (self.layout)
        if self.editing:
            if self.preedit:
                (strong, weak) = self.layout.get_cursor_pos(
                    self.index + self.preedit[2])

            else:
                (strong, weak) = self.layout.get_cursor_pos(self.index)

            if type(strong) == tuple:
                (startx, starty, curx, cury) = strong

            elif type(strong) == Pango.Rectangle:
                startx = strong.x
                starty = strong.y
                curx = strong.width
                cury = strong.height

            startx /= Pango.SCALE
            starty /= Pango.SCALE
            curx /= Pango.SCALE
            cury /= Pango.SCALE
            context.move_to(textx + startx, texty + starty)
            context.line_to(textx + startx, texty + starty + cury)
            context.stroke()

        context.set_source_rgb(0, 0, 0)
        context.stroke()

    def process_key_press(self, event, mode):
        # Since we are using textviews, we don't use the
        # keypress code anymore
        if not self.editing:
            return False
        else:
            return True

        modifiers = Gtk.accelerator_get_default_mod_mask()
        shift = event.state & modifiers == Gdk.ModifierType.SHIFT_MASK
        handled = True
        clear_attrs = True
        if not self.editing:
            return False

        if (event.state & modifiers) & Gdk.ModifierType.CONTROL_MASK:
            if event.keyval == gtk.keysyms.a:
                self.index = self.bindex = 0
                self.end_index = len(self.text)
        elif event.keyval == gtk.keysyms.Escape:
            self.leave()
        elif event.keyval == gtk.keysyms.Left:
            if prefs.get_direction() == Gtk.TextDirection.LTR:
                self.move_index_back(shift)
            else:
                self.move_index_forward(shift)
        elif event.keyval == gtk.keysyms.Right:
            if prefs.get_direction() == Gtk.TextDirection.RTL:
                self.move_index_back(shift)
            else:
                self.move_index_forward(shift)
        elif event.keyval == gtk.keysyms.Up:
            self.move_index_up(shift)
        elif event.keyval == gtk.keysyms.Down:
            self.move_index_down(shift)
        elif event.keyval == gtk.keysyms.Home:
            if prefs.get_direction() == Gtk.TextDirection.LTR:
                self.move_index_horizontal(shift, True)    # move home
            else:
                self.move_index_horizontal(shift)            # move end
            self.move_index_horizontal(shift, True)        # move home
        elif event.keyval == gtk.keysyms.End:
            self.move_index_horizontal(shift)            # move
        elif event.keyval == gtk.keysyms.BackSpace and self.editing:
            self.backspace_char()
        elif event.keyval == gtk.keysyms.Delete and self.editing:
            self.delete_char()
        elif len(event.string) != 0:
            self.add_text(event.string)
            clear_attrs = False
        else:
            handled = False

        if clear_attrs:
            del self.current_attrs
            self.current_attrs = []

        self.recalc_edges()
        self.selection_changed()
        self.emit("title_changed", self.text)
        self.bindex = self.bindex_from_index(self.index)
        self.emit("update_view")

        return handled

    def undo_text_action(self, action, mode):
        self.undo.block()
        if action.undo_type == UndoManager.DELETE_LETTER or action.undo_type == UndoManager.DELETE_WORD:
            real_mode = not mode
            attrslist = [action.args[5], action.args[4]]

        else:
            real_mode = mode
            attrslist = [action.args[3], action.args[4]]

        self.bindex = action.args[0]
        self.index = self.index_from_bindex(self.bindex)
        self.end_index = self.index
        if real_mode == UndoManager.UNDO:
            attrs = attrslist[0]
            self.end_index = self.index + action.args[2]
            self.delete_char()
        else:
            attrs = attrslist[1]
            self.add_text(action.text)
            self.rebuild_byte_table()
            self.bindex = self.b_f_i(self.index)

        self.recalc_edges()
        self.emit("title_changed", self.text)
        self.emit("update_view")
        self.emit("grab_focus", False)
        self.undo.unblock()

    def delete_char(self):
        if self.index == self.end_index == len(self.text):
            return
        if self.index > self.end_index:
            self.index, self.end_index = self.end_index, self.index
        if self.index != self.end_index:
            left = self.text[:self.index]
            right = self.text[self.end_index:]
            local_text = self.text[self.index:self.end_index]
            bleft = self.bytes[:self.b_f_i(self.index)]
            bright = self.bytes[self.b_f_i(self.end_index):]
            local_bytes = self.bytes[self.b_f_i(
                self.index):self.b_f_i(self.end_index)]
            change = -len(local_text)
        else:
            left = self.text[:self.index]
            right = self.text[self.index+int(self.bytes[self.bindex]):]
            local_text = self.text[self.index:self.index +
                                   int(self.bytes[self.bindex])]
            bleft = self.bytes[:self.b_f_i(self.index)]
            bright = self.bytes[self.b_f_i(self.index)+1:]
            local_bytes = self.bytes[self.b_f_i(self.index)]
            change = -len(local_text)

        changes = []
        old_attrs = self.attributes.copy()
        accounted = -change

        self.undo.add_undo(UndoManager.UndoAction(self, UndoManager.DELETE_LETTER, self.undo_text_action,
                                                  self.b_f_i(self.index), local_text, len(
                                                      local_text), local_bytes, old_attrs,
                                                  changes))
        self.text = left+right
        self.bytes = bleft+bright
        self.end_index = self.index

    def backspace_char(self):
        if self.index == self.end_index == 0:
            return

        if self.index > self.end_index:
            self.index, self.end_index = self.end_index, self.index

        if self.index != self.end_index:
            left = self.text[:self.index]
            right = self.text[self.end_index:]
            bleft = self.bytes[:self.b_f_i(self.index)]
            bright = self.bytes[self.b_f_i(self.end_index):]
            local_text = self.text[self.index:self.end_index]
            local_bytes = self.bytes[self.b_f_i(
                self.index):self.b_f_i(self.end_index)]
            change = -len(local_text)

        else:
            left = self.text[:self.index-int(self.bytes[self.bindex-1])]
            right = self.text[self.index:]
            bleft = self.bytes[:self.b_f_i(self.index)-1]
            bright = self.bytes[self.b_f_i(self.index):]
            local_text = self.text[self.index -
                                   int(self.bytes[self.bindex-1]):self.index]
            local_bytes = self.bytes[self.b_f_i(self.index)-1]
            self.index -= int(self.bytes[self.bindex-1])
            change = -len(local_text)

        old_attrs = self.attributes.copy()
        changes = []
        accounted = -change

        self.text = left+right
        self.bytes = bleft+bright
        self.end_index = self.index

        self.undo.add_undo(UndoManager.UndoAction(self, UndoManager.DELETE_LETTER, self.undo_text_action,
                                                  self.b_f_i(self.index), local_text, len(
                                                      local_text), local_bytes, old_attrs,
                                                  changes))

        if self.index < 0:
            self.index = 0

    def move_index_back(self, mod):
        if self.index <= 0:
            self.index = 0
            return

        self.index -= int(self.bytes[self.bindex-1])

        if not mod:
            self.end_index = self.index

    def move_index_forward(self, mod):
        if self.index >= len(self.text):
            self.index = len(self.text)
            return
        self.index += int(self.bytes[self.bindex])
        if not mod:
            self.end_index = self.index

    def move_index_up(self, mod):
        tmp = self.text.decode()
        lines = tmp.splitlines()
        if len(lines) == 1:
            return
        loc = 0
        line = 0
        for i in lines:
            loc += len(i)+1
            if loc > self.index:
                loc -= len(i)+1
                line -= 1
                break
            line += 1
        if line == -1:
            return
        elif line >= len(lines):
            self.bindex -= len(lines[-1])+1
            self.index = self.index_from_bindex(self.bindex)
            if not mod:
                self.end_index = self.index
            return
        dist = self.bindex - loc - 1
        self.bindex = loc
        if dist < len(lines[line]):
            self.bindex -= (len(lines[line]) - dist)
        else:
            self.bindex -= 1
        if self.bindex < 0:
            self.bindex = 0
        self.index = self.index_from_bindex(self.bindex)
        if not mod:
            self.end_index = self.index

    def move_index_down(self, mod):
        tmp = self.text.decode()
        lines = tmp.splitlines()
        if len(lines) == 1:
            return
        loc = 0
        line = 0
        for i in lines:
            loc += len(i)+1
            if loc > self.bindex:
                break
            line += 1
        if line >= len(lines)-1:
            return
        dist = self.bindex - (loc - len(lines[line]))+1
        self.bindex = loc
        if dist > len(lines[line+1]):
            self.bindex += len(lines[line+1])
        else:
            self.bindex += dist
        self.index = self.index_from_bindex(self.bindex)
        if not mod:
            self.end_index = self.index

    def move_index_horizontal(self, mod, home=False):
        lines = self.text.splitlines()
        loc = 0
        line = 0
        for i in lines:
            loc += len(i) + 1
            if loc > self.index:
                self.index = loc - 1
                if home:
                    self.index -= len(i)
                if not mod:
                    self.end_index = self.index
                return
            line += 1

    def process_button_down(self, event, coords):
        if not self._parent.move_mode and self.textview is None:
            self._create_textview()
            self.make_tags()

        if self.textview is not None:
            self.textview.grab_focus()

        if ResizableThought.process_button_down(self, event, coords):
            return True

        # With textview, we are always editing
        # if not self.editing:
        #     return False

        modifiers = Gtk.accelerator_get_default_mod_mask()

        if event.button == 1:
            if event.type == Gdk.EventType.BUTTON_PRESS:
                x = int((coords[0] - self.min_x)*Pango.SCALE)
                y = int((coords[1] - self.min_y)*Pango.SCALE)
                loc = self.layout.xy_to_index(x, y)
                self.index = loc[0]
                if loc[0] >= len(self.text) - 1 or self.text[loc[0]+1] == '\n':
                    self.index += loc[1]
                self.bindex = self.bindex_from_index(self.index)
                if not (event.state & modifiers) & Gdk.ModifierType.SHIFT_MASK:
                    self.end_index = self.index
            elif event.type == Gdk.EventType._2BUTTON_PRESS:
                self.index = len(self.text)
                self.end_index = 0                        # and mark all
                self.double_click = True

        elif event.button == 2:
            x = int((coords[0] - self.min_x)*Pango.SCALE)
            y = int((coords[1] - self.min_y)*Pango.SCALE)
            loc = self.layout.xy_to_index(x, y)
            self.index = loc[0]
            if loc[0] >= len(self.text) - 1 or self.text[loc[0]+1] == '\n':
                self.index += loc[1]
            self.bindex = self.bindex_from_index(self.index)
            self.end_index = self.index
            if os.name != 'nt':
                clip = Gtk.Clipboard(selection="PRIMARY")
                self.paste_text(clip)

        del self.current_attrs
        self.current_attrs = []
        self.recalc_edges()
        self.emit("update_view")

        self.selection_changed()

    def _create_textview(self):
        # When the button is pressed inside a text thought,
        # create a textview (necessary for invoking the
        # on-screen keyboard) instead of processing the text
        # by grabbing keyboard events.
        if self.textview is None:
            self.textview = Gtk.TextView()
            margin = utils.margin_required(utils.STYLE_NORMAL)
            x, y, w, h = self.textview_rescale()
            self.textview.set_size_request(
                w if w > 0 else 1, h if h > 0 else 1)
            self._fixed.put(self.textview, x, y)
        self.textview.set_justification(Gtk.Justification.CENTER)

        font, size = None, None
        bold, italic, underline = False, False, False
        # Get current attributes and set them here
        """
        while (1):
            r = it.range()
            for x in it.get_attrs():
                if x.type == Pango.Weight and x.value == Pango.Weight.BOLD:
                    bold = True
                elif x.type == Pango.Style and x.value == Pango.Style.ITALIC:
                    italic = True
                elif x.type == Pango.Underline and x.value == Pango.Underline.SINGLE:
                    underline = True
                elif x.type == Pango.ATTR_FONT_DESC:
                    parts = x.desc.to_string ().split()
                    font = string.join(parts[0:-2])
                    size = parts[-1]

            if not it.next():
                break

        if font is None:
            font = 'Sans'
        if size is None:
            size = utils.default_font_size
            font_desc = Pango.FontDescription(font)
            font_desc.set_size(
                int(int(size) * Pango.SCALE * self._parent.scale_fac))

        if bold:
            font_desc.set_weight(Pango.Weight.BOLD)
        if italic:
            font_desc.set_style(Pango.Style.ITALIC)
        self.textview.modify_font(font_desc)
        """

        r, g, b = utils.gtk_to_cairo_color(self.foreground_color)
        rgba = Gdk.Color(int(65535 * r), int(65535 * g), int(65535 * b))
        self.textview.modify_text(Gtk.StateType.NORMAL, rgba)

        self.textview.get_buffer().set_text(self.text)
        self.textview.show()

        if self._textview_handler is None:
            self._textview_handler = self.textview.connect(
                'focus-out-event', self._textview_focus_out_cb)
            self.copy_handler = self.textview.connect(
                'copy-clipboard', self._textview_copy_cb)
            self.cut_handler = self.textview.connect(
                'cut-clipboard', self._textview_cut_cb)
            self.paste_handler = self.textview.connect(
                'paste-clipboard', self._textview_paste_cb)
            self.select_handler = self.textview.connect(
                'select-all', self._textview_select_cb)
        self.textview.grab_focus()
        self._fixed.show()

    def textview_rescale(self):
        tx = self._parent.translation[0] * self._parent.scale_fac
        ty = self._parent.translation[1] * self._parent.scale_fac
        margin = utils.margin_required(utils.STYLE_NORMAL)
        hadj = int(self._parent.hadj)
        vadj = int(self._parent.vadj)
        w = int((self.width - margin[0] - margin[2])
                * self._parent.scale_fac)
        # w = max(w, margin[0] + margin[2])
        h = int((self.height - margin[1] - margin[3])
                * self._parent.scale_fac)
        # h = max(h, margin[1] + margin[3])
        xo = Gdk.Screen.width() \
            * (1. - self._parent.scale_fac) / 2.
        yo = Gdk.Screen.height() \
            * (1. - self._parent.scale_fac) / 1.25  # FIXME
        x = (self.ul[0] + margin[0]) * self._parent.scale_fac
        y = (self.ul[1] + margin[1]) * self._parent.scale_fac
        return int(x + xo - hadj + tx), int(y + yo - vadj + ty), \
            int(w), int(h)

    def apply_tags(self):
        buffer = self.textview.get_buffer()
        bounds = buffer.get_bounds()
        if len(bounds) == 0:
            return

        start, end = bounds

        if self.attributes["bold"]:
            buffer.apply_tag(self.tag_bold, start, end)
        else:
            buffer.remove_tag(self.tag_bold, start, end)

        if self.attributes["italic"]:
            buffer.apply_tag(self.tag_italic, start, end)
        else:
            buffer.remove_tag(self.tag_italic, start, end)

        if self.attributes["underline"]:
            buffer.apply_tag(self.tag_underline, start, end)
        else:
            buffer.remove_tag(self.tag_underline, start, end)

        buffer.apply_tag(self.tag_font, start, end)

    def _textview_copy_cb(self, widget=None, event=None):
        self.textview.get_buffer().copy_clipboard(self._clipboard)
        return True

    def _textview_cut_cb(self, widget=None, event=None):
        self.textview.get_buffer().cut_clipboard(
            self._clipboard, self.textview.get_editable())
        self._textview_process()
        return True

    def _textview_paste_cb(self, widget=None, event=None):
        self.textview.get_buffer().paste_clipboard(
            self._clipboard, None, self.textview.get_editable())
        self._textview_process()
        return True

    def _textview_select_cb(self, widget=None, event=None):
        buffer = self.textview.get_buffer()
        buffer.select_range(buffer.get_start_iter(),
                            buffer.get_end_iter())
        return True

    def _textview_focus_out_cb(self, widget=None, event=None):
        self._textview_process()
        return False

    def _textview_process(self):
        self.index = 0
        self.end_index = len(self.text)
        self.delete_char()
        bounds = self.textview.get_buffer().get_bounds()
        self.add_text(self.textview.get_buffer().get_text(
            bounds[0], bounds[1], True))
        self.emit("title_changed", self.text)
        self.emit("update_view")
        return False

    def process_button_release(self, event, transformed):
        if self.orig_size:
            if self.creating:
                orig_size = self.width >= MIN_SIZE or self.height >= MIN_SIZE
                self.width = orig_size and max(
                    MIN_SIZE, self.width) or DEFAULT_WIDTH
                self.height = orig_size and max(
                    MIN_SIZE, self.height) or DEFAULT_HEIGHT
                self.recalc_edges()
                self.creating = False
            else:
                self.undo.add_undo(UndoManager.UndoAction(self, UNDO_RESIZE,
                                                          self.undo_resize, self.orig_size, (self.ul, self.width, self.height)))

        self.double_click = False
        return ResizableThought.process_button_release(self, event, transformed)

    def selection_changed(self):
        # Fix me: We are forcing selection to entire buffer
        # (start, end) = (min(self.index, self.end_index), max(self.index, self.end_index))
        start, end = 0, len(self.text)
        self.emit("text_selection_changed", start, end, self.text[start:end])

    def handle_motion(self, event, transformed):
        if ResizableThought.handle_motion(self, event, transformed):
            self.recalc_edges()
            return True

        if self.textview is not None and self.ul is not None:
            x, y, w, h = self.textview_rescale()
            self.textview.set_size_request(
                w if w > 0 else 1, h if h > 0 else 1)
            self._fixed.move(self.textview, x, y)

        if not self.editing or self.resizing:
            return False

        if event.state & Gdk.ModifierType.BUTTON1_MASK and not self.double_click:
            if transformed[0] < self.max_x and transformed[0] > self.min_x and \
               transformed[1] < self.max_y and transformed[1] > self.min_y:
                x = int((transformed[0] - self.min_x)*Pango.SCALE)
                y = int((transformed[1] - self.min_y)*Pango.SCALE)
                loc = self.layout.xy_to_index(x, y)
                self.index = loc[0]
                if loc[0] >= len(self.text) - 1 or self.text[loc[0]+1] == '\n':
                    self.index += loc[1]
                self.bindex = self.bindex_from_index(self.index)
                self.selection_changed()
                return True

        return False

    def export(self, context, move_x, move_y):
        utils.export_thought_outline(context, self.ul, self.lr, self.background_color, self.am_selected, self.am_primary, utils.STYLE_NORMAL,
                                     (move_x, move_y))

        r, g, b = utils.gtk_to_cairo_color(self.foreground_color)
        context.set_source_rgb(r, g, b)
        context.move_to(self.min_x+move_x, self.min_y+move_y)
        ##context.show_layout (self.layout)
        context.set_source_rgb(0, 0, 0)
        context.stroke()

    def update_save(self):
        next = self.element.firstChild
        while next:
            m = next.nextSibling
            if next.nodeName == "attribute":
                self.element.removeChild(next)
                next.unlink()
            next = m

        if self.text_element.parentNode is not None:
            self.text_element.replaceWholeText(self.text)
        text = self.extended_buffer.get_text()
        if text:
            self.extended_buffer.update_save()
        else:
            try:
                self.element.removeChild(self.extended_buffer.element)
            except xml.dom.NotFoundErr:
                pass
        self.element.setAttribute("cursor", str(self.index))
        self.element.setAttribute("ul-coords", str(self.ul))
        self.element.setAttribute("lr-coords", str(self.lr))
        self.element.setAttribute("identity", str(self.identity))
        self.element.setAttribute(
            "background-color", utils.color_to_string(self.background_color))
        self.element.setAttribute(
            "foreground-color", utils.color_to_string(self.foreground_color))

        if self.am_selected:
            self.element.setAttribute("current_root", "true")

        else:
            try:
                self.element.removeAttribute("current_root")

            except xml.dom.NotFoundErr:
                pass

        if self.am_primary:
            self.element.setAttribute("primary_root", "true")

        else:
            try:
                self.element.removeAttribute("primary_root")

            except xml.dom.NotFoundErr:
                pass

        doc = self.element.ownerDocument
        """
        while (1):
            r = it.range()
            for x in it.get_attrs():
                if x.type == Pango.Weight and x.value == Pango.Weight.BOLD:
                    elem = doc.createElement ("attribute")
                    self.element.appendChild (elem)
                    elem.setAttribute("start", str(r[0]))
                    elem.setAttribute("end", str(r[1]))
                    elem.setAttribute("type", "bold")
                elif x.type == Pango.Style and x.value == Pango.Style.ITALIC:
                    elem = doc.createElement ("attribute")
                    self.element.appendChild (elem)
                    elem.setAttribute("start", str(r[0]))
                    elem.setAttribute("end", str(r[1]))
                    elem.setAttribute("type", "italics")
                elif x.type == Pango.Underline and x.value == Pango.Underline.SINGLE:
                    elem = doc.createElement ("attribute")
                    self.element.appendChild (elem)
                    elem.setAttribute("start", str(r[0]))
                    elem.setAttribute("end", str(r[1]))
                    elem.setAttribute("type", "underline")
                elif x.type == Pango.AttrFontDesc:
                    elem = doc.createElement ("attribute")
                    self.element.appendChild (elem)
                    elem.setAttribute("start", str(r[0]))
                    elem.setAttribute("end", str(r[1]))
                    elem.setAttribute("type", "font")
                    elem.setAttribute("value", x.desc.to_string ())
            if not it.next():
                break
        """

    def rebuild_byte_table(self):
        # Build the Byte table
        del self.bytes
        self.bytes = ''
        tmp = self.text.encode("utf-8")
        current = 0
        for z in range(len(self.text)):
            if str(self.text[z]) == str(tmp[current]):
                self.bytes += '1'
            else:
                blen = 2
                while 1:
                    try:
                        if str(tmp[current:current+blen].encode()) == str(self.text[z]):
                            self.bytes += str(blen)
                            current += (blen-1)
                            break
                        blen += 1
                    except:
                        blen += 1
            current += 1
        self.bindex = self.b_f_i(self.index)
        self.text = tmp

    def load(self, node, tar):
        self.index = 0  # int (node.getAttribute ("cursor"))
        self.end_index = self.index
        tmp = node.getAttribute("ul-coords")
        self.ul = utils.parse_coords(tmp)
        tmp = node.getAttribute("lr-coords")
        self.lr = utils.parse_coords(tmp)

        self.width = self.lr[0] - self.ul[0]
        self.height = self.lr[1] - self.ul[1]

        self.identity = 0  # int (node.getAttribute ("identity"))
        try:
            tmp = node.getAttribute("background-color")
            self.background_color = Gdk.Color.parse(tmp)
            tmp = node.getAttribute("foreground-color")
            self.foreground_color = Gdk.Color.parse(tmp)
        except ValueError:
            pass

        self.am_selected = node.hasAttribute("current_root")
        self.am_primary = node.hasAttribute("primary_root")

        for n in node.childNodes:
            if n.nodeType == n.TEXT_NODE:
                self.text = n.data
            elif n.nodeName == "Extended":
                self.extended_buffer.load(n)
            elif n.nodeName == "attribute":
                attrType = n.getAttribute("type")
                start = int(n.getAttribute("start"))
                end = int(n.getAttribute("end"))

                if attrType == "bold":
                    self.attributes["bold"] = True
                elif attrType == "italics":
                    self.atributes["italic"] = True
                elif attrType == "underline":
                    self.attributes["underline"] = True
                # elif attrType == "font":
                ##    self.attributes["font"] = font
            else:
                print("Unknown: "+n.nodeName)
        self.rebuild_byte_table()
        self.recalc_edges()

    def copy_text(self, clip):
        self._clipboard = clip
        self._textview_copy_cb()

    def cut_text(self, clip):
        self._clipboard = clip
        self._textview_copy_cb()

    def paste_text(self, clip):
        self._clipboard = clip
        self._textview_paste_cb()

    def delete_surroundings(self, imcontext, offset, n_chars, mode):
        # TODO: Add in Attr stuff
        orig = len(self.text)
        left = self.text[:offset]
        right = self.text[offset+n_chars:]
        local_text = self.text[offset:offset+n_chars]
        self.text = left+right
        self.rebuild_byte_table()
        new = len(self.text)
        if self.index > len(self.text):
            self.index = len(self.text)

        change = old - new
        changes = []
        old_attrs = self.attributes.copy()
        accounted = -change
        index = offset
        end_index = offset - (new-orig)

        """while (1):
            (start,end) = it.range()
            l = it.get_attrs()
            if end <= start:
                for x in l:
                    changes.append(x)
            elif start < index and end <= end_index:
                # partial ending
                for x in l:
                    old_attrs.append(x.copy())
                    accounted -= (x.end_index - index)
                    x.end_index -= (x.end_index - index)
                    changes.append(x)
            elif start <= index and end >= end_index:
                # Swallow whole
                accounted -= (end - start)
                for x in l:
                    old_attrs.append(x.copy())
                    x.end_index += change
                    changes.append(x)
            elif start < end_index and end > end_index:
                # partial beginning
                for x in l:
                    old_attrs.append(x.copy())
                    accounted -= (x.start_index - index)
                    x.start_index = index
                    x.end_index = x.start_index + (end - start) - accounted
                    changes.append(x)
            else:
                # Past
                for x in l:
                    old_attrs.append(x.copy())
                    x.start_index += change
                    x.end_index += change
                    changes.append(x)
            if it.next() == False:
                break
        """
        self.recalc_edges()
        self.undo.add_undo(UndoManager.UndoAction(self, UndoManager.DELETE_LETTER, self.undo_text_action,
                                                  self.b_f_i(offset), local_text, len(
                                                      local_text),
                                                  local_bytes, old_attrs, changes))
        self.emit("title_changed", self.text)
        self.bindex = self.bindex_from_index(self.index)
        self.emit("update_view")

    def preedit_changed(self, imcontext, mode):
        self.preedit = imcontext.get_preedit_string()
        if self.preedit[0] == '':
            self.preedit = None
        self.recalc_edges()
        self.emit("update_view")

    def retrieve_surroundings(self, imcontext, mode):
        imcontext.set_surrounding(self.text, -1, self.bindex)
        return True

    def undo_attr_cb(self, action, mode):
        self.undo.block()
        if mode == UndoManager.UNDO:
            if action.undo_type == UNDO_REMOVE_ATTR:
                self.current_attrs.append(action.args[0])
            elif action.undo_type == UNDO_ADD_ATTR:
                self.current_attrs.remove(action.args[0])
            elif action.undo_type == UNDO_REMOVE_ATTR_SELECTION:
                pass  # self.attributes = action.args[0].copy()
            elif action.undo_type == UNDO_ADD_ATTR_SELECTION:
                pass  # self.attributes = action.args[0].copy()
        else:
            if action.undo_type == UNDO_REMOVE_ATTR:
                self.current_attrs.remove(action.args[0])
            elif action.undo_type == UNDO_ADD_ATTR:
                self.current_attrs.append(action.args[0])
            elif action.undo_type == UNDO_REMOVE_ATTR_SELECTION:
                pass  # self.attributes = action.args[1].copy()
            elif action.undo_type == UNDO_ADD_ATTR_SELECTION:
                pass  # self.attributes = action.args[1].copy()
        self.recalc_edges()
        self.emit("update_view")
        self.undo.unblock()

    def set_attribute(self, active, attribute):
        # if not self.editing:
        #     return

        if attribute == 'bold':
            pstyle, ptype, pvalue = (
                Pango.Weight.NORMAL, Pango.Weight, Pango.Weight.BOLD)
        elif attribute == 'italic':
            pstyle, ptype, pvalue = (
                Pango.Weight.NORMAL, Pango.Style, Pango.Style.ITALIC)
        elif attribute == 'underline':
            pstyle, ptype, pvalue = (
                Pango.Underline.NONE, Pango.Underline, Pango.Underline.SINGLE)

        # Always modify whole string
        self.index = 0
        self.end_index = len(self.text)

        index, end_index = (self.index, self.end_index)
        init = min(index, end_index)
        end = max(index, end_index)

        if not active:
            """tmp = []
            attr = None
            if index == end_index:
                for x in self.current_attrs:
                    if x.type == ptype and x.value == pvalue:
                        attr = x
                    else:
                        tmp.append(x)
                    self.current_attrs = tmp
                    self.recalc_edges()
                    self.undo.add_undo(UndoManager.UndoAction(self, UNDO_REMOVE_ATTR,
                                          self.undo_attr_cb,
                                          attr))
                    return
            """
            """
            while True:
                r = it.range()
                if r[0] <= init and r[1] >= end:
                    for x in it.get_attrs():
                        if x.type == ptype and x.value == pvalue:
                            changed.append(self.create_attribute(attribute, r[0], init))
                            changed.append(self.create_attribute(attribute, end, r[1]))
                        else:
                            changed.append(x)
                else:
                    map(lambda x : changed.append(x), it.get_attrs())

                if not it.next():
                    break
            """
            old_attrs = self.attributes.copy()
            self.undo.add_undo(UndoManager.UndoAction(self, UNDO_REMOVE_ATTR_SELECTION,
                                                      self.undo_attr_cb,
                                                      old_attrs,
                                                      self.attributes.copy()))
        else:
            """
            if index == end_index:
                attr = self.create_attribute(attribute, index, end_index)
                self.undo.add_undo(UndoManager.UndoAction(self, UNDO_ADD_ATTR,
                                      self.undo_attr_cb,
                                      attr))
                self.current_attrs.append(attr)
                #self.attributes.insert(attr)
            else:
                attr = self.create_attribute(attribute, init, end)
                old_attrs = self.attributes.copy()
                self.attributes.change(attr)
                self.undo.add_undo(UndoManager.UndoAction(self, UNDO_ADD_ATTR_SELECTION,
                                      self.undo_attr_cb,
                                      old_attrs,
                                      self.attributes.copy()))
            """
        self.recalc_edges()
        self.remove_textview()

    def set_bold(self, active):
        self.attributes["bold"] = active
        self.apply_tags()

    def set_italics(self, active):
        self.attributes["italic"] = active
        self.apply_tags()

    def set_underline(self, active):
        self.attributes["underline"] = active
        self.apply_tags()

    def set_font(self, font_name, font_size):
        # With textview, we are always editing
        # if not self.editing:
        #     return

        # Always modify whole string
        self.index = 0
        self.end_index = len(self.text)
        self.attributes["font"] = "%s %d" % (font_name, font_size)

        start = min(self.index, self.end_index)
        end = max(self.index, self.end_index)

        self.textview.get_buffer().remove_tag(self.tag_font)
        self.tag_font = self.textview.get_buffer().create_tag(
            "font", self.attributes["font"])

        if start == end:
            self.undo.add_undo(UndoManager.UndoAction(self, UNDO_ADD_ATTR,
                                                      self.undo_attr_cb,
                                                      ))  # attr))
            # self.current_attrs.change(attr)
        else:
            pass
            # self.undo.add_undo(UndoManager.UndoAction(self, UNDO_ADD_ATTR_SELECTION,
            # self.undo_attr_cb,
            # old_attrs,
            # self.attributes.copy()))
        self.recalc_edges()
        self.remove_textview()

    def inside(self, inside):
        # FIXME: with switch to textview, we don't need cursor update
        if self.editing:
            if self.textview is not None:
                self.textview.grab_focus()
            self.emit("change_mouse_cursor", Gdk.CursorType.XTERM)
        else:
            ResizableThought.inside(self, inside)

    def enter(self):
        if self.editing:
            return
        self.orig_text = self.text
        self.editing = True

    def remove_textview(self):
        if self.textview is not None:
            self._textview_process()
            self._textview_handler = None
            self.textview.hide()
            self.textview.destroy()
            self.textview = None

    def leave(self):
        self.remove_textview()
        if not self.editing:
            return
        ResizableThought.leave(self)
        self.editing = False
        self.end_index = self.index
        self.emit("update_links")
        self.recalc_edges()
