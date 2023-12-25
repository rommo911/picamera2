#!/usr/bin/python3

# This is the same as mjpeg_server.py, but uses the h/w MJPEG encoder.

import io
import logging
import socketserver
from http import server
from threading import Condition
import os
import threading
from time import sleep
from picamera2 import Picamera2 , MappedArray,Preview
from picamera2.encoders import MJPEGEncoder
from picamera2.outputs import FileOutput
from picamera2.encoders import H264Encoder
from picamera2.outputs import FfmpegOutput
import numpy as np
import libcamera
import time
import cv2
import json
from paho.mqtt import client as mqtt_client

picam2 = Picamera2()
mqtt_topic_base = "rpi_cam"
mqtt_topic_availability = mqtt_topic_base + "/status"
mqtt_topic_lux = mqtt_topic_base + "/lux"
mqtt_topic_motion = mqtt_topic_base + "/motion"
mqtt_topic_motion_detection = mqtt_topic_base + "/motion_detection"
temp_capture_file_path = "/tmp/test.jpg"
requestImageSave = False

class MQTT():
    def __init__(self):
        self.mqtt_broker = '127.0.0.1'
        self.mqtt_port = 8883
        self.mqtt_client_id = "rpi_cam_sensor"
        self.username = 'rami'
        self.password = '5461'
        self.mqtt_client = mqtt_client.Client(self.mqtt_client_id)
        self.RECONNECT_RATE = 1.1
        self.MAX_RECONNECT_COUNT = 5
        self.reconnect_delay = 2
        self.MAX_RECONNECT_DELAY = 10
    def mqtt_on_connect(self , client, userdata, flags, rc):
        print("Connected to MQTT Broker YAAAAAAAAAAAAAAAAAY!")
        if rc == 0:
            print("Connected to MQTT Broker YAAAAAAAAAAAAAAAAAY!")
        else:
            print("Failed to connect, return code %d\n", rc)

    def mqtt_on_disconnect(self ,client, userdata, rc):
        print("Disconnected with result code: %s", rc)
        reconnect_count = 0
        while reconnect_count < self.MAX_RECONNECT_COUNT:
            print("Reconnecting in %d seconds...", self.reconnect_delay)
            time.sleep(self.reconnect_delay)
            try:
                client.reconnect()
                print("Reconnected successfully!")
                return
            except Exception as err:
                print("%s. Reconnect failed. Retrying...", err)
            self.reconnect_delay *= self.RECONNECT_RATE
            self.reconnect_delay = min(self.reconnect_delay, self.MAX_RECONNECT_DELAY)
            reconnect_count += 1
        print("Reconnect failed after %s attempts. Exiting...", reconnect_count)

    def connect_mqtt(self):
        print("connect_mqtt")
        # Set Connecting Client ID
        self.mqtt_client = mqtt_client.Client(self.mqtt_client_id)
        self.mqtt_client.username_pw_set(self.username, self.password)
        self.mqtt_client.on_connect = self.mqtt_on_connect
        self.mqtt_client.on_disconnect = self.mqtt_on_disconnect
        self.mqtt_client.connect(self.mqtt_broker, self.mqtt_port)
        self.mqtt_client.will_set(mqtt_topic_availability, payload="offline", qos=1, retain=True)
        print("connect_mqtt done")
        return self.mqtt_client


def current_time_second():
    return round(time.time())

#  configuration settings
IMAGE_RESOLUTION = (1280, 720)
FRAMERATE = 20.0
cnontrols = {
    "AwbEnable": True,
    "AwbMode": libcamera.controls.AwbModeEnum.Indoor,
    "AeEnable": True,
    "AeMeteringMode": libcamera.controls.AeMeteringModeEnum.Matrix,
    "ColourGains": [0.0, 0.0],
    "FrameRate": FRAMERATE
}

class StreamingOutput(io.BufferedIOBase):
    def __init__(self):
        self.frame = None
        self.condition = Condition()

    def write(self, buf):
        with self.condition:
            self.frame = buf
            self.condition.notify_all()
    

last_timetamb_ms = 0
globalbusy = False
busyrecording = False
RecordHelperThread = threading.Thread()
RecordHelperThread_event = threading.Event()
motionValue = 0

def apply_timestamp(request):
    timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
    thickness = 2
    scale = 1
    colour = (0, 255, 0)
    origin = (0, 30)
    font = cv2.FONT_HERSHEY_SIMPLEX
    with MappedArray(request, "main") as m:
        cv2.putText(m.array, timestamp, origin, font, scale, colour, thickness)


def SendOK(StreamingHandler):
    _PAGE ="""\
    <html> <head> <title>picamera2 Rami</title></head>
    <body>
    <h1>Command OK </h1>
    </body>
    </html>
    """
    content = _PAGE.encode('utf-8')
    StreamingHandler.send_response(200)
    StreamingHandler.send_header('Content-Type', 'text/html')
    StreamingHandler.send_header('Content-Length', len(content))
    StreamingHandler.end_headers()
    StreamingHandler.wfile.write(content)

