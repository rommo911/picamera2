#!/usr/bin/python3
import RPi.GPIO as GPIO
import time
from paho.mqtt import client as mqtt_client
import json
# Set GPIO mode and PIR pin
GPIO.setmode(GPIO.BCM)
PIR_PIN = 21
GPIO.setup(PIR_PIN, GPIO.IN)

# Initialize MQTT client
import logging
from systemd import journal 

logger = logging.getLogger(__name__)
#logger.addHandler(journal.JournalHandler())
handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
# add the handler to the logger
logger.addHandler(handler)
logger.setLevel(logging.INFO)


mqtt_topic_base = "rpi_pir"
mqtt_topic_availability = mqtt_topic_base + "/status"
mqtt_topic_motion = mqtt_topic_base + "/motion"

class MQTT():
    def __init__(self):
        self.mqtt_broker = 'localhost'
        self.mqtt_port = 8883
        self.mqtt_client_id = "rpi_pi_sensor"
        self.username = 'rami'
        self.password = '5461'
        self.mqtt_client = mqtt_client.Client(self.mqtt_client_id)
        self.RECONNECT_RATE = 2
        self.MAX_RECONNECT_COUNT = 100
        self.reconnect_delay = 2
        self.MAX_RECONNECT_DELAY = 10
        self.DisconnectFlag = False
    def mqtt_on_connect(self , client, userdata, flags, rc):
        if rc == 0:
            logger.info("Connected to MQTT Broker!")
        else:
            logger.info("Failed to connect, return code %d\n", rc)

    def mqtt_on_disconnect(self ,client, userdata, rc):
        if (self.DisconnectFlag == True ):
            return
        print("Disconnected with result code: %s", rc)
        reconnect_count = 0
        while reconnect_count < self.MAX_RECONNECT_COUNT:
            logger.info("Reconnecting in %d seconds...", self.reconnect_delay)
            time.sleep(self.reconnect_delay)
            try:
                client.reconnect()
                logger.info("Reconnected successfully!")
                client.publish(mqtt_topic_availability,"online", retain=True)
                return
            except Exception as err:
                logger.error("%s. Reconnect failed. Retrying...", err)
            self.reconnect_delay *= self.RECONNECT_RATE
            self.reconnect_delay = min(self.reconnect_delay, self.MAX_RECONNECT_DELAY)
            reconnect_count += 1
        logger.info("Reconnect failed after %s attempts. Exiting...", reconnect_count)

    def connect_mqtt(self):
        logger.info("connect_mqtt")
        # Set Connecting Client ID
        self.mqtt_client = mqtt_client.Client(self.mqtt_client_id)
        self.mqtt_client.username_pw_set(self.username, self.password)
        self.mqtt_client.reconnect_delay_set(2)
        self.mqtt_client.on_connect = self.mqtt_on_connect
        self.mqtt_client.on_disconnect = self.mqtt_on_disconnect
        self.mqtt_client.connect(self.mqtt_broker, self.mqtt_port , 2 )
        #self.mqtt_client.will_set(mqtt_topic_availability, payload="offline", qos=1, retain=True)
        logger.info("connect_mqtt done")
        return self.mqtt_client

    
MqttClass =  MQTT()
_mqtt_client = MqttClass.connect_mqtt()
ExitAllThread = False
globalbusy = False
_mqtt_client.publish(mqtt_topic_motion,json.dumps({"motion" :"off"}))
_mqtt_client.publish(mqtt_topic_availability,"online", retain=True)



# Callback when PIR sensor detects motion
def motion_detected(channel):
    global _mqtt_client 
    if GPIO.input(PIR_PIN):
        print("Motion Detected!")
        _mqtt_client.publish(mqtt_topic_motion,json.dumps({"motion" :"on"}))
    else : 
        print("Motion NOT Detected!")
        _mqtt_client.publish(mqtt_topic_motion,json.dumps({"motion" :"off"}))


# Set up GPIO event detection
GPIO.add_event_detect(PIR_PIN, GPIO.BOTH, callback=motion_detected)

try:
    print("PIR Sensor Monitoring...")

    # Main loop
    while True:
        _mqtt_client.loop_forever()
        print("ping loop ")

except KeyboardInterrupt:
    print("Program terminated by user.")
    GPIO.cleanup()
    MqttClass.DisconnectFlag = True
    _mqtt_client.publish(mqtt_topic_availability,"offline", retain=True)
    _mqtt_client.disconnect()
