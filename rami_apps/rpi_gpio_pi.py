#!/usr/bin/python3
import RPi.GPIO as GPIO
import time
from paho.mqtt import client as mqtt_client
import json
# Set GPIO mode and PIR pin
GPIO.setmode(GPIO.BCM)
PIR_PIN = 18
GPIO.setup(PIR_PIN, GPIO.IN)

# Initialize MQTT client

mqtt_topic_base = "rpi_pir"
mqtt_topic_availability = mqtt_topic_base + "/status"
mqtt_topic_motion = mqtt_topic_base + "/motion"

class MQTT():
    def __init__(self):
        self.mqtt_broker = '127.0.0.1'
        self.mqtt_port = 8883
        self.mqtt_client_id = "rpi_pir_sensor"
        self.username = 'rami'
        self.password = '5461'
        self.mqtt_client = mqtt_client.Client(self.mqtt_client_id)
        self.RECONNECT_RATE = 1.1
        self.MAX_RECONNECT_COUNT = 5
        self.MAX_RECONNECT_DELAY = 15
        self.reconnect_delay = 2
        self.disconnectFalg = False
    def mqtt_on_connect(self, client, userdata, flags, rc):
        print("Connected to MQTT Broker YAAAAAAAAAAAAAAAAAY!")
        if rc == 0:
            print("Connected to MQTT Broker YAAAAAAAAAAAAAAAAAY!")
        else:
            print("Failed to connect, return code %d\n", rc)

    def mqtt_on_disconnect(self ,client, userdata, rc):
        if (self.disconnectFalg):
            return
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
    
MqttClass =  MQTT()
_mqtt_client = MqttClass.connect_mqtt()
ExitAllThread = False
globalbusy = False
_mqtt_client.publish(mqtt_topic_motion,json.dumps({"motion" :"0"}))
_mqtt_client.publish(mqtt_topic_availability,"online", retain=True)



# Callback when PIR sensor detects motion
def motion_detected(channel):
    global _mqtt_client 
    if GPIO.input(PIR_PIN):
        print("Motion Detected!")
        _mqtt_client.publish(mqtt_topic_motion,json.dumps({"motion" :"1"}))
    else : 
        _mqtt_client.publish(mqtt_topic_motion,json.dumps({"motion" :"0"}))


# Set up GPIO event detection
GPIO.add_event_detect(PIR_PIN, GPIO.BOTH, callback=motion_detected)

try:
    print("PIR Sensor Monitoring...")

    # Main loop
    while True:
        time.sleep(1)

except KeyboardInterrupt:
    print("Program terminated by user.")
    GPIO.cleanup()
    MqttClass.disconnectFalg = True
    _mqtt_client.publish(mqtt_topic_availability,"offline", retain=True)
    _mqtt_client.disconnect()