def SendNOT_OK(StreamingHandler):
    _PAGE ="""\
    <html> <head> <title>picamera2 Rami</title></head>
    <body>
    <h1>Command NOT OK  </h1>
    </body>
    </html>
    """
    content = _PAGE.encode('utf-8')
    StreamingHandler.send_response(200)
    StreamingHandler.send_header('Content-Type', 'text/html')
    StreamingHandler.send_header('Content-Length', len(content))
    StreamingHandler.end_headers()
    StreamingHandler.wfile.write(content)    
    
def StartImageCapture(StreamingHandler) :
    global last_timetamb_ms,requestImageSave,temp_capture_file_path
    _now = current_time_second() - 1703546000
    try:
        if ( _now < (last_timetamb_ms + 10 ) ):
            print("duplicate now= ",_now , " , last="  ,last_timetamb_ms)
            with open(temp_capture_file_path, 'rb') as jpeg_file:
                StreamingHandler.send_response(200)
                StreamingHandler.send_header('Content-Type', 'image/jpeg')
                StreamingHandler.send_header('Content-Length', os.path.getsize(temp_capture_file_path))
                StreamingHandler.end_headers()
                StreamingHandler.wfile.write(jpeg_file.read())
        else: 
            print("requesting new image")
            requestImageSave = True
            last_timetamb_ms = _now
            sleep(0.5)
            with open(temp_capture_file_path, 'rb') as jpeg_file:
                StreamingHandler.send_response(200)
                StreamingHandler.send_header('Content-Type', 'image/jpeg')
                StreamingHandler.send_header('Content-Length', os.path.getsize(temp_capture_file_path))
                StreamingHandler.end_headers()
                StreamingHandler.wfile.write(jpeg_file.read())
    except  Exception as exc:
        print(" capture erro jpeg_file exception %s ",str(exc))

def StartStream(StreamingHandler) :
    global globalbusy, ExitAllThread
    if (globalbusy == True):
        SendNOT_OK(StreamingHandler)
        return
    try :
        globalbusy = True
        print("wait for motion to stop")
        sleep(0.5)
        picam2.stop()
        picam2.configure(picam2.create_video_configuration(main={"size": (1280, 720)}))
        picam2.set_controls(cnontrols)
        mjpegencoder = MJPEGEncoder()
        output = StreamingOutput()
        StreamFile_output = FileOutput(output)
        mjpegencoder = MJPEGEncoder()
        picam2.start_recording(mjpegencoder,StreamFile_output)
        StreamingHandler.send_response(200)
        StreamingHandler.send_header('Age', 0)
        StreamingHandler.send_header('Cache-Control', 'no-cache, private')
        StreamingHandler.send_header('Pragma', 'no-cache')
        StreamingHandler.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=FRAME')
        StreamingHandler.end_headers()
        try:
            while ExitAllThread == False:
                with output.condition:
                    output.condition.wait()
                    frame = output.frame
                StreamingHandler.wfile.write(b'--FRAME\r\n')
                StreamingHandler.send_header('Content-Type', 'image/jpeg')
                StreamingHandler.send_header('Content-Length', len(frame))
                StreamingHandler.end_headers()
                StreamingHandler.wfile.write(frame)
                StreamingHandler.wfile.write(b'\r\n')
        except Exception as e:
                    logging.warning(
                        'Removed streaming client %s: %s',
                        StreamingHandler.client_address, str(e))
    except  Exception as exc:
        print(" stream error exception %s",str(exc))
    picam2.stop_recording()
    picam2.stop()
    globalbusy = False
    print("stream handler done")

def checkMotionThread():
    global motionValue , ExitAllThread , _mqtt_client , globalbusy, requestImageSave
    lsize = (320, 240)
    started = False
    w, h = lsize
    buf_prev = None
    lux_value = 0
    _now_lux_value = 0 
    last_detcted = "0"
    detection = "off"
    print("started motion thread ") 
    while (ExitAllThread == False):
            if (globalbusy == False ):
                if (started == False):
                    try: 
                        print(" *********** start motion cam config ************") 
                        picam2.stop()
                        picam2.configure(picam2.create_video_configuration(main={"size": (1280, 720)}, lores={"size": lsize, "format": "YUV420"}))
                        picam2.start()
                        sleep(0.5)
                        started = True
                    except: 
                        print("exception in motion" )
                        started = False
                        picam2.stop()
                (buf_cur, ), metadata = picam2.capture_buffers(["main"])
                if (requestImageSave):
                    requestImageSave = False
                    img = picam2.helpers.make_image(buf_cur, picam2.camera_configuration()["main"])
                    picam2.helpers.save(img, metadata, temp_capture_file_path)
                    print("new image saved " )
                _now_lux_value = int(metadata['Lux'])
                if abs(_now_lux_value - lux_value ) > 1:
                    lux_value = _now_lux_value
                    print("lux=",lux_value)
                    _mqtt_client.publish(mqtt_topic_lux,json.dumps({"lux" : lux_value}))
                    sleep(0.5)
                    buf_prev = None
                else: 
                    buf_cur = picam2.capture_buffer("lores")
                    if buf_cur is not None :
                        buf_cur = buf_cur[:w * h].reshape(h, w)
                        if (buf_prev is not None) :
                            temp_motionValue = np.square(np.subtract(buf_cur, buf_prev)).mean()
                            #
                            #print(" *********** motion =",temp_motionValue)
                            if (temp_motionValue > 10):
                                detection = "on"
                                if(motionValue < 20 ):
                                    motionValue = motionValue+1
                                    print(" *********** motion detected ",temp_motionValue , ", total = " , motionValue)
                                    _mqtt_client.publish(mqtt_topic_motion,json.dumps({"motion" : motionValue}))
                            else:
                                detection = "off"
                                if(motionValue > 0):
                                    motionValue = motionValue - 1
                                    if(motionValue == 0):
                                        _mqtt_client.publish(mqtt_topic_motion,json.dumps({"motion" : motionValue}))
                            if (last_detcted != detection):
                                last_detcted = detection
                                _mqtt_client.publish(mqtt_topic_motion_detection,json.dumps({"motion_Detction" :detection , "diff" : temp_motionValue}))
                        else :
                            buf_cur = picam2.capture_buffer("lores")
                            buf_cur = buf_cur[:w * h].reshape(h, w)
                        buf_prev = buf_cur
                    sleep(0.4)
            elif (started):
                print("*********** stopping motion ********** ") 
                buf_prev = None
                started = False
            else :
                sleep(0.5)
    print("motion thread out ") 

