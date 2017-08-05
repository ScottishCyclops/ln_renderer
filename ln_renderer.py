#    Local Network Render
#    Copyright (C) 2017 Scott Winkelmann
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.

import glob
from base64 import b64encode
from gzip import decompress as decompress_gzip
from io import BytesIO
from json import loads as decode_json
from os.path import basename, dirname
from tarfile import open as open_tar
from time import sleep

import bpy
import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning

bl_info = {
    "name":        "Local Network Renderer",
    "author":      "Scott Winkelmann <scottlandart@gmail.com>",
    "version":     (1, 0, 0),
    "blender":     (2, 78, 0),
    "location":    "Properties Panel > Render Tab",
    "description": "Adds the ability to render a blender file on the local network",
    "warning":     "",
    "wiki_url":    "https://github.com/ScottishCyclops/",
    "tracker_url": "https://github.com/ScottishCyclops//issues",
    "category":    "Render"
}

password = "MwCF!@DPyv)k^SG4"
command = "farm"

handle = None
active_panel = None
canceled = False
#header_visibility = False

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)


def post_server(data):
    try:
        res = requests.post("https://0.0.0.0:3001/", data=data, verify=False)
    except Exception:
        res = None

    return res


def try_parse_res(res):
    if res is not None:
        return decode_json(res.text)
    else:
        return dict(code=-5)


def render(blend_file, animation=False):

    with open(blend_file, "rb") as f:
        render_payload = \
        {
            "pass": password,
            "command": command,
            "action": "anim" if animation else "still",
            "data": b64encode(f.read())
        }
    res = post_server(render_payload)
    return try_parse_res(res)


def cancel_render():
    cancel_payload = \
    {
        "pass": password,
        "command": command,
        "action": "cancel"
    }
    res = post_server(cancel_payload)
    return try_parse_res(res)


def get_render_status():
    status_payload = \
    {
        "pass": password,
        "command": command,
        "action": "status"
    }
    res = post_server(status_payload)
    return try_parse_res(res)


def retrieve_render(name, folder):
    """retrieve the render data by name and extracts it in the given folder"""
    retrieve_render_payload = \
    {
        "pass": password,
        "command": command,
        "action": "retrieve",
        "data": name
    }

    #get the tar.gz
    res = post_server(retrieve_render_payload)
    
    payload = try_parse_res(res)

    if payload["code"] >= 0:
        #decompresse the gz
        decompressed_file = decompress_gzip(bytearray.fromhex(payload["data"]))
        file_like = BytesIO(decompressed_file)

        #extract the tar
        tar = open_tar(fileobj=file_like, mode="r")
        tar.extractall(folder)

    return payload


def report_server_code(code, func):
    report_type = "ERROR" if code < 0 else "WARNING" if code > 0 else "INFO"
    prefix = "LNR: "
    default_msg = "Server returned code " + str(code)

    func({report_type}, prefix + {
        0:  "Request successful",
        -1: "Invalid request",
        -2: "Request failed",
        -3: "Access denied",
        -4: "No request",

        -5:  "Server not running",
        -10: "Process already running",
        -11: "Process not running",

        -12: "File does not exist",
        -13: "Folder does not exist",
        -14: "File not ready",

        -20: "Action not implemented",
    }.get(code, default_msg))


def lnr_panel_render(self, context):
    row = self.layout.row()
    row.operator(LnrRender.bl_idname, icon="RENDER_STILL", text="Network Render").animation = False
    row.operator(LnrRender.bl_idname, icon="RENDER_ANIMATION", text="Network Animation").animation = True


def lnr_panel_cancel(self, context):
    row = self.layout.row()
    row.operator(LnrCancel.bl_idname, icon="CANCEL", text="Cancel Network Render")

def force_redraw(context):
    """Does not work as expected"""
    context.window.screen.areas.update()


