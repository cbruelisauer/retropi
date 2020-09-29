import time
import sys
import subprocess
import signal
import os
import RPi.GPIO as GPIO
GPIO.setmode(GPIO.BCM)


import Adafruit_MCP3008



#Pin definitions
Power_Pin = 26
InetRadio_Pin = 13
DAB_Pin = 12
BLE_Pin = 16

#LED pins
PWR_LED_Pin = 5
STATUS_LED_Pin = 6

#MCP3008
GPIO_CLK = 17
GPIO_MISO = 23
GPIO_MOSI = 24
GPIO_CS = 25

MCP3008_CHANNEL = 1

#setup the input pins
GPIO.setup(Power_Pin,GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(InetRadio_Pin,GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(DAB_Pin,GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(BLE_Pin,GPIO.IN, pull_up_down=GPIO.PUD_UP)



#callback functions for pin interrupt
#callback for on/off key
def power_callback(Power_Pin):
    print "Power pin pressed"
   # os.system("mpc stop")
   # os.system("sudo systemctl stop bt_speaker")
   # os.system("sudo systemctl stop bluetooth")



#callback for internet radio key
def inet_callback(InetRadio_Pin):
    print "Internet Radio Pin pressed"
    # os.system("mpc play") #start playing mpc
    
    #stop bluetooth
   # os.system("sudo systemctl stop bt_speaker")
   # os.system("sudo systemctl stop bluetooth")



#callback for dab key
def dab_callback(DAB_Pin):
    print "DAB Pin pressed"
    
    #stop other services
   # os.system("mpc stop")
   # os.system("sudo systemctl stop bt_speaker")
   # os.system("sudo systemctl stop bluetooth")



#callback for bluetooth key
def ble_callback(BLE_Pin):
    print "BL Pin pressed"
    
    #stop other services
   # os.system("mpc stop")
    
    #start ble service
   # os.system("sudo systemctl start bluetooth")
   # subprocess.call('/home/pi/bl_start', shell=True)
   # os.system("sudo systemctl start bt_speaker")
   


#setup event from gpio
GPIO.add_event_detect(Power_Pin, GPIO.FALLING, callback=power_callback, bouncetime=1500)
GPIO.add_event_detect(InetRadio_Pin, GPIO.FALLING, callback=inet_callback, bouncetime=1500)
GPIO.add_event_detect(DAB_Pin, GPIO.FALLING, callback=dab_callback, bouncetime=1500)
GPIO.add_event_detect(BLE_Pin, GPIO.FALLING, callback=ble_callback, bouncetime=1500)



class RotaryEncoder(object):
      def __init__(self, gpio_CLK, gpio_CS, gpio_MISO, gpio_MOSI, channel, tolerance = 5):
          self.mcp = Adafruit_MCP3008.MCP3008(clk=gpio_CLK, cs=gpio_CS, miso=gpio_MISO, mosi=gpio_MOSI)
          self.channel = channel
          
          self.tolerance = tolerance
          self.last_read = 0

      def destroy(self):
          print "nooooo"

      def read(self):
          trim_pot_changed = False
          trim_pot = self.mcp.read_adc(self.channel)
          pot_adjust = abs(trim_pot-self.last_read)

          if pot_adjust > self.tolerance:
             trim_pot_changed = True

          if trim_pot_changed:
             station = int(round(trim_pot / 51.2))
             set_station(station)

             self.last_read = trim_pot


def set_station(station_mcp):
    temp_str1 = str(station_mcp)
    temp_str2 = "mpc play "
    comp_str = temp_str2 + temp_str1
    os.system(comp_str)







if __name__ == "__main__":
   def on_exit(a, b):
       encoder.destroy()
       GPIO.cleanup()
       os.system("sudo systemctl stop bluetooth")
       os.system("sudo systemctl stop bt_speaker")
       os.system("mpc stop")
       sys.exit(0)
   
   #stop the bt_speaker service
   os.system("sudo systemctl stop bluetooth")
   os.system("sudo systemctl stop bt_speaker")
  
   encoder = RotaryEncoder(GPIO_CLK, GPIO_CS, GPIO_MISO, GPIO_MOSI, MCP3008_CHANNEL)
   signal.signal(signal.SIGINT, on_exit)


   while True:
         if not GPIO.input(InetRadio_Pin):
            encoder.read()
        # if not GPIO.input(DAB_Pin):
         #   print "blabla"
        # if not GPIO.input(BLE_Pin):
          #  print "hololo"
         time.sleep(0.1)
          