def StartRecord(StreamingHandler) :
    global globalbusy,busyrecording,RecordHelperThread_event
    if (globalbusy == False ):
        try:
            globalbusy = True
            busyrecording = True 
            sleep(0.5)
            picam2.stop()
            picam2.configure(picam2.create_video_configuration(main={"size": (1280, 720)}))
            picam2.set_controls(cnontrols)
            h264_encoder = H264Encoder(800000, framerate=15)
            currentTime = time.strftime("%Y%m%d-%H-%M-%S")
            filename1 = '/tmp/record_' + currentTime + '.mp4'
            Ffmpeg_output = FfmpegOutput(filename1, audio=False)
            #
            print(" starting recording ")
            picam2.start_recording(h264_encoder, Ffmpeg_output) #  pts='timestamp.txt'
            SendOK(StreamingHandler)
            RecordHelperThread_event.clear()
            print(" started recording ")
            RecordHelperThread_event.wait(timeout=900)
            #sleep(2)
            print("stopping recording ")
            picam2.stop_recording()
            picam2.stop()
        except NameError:
                print("record error exception")
        busyrecording = False
        globalbusy = False
    else :
        print("camera busy for recording")
        SendNOT_OK(StreamingHandler)
                
def StopRecord(StreamingHandler) :
    global globalbusy,busyrecording,RecordHelperThread_event
    if (busyrecording == True):
        print("stopping record ")
        RecordHelperThread_event.set()
        SendOK(StreamingHandler)
    else :
        print(" not recording")
        SendNOT_OK(StreamingHandler)
    
class StreamingHandler(server.BaseHTTPRequestHandler):
    def do_GET(self):
        global globalbusy
        print(' received request ',self.path ,"***")
        try : 
            if (self.path == '/'):
                self.send_response(301)
                self.send_header('Location', '/still.html')
                self.end_headers()
            elif (self.path == '/index.html'):
                self.send_error(404)
                self.end_headers()
            elif ((self.path == '/still.html' or  self.path == '/still.jpg'  or  self.path == '/still')):
                StartImageCapture(self)
            elif self.path == '/stream.mjpg':
                StartStream(self)
            elif self.path == '/record.start':
                if (busyrecording == False):
                    busyrecording = True
                    HelperThread = threading.Thread(target = StartRecord(self) )
                    HelperThread.start()
                    sleep(1)
                else :
                    SendNOT_OK(self)
            elif self.path == '/record.stop':
                StopRecord(self)
            else:
                self.send_error(404)
                self.end_headers()
        except Exception as ex : 
            print("request process exception =",ex)

class StreamingServer(socketserver.ThreadingMixIn, server.HTTPServer):
    allow_reuse_address = True
    #daemon_threads = True
    
MqttClass =  MQTT()
_mqtt_client = MqttClass.connect_mqtt()
ExitAllThread = False
globalbusy = False
_mqtt_client.publish(mqtt_topic_motion_detection,json.dumps({"motion_Detction" :"off"}))
_mqtt_client.publish(mqtt_topic_motion,json.dumps({"motion" :"0"}))
_mqtt_client.publish(mqtt_topic_lux,json.dumps({"lux" :"0"}))
_mqtt_client.publish(mqtt_topic_availability,"online", retain=True)

MotionHelperThread = threading.Thread( target = checkMotionThread )
MotionHelperThread.start()
try:
    address = ('', 8000)
    server = StreamingServer(address, StreamingHandler)
    print("Server started at http://localhost:8000")
    server.serve_forever()
except KeyboardInterrupt:
    server.shutdown()
    ExitAllThread = True
    print("Server stopped.") 
_mqtt_client.publish(mqtt_topic_availability,"offline")