def switch_panels(new, context):
    global active_panel

    bpy.types.RENDER_PT_render.remove(active_panel)
    bpy.types.RENDER_PT_render.prepend(new)
    active_panel = new
    force_redraw(context)

def progress_bar(length, progress):
    block = int(round(length * progress))
    return "[" + "#" * block + "-" * (length-block) + "]"


'''
def header_status(self, context):
    global status
    content = "frame: " + str(status["frame"]) + " | time left: " + status["time_left"]

    self.layout.column(align=True).label(text=content)

def change_status_visibility(show=True):
    global header_visibility

    if show and not header_visibility:
        bpy.types.INFO_HT_header.append(header_status)
        header_visibility = True
    elif not show and header_visibility:
        bpy.types.INFO_HT_header.remove(header_status)
        header_visibility = False
'''


class LnrTimer(bpy.types.Operator):
    """Network Render checker"""
    bl_idname = "render.lnr_timer"
    bl_label = "Network Render Timer"
    bl_options = {"REGISTER"}

    _timer = None
    try_retrieving = False

    def modal(self, context, event):
        if(event.type == "TIMER"):
            global handle
            global active_panel
            global canceled

            #getting status
            if not self.try_retrieving:
                payload = get_render_status()

                if payload["code"] >= 0:
                    if payload["data"]["farm"] is 1:
                        #if the farm is stopped
                        #change_status_visibility(False)

                        switch_panels(lnr_panel_render, context)

                        if not canceled:
                            self.try_retrieving = True
                            self.report({"INFO"}, "LNR: Render completed")
                        else:
                            #if cancelled, no need to retrieve anything
                            self.report({"INFO"}, "LNR: Render cancelled")
                            canceled = False
                            self.cancel(context)
                            return {"FINISHED"}
                    else:
                        #change_status_visibility(True)
                        #farm running: print the data
                        data = None
                        extra_data = None
                        try:
                            data = payload["data"]["nodes"][0]
                            extra_data = payload["data"]["render_data"]
                        except KeyError:
                            pass

                        if data is not None:
                            frame = "  0"
                            try:
                                if data["current_frame"] != 0:
                                    frame = str(data["current_frame"]).rjust(3, " ")
                            except KeyError:
                                pass
                            
                            time_left = " unknown"
                            try:
                                time_left = str(data["time_left"]["minutes"]).rjust(2, "0") + ":" + \
                                            str(data["time_left"]["seconds"]).rjust(2, "0") + "." + \
                                            str(data["time_left"]["millis"]).rjust(2, "0")

                            except KeyError:
                                pass
                            
                            progress = 0.0
                            try:
                                progress = data["current_tile"] / data["num_tiles"]
                            except KeyError:
                                pass
                            
                            status = "frame: " + frame + \
                                    " | time left: " + time_left + \
                                    " | progress: " + str(round(progress * 100)).rjust(3, " ") + "% " + \
                                    progress_bar(20, progress)
                                

                            if extra_data is not None:
                                #next line not tested. èèeh
                                if extra_data["is_animation"]:
                                    anim_progress = 0.0
                                    try:
                                        anim_progress = (data["current_frame"] - extra_data["start_frame"]) / extra_data["end_frame"] 
                                    except KeyError:
                                        pass
                                    status += " | overall progress: " + \
                                              str(round(anim_progress * 100)).rjust(3, " ") + "% " + \
                                              progress_bar(20, anim_progress)

                            self.report({"INFO"}, status)                        
                else:
                    #in case of error, report it
                    report_server_code(payload["code"], self.report)
            else:
                #render retrieving
                #root folder to output retrieved data: the folder of the executed blend file
                folder = dirname(bpy.data.filepath)
                payload = retrieve_render(handle, folder)

                if payload["code"] != -14:
                    #si le code d'erreur n'est pas file not ready, on quittera le timer
                    #sinon, on le laisse tourner pour re-essayer
                    if payload["code"] >= 0:
                        #disk location of retrieved render
                        render_folder = folder + "/" + handle
                        #get last retrieved image
                        last_image = max(glob.iglob(render_folder + "/*"))
                        #name of the file in blender
                        img_name = "Network Render Result"
                        #replace the current render if it exists
                        try:
                            bpy.data.images.remove(bpy.data.images[img_name], do_unlink=True)
                        except KeyError:
                            pass
                        #open image in blender
                        bpy.ops.image.open(filepath=last_image, directory=render_folder, relative_path=False)
                        bpy.data.images[basename(last_image)].name = img_name
                    else:
                        #report any other errors
                        report_server_code(payload["code"], self.report)

                    #quit timer
                    self.report({"INFO"}, "LNR: Retrieved render data")
                    self.try_retrieving = False
                    self.cancel(context)
                    return {"FINISHED"}

                else:
                    print("could not retrieve render data")
        return {"PASS_THROUGH"}

    def execute(self, context):
        self._timer = context.window_manager.event_timer_add(0.3, context.window)
        context.window_manager.modal_handler_add(self)

        return {"RUNNING_MODAL"}
    
    def invoke(self, context, event):
        return self.execute(context)


    def cancel(self, context):
        #remove the timer
        context.window_manager.event_timer_remove(self._timer)


