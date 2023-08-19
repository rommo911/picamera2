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
from picamera2 import Picamera2 , Preview
from picamera2.encoders import MJPEGEncoder
from picamera2.outputs import FileOutput
from picamera2.encoders import H264Encoder
from picamera2.outputs import FfmpegOutput
import time

PAGE = """\
<html>
<head>
<title>picamera2 MJPEG streaming demo</title>
</head>
<body>
<h1>Picamera2 MJPEG Streaming Demo</h1>
<img src="stream.mjpg" width="1280" height="720" />
</body>
</html>
"""


class StreamingOutput(io.BufferedIOBase):
    def __init__(self):
        self.frame = None
        self.condition = Condition()

    def write(self, buf):
        with self.condition:
            self.frame = buf
            self.condition.notify_all()

picam2 = Picamera2()
globalbusy = False
busyrecording = False
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
    global globalbusy
    if (globalbusy == True):
        print ('avoiding double demandes :  ! ! !')
        with open("/tmp/test.jpg", 'rb') as jpeg_file:
            StreamingHandler.send_response(200)
            StreamingHandler.send_header('Content-Type', 'image/jpeg')
            StreamingHandler.send_header('Content-Length', os.path.getsize("test.jpg"))
            StreamingHandler.end_headers()
            StreamingHandler.wfile.write(jpeg_file.read())
    else:              
        globalbusy = True
        picam2.configure(picam2.create_still_configuration(main={"size": (1280, 720)}))
        picam2.start()
        picam2.capture_file("/tmp/test.jpg")
        with open("/tmp/test.jpg", 'rb') as jpeg_file:
            StreamingHandler.send_response(200)
            StreamingHandler.send_header('Content-Type', 'image/jpeg')
            StreamingHandler.send_header('Content-Length', os.path.getsize("test.jpg"))
            StreamingHandler.end_headers()
            StreamingHandler.wfile.write(jpeg_file.read())
            picam2.stop()
        globalbusy = False
        
def StartStream(StreamingHandler) :
    global globalbusy
    globalbusy= True
    picam2.configure(picam2.create_video_configuration(main={"size": (1280, 720)}))
    mjpegencoder = MJPEGEncoder()
    output = StreamingOutput()
    StreamFile_output = FileOutput(output)
    picam2.start_recording(mjpegencoder,StreamFile_output)
    StreamingHandler.send_response(200)
    StreamingHandler.send_header('Age', 0)
    StreamingHandler.send_header('Cache-Control', 'no-cache, private')
    StreamingHandler.send_header('Pragma', 'no-cache')
    StreamingHandler.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=FRAME')
    StreamingHandler.end_headers()
    try:
        while True:
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
    picam2.stop_recording()
    picam2.stop()
    globalbusy = False

RecordHelperThread = threading.Thread()
RecordHelperThread_event = threading.Event()

def StartRecord(StreamingHandler) :
    global globalbusy,busyrecording,RecordHelperThread_event
    if (globalbusy == False and busyrecording == False ):
        globalbusy = True
        busyrecording = True 
        video_config = picam2.create_video_configuration()
        picam2.configure(video_config)
        h264_encoder = H264Encoder(800000, framerate=24)
        currentTime = time.strftime("%Y%m%d-%H-%M-%S")
        filename1 = '/tmp/record_' + currentTime + '.mp4'
        Ffmpeg_output = FfmpegOutput(filename1, audio=False)
        picam2.start_recording(h264_encoder, Ffmpeg_output)
        SendOK(StreamingHandler)
        RecordHelperThread_event.clear()
        print(" started recording ")
        RecordHelperThread_event.wait(timeout=600)
        #sleep(2)
        print("stopping recording ")
        picam2.stop_recording()
        picam2.stop()
        print("stoppped recording ")
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
        print(' *** GOT asked  %s',self.path )
        if self.path == '/':
            self.send_response(301)
            self.send_header('Location', '/still.html')
            self.end_headers()
        elif self.path == '/index.html':
            print('*** ')
            self.send_error(404)
            self.end_headers()
        elif (self.path == '/still.html' or  self.path == '/still.jpg'):
            StartImageCapture(self)
        elif self.path == '/stream.mjpg' and  globalbusy == False :
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
            print('*** ')
            self.send_error(404)
            self.end_headers()
        


class StreamingServer(socketserver.ThreadingMixIn, server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True

try:
    address = ('', 8000)
    server = StreamingServer(address, StreamingHandler)
    print("Server started at http://localhost:8000")
    server.serve_forever()
except KeyboardInterrupt:
    server.shutdown()
    print("Server stopped.")