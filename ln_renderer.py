#    Local Network Renderer
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
from gzip import decompress as decompress_gzip
from io import BytesIO
from json import loads as decode_json
from os.path import basename, dirname
from tarfile import open as open_tar

import bpy
from requests import post
from requests.packages.urllib3 import disable_warnings
from requests.packages.urllib3.exceptions import InsecureRequestWarning

bl_info = {
    "name":        "Local Network Renderer",
    "author":      "Scott Winkelmann <scottlandart@gmail.com>",
    "version":     (1, 0, 0),
    "blender":     (2, 78, 0),
    "location":    "Properties Panel > Render Tab",
    "description": "Adds the ability to render a blender file on the local network",
    "warning":     "",
    "wiki_url":    "https://github.com/ScottishCyclops/ln_renderer",
    "tracker_url": "https://github.com/ScottishCyclops/ln_renderer/issues",
    "category":    "Render"
}

#server configuration
password = "MwCF!@DPyv)k^SG4"
command = "farm"
server_ip = "0.0.0.0"
server_address = "https://" + server_ip + ":3001/"
extra_params = dict(verify=False)
#global variables
handle = None
active_panel = None
canceled = False
#warning suppresion for https requests
disable_warnings(InsecureRequestWarning)


#utility functions

def try_parse_res(res):
    """Try to parse a server response as JSON

    If it fails, will return code 'Server not running'"""

    if res is not None:
        return decode_json(res.text)
    else:
        return dict(code=-5)


def render(blend_file, animation=False):
    """Performs a render request on the server for a given file
    
    Returns th parsed response"""

    data = \
    {
        "pass": password,
        "command": command,
        "action": "anim" if animation else "still"
    }

    res = None
    with open(blend_file, "rb") as f:
        try:
            res = post(server_address + "upload", data=data, files={"blendfile": f}, **extra_params)
        except Exception:
            pass

    return try_parse_res(res)


def cancel_render():
    """Performs a cancel request on the server
    
    Returns th parsed response"""

    data = \
    {
        "pass": password,
        "command": command,
        "action": "cancel"
    }

    res = None
    try:
        res = post(server_address, data=data, **extra_params)
    except Exception:
        pass

    return try_parse_res(res)


def get_render_status():
    """Performs a status request on the server
    
    Returns th parsed response"""

    data = \
    {
        "pass": password,
        "command": command,
        "action": "status"
    }

    res = None
    try:
        res = post(server_address, data=data, **extra_params)
    except Exception:
        pass

    return try_parse_res(res)


def retrieve_render(handle, folder):
    """Performs a retrieve request on the server with the given handle
    
    The data is decompressed and written in a new subfolder inside 'folder'
    
    Returns th parsed response"""

    data = \
    {
        "pass": password,
        "command": command,
        "action": "retrieve",
        "data": handle
    }

    #get the tar.gz
    res = None
    try:
        res = post(server_address, data=data, **extra_params)
    except Exception:
        pass
    
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
    """Translates a server code to text and reports it with the given Operator.report function"""

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
    """Adds custom buttons for network rendering"""

    row = self.layout.row()
    row.operator(LnrRender.bl_idname, icon="RENDER_STILL", text="Network Render").animation = False
    row.operator(LnrRender.bl_idname, icon="RENDER_ANIMATION", text="Network Animation").animation = True


def lnr_panel_cancel(self, context):
    """Adds a custom button for network canceling"""

    row = self.layout.row()
    row.operator(LnrCancel.bl_idname, icon="CANCEL", text="Cancel Network Render")


def switch_panels(new, context):
    """Switches the custom panel visible under Properties > Render
    
    'new' can be 'lnr_panel_render' or 'lnr_panel_cancel'"""

    global active_panel

    bpy.types.RENDER_PT_render.remove(active_panel)
    bpy.types.RENDER_PT_render.prepend(new)
    active_panel = new
    context.window.screen.areas.update()


def progress_bar(length, progress):
    """Returns a text progress bar of the given length with the given progress"""

    block = int(round(length * progress))
    return "[" + "#" * block + "-" * (length-block) + "]"


#Operators

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
            global canceled

            #getting status
            if not self.try_retrieving:
                payload = get_render_status()

                if payload["code"] >= 0:
                    if payload["data"]["farm"] is 1:
                        #if the farm is stopped
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

                #root folder to output retrieved data
                folder = dirname(bpy.data.filepath)
                payload = retrieve_render(handle, folder)

                if payload["code"] != -14:
                    #si le code d'erreur n'est pas file not ready, on quittera le timer
                    #sinon, on le laisse tourner pour re-essayer
                    if folder == "":
                        self.report({"ERROR"}, "This blendfile's root folder is null")
                    else:
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

                            self.report({"INFO"}, "LNR: Retrieved render data")
                        else:
                            #report any other errors
                            report_server_code(payload["code"], self.report)

                    #quit timer
                    self.try_retrieving = False
                    self.cancel(context)
                    return {"FINISHED"}

        return {"PASS_THROUGH"}

    def execute(self, context):
        self._timer = context.window_manager.event_timer_add(0.5, context.window)
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
        else:
            canceled = True

        return {"FINISHED"}

    def invoke(self, context, event):
        return self.execute(context)


def register():
    global active_panel

    bpy.utils.register_class(LnrTimer)
    bpy.utils.register_class(LnrRender)
    bpy.utils.register_class(LnrCancel)
    bpy.types.RENDER_PT_render.prepend(lnr_panel_render)

    active_panel = lnr_panel_render


def unregister():
    global active_panel

    bpy.types.RENDER_PT_render.remove(active_panel)
    bpy.utils.unregister_class(LnrCancel)
    bpy.utils.unregister_class(LnrRender)
    bpy.utils.unregister_class(LnrTimer)


if __name__ == "__main__":
    register()
