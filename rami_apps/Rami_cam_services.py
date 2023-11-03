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

mqtt_topic_lux = "rpi_cam/lux"
mqtt_topic_motion = "rpi_cam/motion"
mqtt_topic_motion_detection = "rpi_cam/motion_detection"
mqtt_topic_base = "rpi_cam/status/"

class MQTT():
    def __init__(self):
        self.mqtt_broker = '127.0.0.1'
        self.mqtt_port = 8883
        self.mqtt_client_id = "rpi_cam_sensor"
        self.username = 'rami'
        self.password = '5461'
        self.mqtt_client = mqtt_client.Client(self.mqtt_client_id)

    def mqtt_on_connect(self,client, userdata, flags, rc):
        if rc == 0:
            print("Connected to MQTT Broker!")
        else:
            print("Failed to connect, return code %d\n", rc)

    def mqtt_on_disconnect(self,client, userdata, rc):
        print("Disconnected with result code: %s", rc)
        reconnect_count, reconnect_delay = 0, FIRST_RECONNECT_DELAY
        while reconnect_count < MAX_RECONNECT_COUNT:
            print("Reconnecting in %d seconds...", reconnect_delay)
            time.sleep(reconnect_delay)
            try:
                client.reconnect()
                print("Reconnected successfully!")
                return
            except Exception as err:
                print("%s. Reconnect failed. Retrying...", err)
            reconnect_delay *= RECONNECT_RATE
            reconnect_delay = min(reconnect_delay, MAX_RECONNECT_DELAY)
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
        self.mqtt_client.will_set(mqtt_topic_base, payload="Offline", qos=1, retain=True)

        print("connect_mqtt done")
        return self.mqtt_client


def current_milli_time():
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
    global globalbusy , last_timetamb_ms
    filepath = "/tmp/test.jpg"
    _now = current_milli_time()
    print("check duplicate now= ",_now , " , last="  ,last_timetamb_ms)
    if (globalbusy == True or ( _now < (last_timetamb_ms + 20 ))):
        print("StartImageCapture duplicate now= ",_now , " , last="  ,last_timetamb_ms, " global_busy= " , globalbusy)
        try:
            with open(filepath, 'rb') as jpeg_file:
                StreamingHandler.send_response(200)
                StreamingHandler.send_header('Content-Type', 'image/jpeg')
                StreamingHandler.send_header('Content-Length', os.path.getsize(filepath))
                StreamingHandler.end_headers()
                StreamingHandler.wfile.write(jpeg_file.read())
        except  Exception as exc:
            print(" capture erro jpeg_file exception %s ",str(exc))
    else:  
        try:
            print("StartImageCapture new capture ")
            globalbusy = True  
            sleep(1)
            picam2.stop()
            picam2.configure(picam2.create_still_configuration(main={"size": IMAGE_RESOLUTION}))
            picam2.set_controls(cnontrols)
            picam2.start()
            picam2.capture_file(filepath)
            with open(filepath, 'rb') as jpeg_file:
                StreamingHandler.send_response(200)
                StreamingHandler.send_header('Content-Type', 'image/jpeg')
                StreamingHandler.send_header('Content-Length', os.path.getsize(filepath))
                StreamingHandler.end_headers()
                StreamingHandler.wfile.write(jpeg_file.read())
            last_timetamb_ms = current_milli_time()
        except  Exception as exc:
            print(" capture erro exception %s ",str(exc))
        picam2.stop()
        globalbusy = False
    
        
def StartStream(StreamingHandler) :
    global globalbusy, ExitAllThread
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
    global motionValue , ExitAllThread , _mqtt_client , globalbusy
    lsize = (320, 240)
    started = False
    w, h = lsize
    prev = None
    checkLuxCounter = 0
    last_detcted = "0"
    detected = "0"
    print("started motion thread ") 
    while (ExitAllThread == False):
            if (globalbusy == False ):
                if (started == False):
                    try: 
                        print(" *********** start motion cam config ************") 
                        picam2.stop()
                        picam2.configure(picam2.create_video_configuration(main={"size": (1280, 720)}, lores={"size": lsize, "format": "YUV420"}))
                        picam2.start()
                        started = True
                    except: 
                        print("exception in motion" )
                        started = False
                        picam2.stop()
                cur = picam2.capture_buffer("lores")
                cur = cur[:w * h].reshape(h, w)
                if prev is not None:
                    temp_motionValue = np.square(np.subtract(cur, prev)).mean()
                    #
                    #print(" *********** motion =",temp_motionValue)
                    if (temp_motionValue > 10):
                        detection = "1"
                        if(motionValue < 20 ):
                            checkLuxCounter = checkLuxCounter + 25 
                            motionValue = motionValue+1
                            print(" *********** motion detected ",temp_motionValue , ", total = " , motionValue)
                            _mqtt_client.publish(mqtt_topic_motion,json.dumps({"motion" : motionValue}))
                    else:
                        detection = "0"
                        if(motionValue > 0):
                            motionValue = motionValue - 1
                            if(motionValue == 0):
                                _mqtt_client.publish(mqtt_topic_motion,json.dumps({"motion" : motionValue}))
                    if (last_detcted != detection):
                        last_detcted = detection
                        _mqtt_client.publish(mqtt_topic_motion_detection,json.dumps({"motion_Detction" :detection}))
                else :
                    cur = picam2.capture_buffer("lores")
                    cur = cur[:w * h].reshape(h, w)
                prev = cur
                sleep(0.2)
                checkLuxCounter = checkLuxCounter+ 1
                if (checkLuxCounter > 100):
                    try:
                        print("*********** stopping cam for LUX  measurement ********** ") 
                        checkLuxCounter = 0
                        picam2.stop()
                        started = False
                        picam2.configure(picam2.create_still_configuration(main={"size": IMAGE_RESOLUTION}))
                        picam2.set_controls(cnontrols)
                        picam2.start()
                        request = picam2.capture_request()
                        metadata = request.get_metadata()
                        request.release()
                        picam2.stop()
                        lux_value = int(metadata['Lux'])
                        print("lux=",lux_value,)
                        _mqtt_client.publish(mqtt_topic_lux,json.dumps({"lux" : lux_value}))
                    except Exception as exc:
                        print(" lux error exception %s ", str(exc))  
            elif (started):
                print("*********** stopping motion ********** ") 
                prev = None
                picam2.stop()
                started = False
            else :
                sleep(1)
    print("motion thread out ") 

def StartRecord(StreamingHandler) :
    global globalbusy,busyrecording,RecordHelperThread_event
    if (globalbusy == False ):
        try:
            globalbusy = True
            busyrecording = True 
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
        if (globalbusy == True):
            self.send_error(404)
            self.end_headers()
            print(' received request ',self.path ," DENIED , BUSY")
            return
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
                    HelperThread = threading.Thread(target = StartRecord(self) )
                    HelperThread.start()
                    sleep(3)
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
_mqtt_client.publish(mqtt_topic_motion_detection,json.dumps({"motion_Detction" :"0"}))
_mqtt_client.publish(mqtt_topic_motion,json.dumps({"motion" :"0"}))
_mqtt_client.publish(mqtt_topic_lux,json.dumps({"lux" :"0"}))
_mqtt_client.publish(mqtt_topic_base,"online")

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
_mqtt_client.publish(mqtt_topic_base,"offline")

    