class LnrRender(bpy.types.Operator):
    """Render active scene on the network"""
    bl_idname = "render.lnr_render"
    bl_label = "Network Render"
    bl_options = {"REGISTER"}

    animation = bpy.props.BoolProperty(name="animation", default=False)

    @classmethod
    def poll(cls, context):
        if context.scene is not None:
            if context.scene.camera is not None:
                return True

        return False

    def execute(self, context):
        global handle
        global active_panel

        if bpy.data.is_dirty:
            bpy.ops.wm.save_mainfile()

        res = render(bpy.data.filepath, self.animation)

        if res["code"] < 0:
            report_server_code(res["code"], self.report)


            #if already running, swap panels to be able to cancel it
            if res["code"] == -10:
                switch_panels(lnr_panel_cancel, context)
        else:
            handle = res["data"]

            #hide render panel and show cancel button
            switch_panels(lnr_panel_cancel, context)

            bpy.ops.render.lnr_timer("INVOKE_DEFAULT")

        return {"FINISHED"}
    
    def invoke(self, context, event):
        return self.execute(context)


class LnrCancel(bpy.types.Operator):
    """Stop active job on the network"""
    bl_idname = "render.lnr_cancel"
    bl_label = "Cancel Network Render"
    bl_options = {"REGISTER"}

    def execute(self, context):
        global canceled

        res = cancel_render()

        if res["code"] < 0:
            report_server_code(res["code"], self.report)

            #if not running, swap panels
            if res["code"] == -11:
                switch_panels(lnr_panel_render, context)

        canceled = True

        return {"FINISHED"}

    def invoke(self, context, event):
        return self.execute(context)


def register():
    global active_panel

    #_percent_kwargs = dict(min=0.0, max=100.0, default=0.0, precision=1, subtype="PERCENTAGE", options={})
    #bpy.types.Scene.percent_current = bpy.props.FloatProperty(name="percent_current", **_percent_kwargs)
    #bpy.types.Scene.percent_total = bpy.props.FloatProperty(name="percent_total", **_percent_kwargs)

    bpy.utils.register_class(LnrTimer)
    bpy.utils.register_class(LnrRender)
    bpy.utils.register_class(LnrCancel)
    bpy.types.RENDER_PT_render.prepend(lnr_panel_render)

    active_panel = lnr_panel_render


def unregister():
    #change_status_visibility(False)

    bpy.types.RENDER_PT_render.remove(active_panel)
    bpy.utils.unregister_class(LnrCancel)
    bpy.utils.unregister_class(LnrRender)
    bpy.utils.unregister_class(LnrTimer)


if __name__ == "__main__":
    register()