#!/usr/bin/python3

# This is the same as mjpeg_server.py, but uses the h/w MJPEG encoder.

import io
import logging
import socketserver
from http import server
from threading import Condition
import os

from picamera2 import Picamera2 , Preview
from picamera2.encoders import MJPEGEncoder
from picamera2.outputs import FileOutput
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

class StreamingHandler(server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(301)
            self.send_header('Location', '/index.html')
            self.end_headers()
        elif self.path == '/index.html':
            content = PAGE.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Content-Length', len(content))
            self.end_headers()
            self.wfile.write(content)
        elif self.path == '/still.html':
            picam2.configure(picam2.create_still_configuration(main={"size": (1280, 720)}))
            picam2.start()
            picam2.capture_file("test.jpg")
            with open("test.jpg", 'rb') as jpeg_file:
                self.send_response(200)
                self.send_header('Content-Type', 'image/jpeg')
                self.send_header('Content-Length', os.path.getsize("test.jpg"))
                self.end_headers()
                self.wfile.write(jpeg_file.read())
            picam2.stop()
        elif self.path == '/stream.mjpg':
            picam2.configure(picam2.create_video_configuration(main={"size": (1280, 720)}))
            mjpegencoder = MJPEGEncoder()
            output = StreamingOutput()
            StreamFile_output = FileOutput(output)
            picam2.start_recording(mjpegencoder,StreamFile_output)
            self.send_response(200)
            self.send_header('Age', 0)
            self.send_header('Cache-Control', 'no-cache, private')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=FRAME')
            self.end_headers()
            try:
                while True:
                    with output.condition:
                        output.condition.wait()
                        frame = output.frame
                    self.wfile.write(b'--FRAME\r\n')
                    self.send_header('Content-Type', 'image/jpeg')
                    self.send_header('Content-Length', len(frame))
                    self.end_headers()
                    self.wfile.write(frame)
                    self.wfile.write(b'\r\n')
            except Exception as e:
                logging.warning(
                    'Removed streaming client %s: %s',
                    self.client_address, str(e))
                picam2.stop_recording()
        else:
            self.send_error(404)
            self.end_headers()
        picam2.stop()


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