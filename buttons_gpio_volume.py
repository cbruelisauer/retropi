import datetime
import time
import sys
import subprocess
import signal
import os
import RPi.GPIO as GPIO
GPIO.setmode(GPIO.BCM)


import Adafruit_MCP3008


print("************************************")
print("*     My Retro Radio by Cornel     *")
print("************************************")


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
MCP3008_VOLUME = 0

#Volume Definitions
VOLUME_MIN = 15
VOLUME_MAX = 50

VOLUME_INCREMENT = 1

DEVICE_NAME = 'Master'

#setup the input pins
GPIO.setup(Power_Pin,GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(InetRadio_Pin,GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(DAB_Pin,GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(BLE_Pin,GPIO.IN, pull_up_down=GPIO.PUD_UP)


#variables
inet_first_pressed = False
power_first_pressed = False
dab_first_pressed = False
ble_first_pressed = False

#variables for alarm
alarm_time = time.strptime("06.55.00", "%H.%M.%S")
alarm_started = False

class RotaryEncoder_channel(object):
      def __init__(self, gpio_CLK, gpio_CS, gpio_MISO, gpio_MOSI, channel, tolerance = 7):
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

class RotaryEncoder_DAB(object):
    def __init__(self, gpio_CLK, gpio_CS, gpio_MISO, gpio_MOSI, channel, tolerance=10):
        self.mcp = Adafruit_MCP3008.MCP3008(clk=gpio_CLK, cs=gpio_CS, miso=gpio_MISO, mosi=gpio_MOSI)
        self.channel = channel
        
        self.tolerance = tolerance
        self.last_read = 0

    def destroy(self):
       print "kaka"

    def read(self):
        trim_pot_changed = False
        trim_pot = self.mcp.read_adc(self.channel)
        pot_adjust = abs(trim_pot-self.last_read)

        if pot_adjust > self.tolerance:
           trim_pot_changed = True

        if trim_pot_changed:
           os.system('\n')

class RotaryEncoder_volume(object):
    def __init__(self, gpio_CLK, gpio_CS, gpio_MISO, gpio_MOSI, channel, tolerance=5):
       self.mcp = Adafruit_MCP3008.MCP3008(clk=gpio_CLK, cs=gpio_CS, miso=gpio_MISO, mosi=gpio_MOSI)
       self.volume = Volume()
       self.channel = channel

       self.tolerance = tolerance
       self.last_read = 0

    def destroy(self):
        print "not me too"
        self.volume.set_volume(0)

    def read(self):
        trim_pot_changed = False
        trim_pot = self.mcp.read_adc(self.channel)
        pot_adjust = abs(trim_pot - self.last_read)
        
        if pot_adjust > self.tolerance:
           trim_pot_changed = True

        if trim_pot_changed:
           set_volume = int(round(trim_pot / 10.24))
           self.volume.set_volume(set_volume)

           self.last_read = trim_pot


class VolumeError(Exception):
      pass

class Volume(object):

      MIN = VOLUME_MIN
      MAX = VOLUME_MAX
      INCREMENT = VOLUME_INCREMENT

      def __init__(self):
          self.last_volume = self.MIN
          self._sync()

      def up(self):
          return self.change(self.INCREMENT)

      def down(self):
          return self.change(-self.INCREMENT)

      def change(self, delta):
          v = self.volume + delta
          v = self._constrain(v)
          return self.set_volume(v)

      def set_volume(self, v):
          self.volume = self._constrain(v)
          output = self.amixer("set '{}' unmute {}%".format(DEVICE_NAME, v))
          self._sync(output)
          return self.volume

      def toggle(self):
          if self.is_muted:
               output = self.amixer("set '{}' unmute".format(DEVICE_NAME))
          else:
               self.last_volume = self.volume
               output = self.amixer("set '{}' mute".format(DEVICE_NAME))

          self._sync(output)
          if not self.is_muted:
                 self.set_volume(self.last_volume)
          return self.is_muted

      def status(self):
           if self.is_muted:
              return "{}% (muted)".format(self.volume)
           return "{}%".format(self.volume)

      def _sync(self, output = None):
           if output is None:
               output = self.amixer("get '{}'".format(DEVICE_NAME))

           lines = output.readlines()
           last = lines[-1].decode('utf-8')

           i1 = last.rindex('[') + 1
           i2 = last.rindex(']')

           self.is_muted = last[i1:i2] == 'off'

           i1 = last.index('[') + 1
           i2 = last.index('%')
           pct = last[i1:i2]

           self.volume = int(pct)


      def _constrain(self, v):
            if v < self.MIN:
               return self.MIN
            if v > self.MAX:
               return self.MAX
            return v


      def amixer(self, cmd):
            p = subprocess.Popen("amixer {}".format(cmd), shell=True, stdout=subprocess.PIPE)
            code = p.wait()
            if code != 0:
               raise VolumeError("Unknown error: {}".format(code))
               sys.exit(0)
            return p.stdout


def comp_time():
    current_time = time.localtime(time.time())
    start_alarm = False
    if (current_time.tm_hour == alarm_time.tm_hour and current_time.tm_min == alarm_time.tm_min):
       start_alarm = True
    return start_alarm   




if __name__ == "__main__":
   def on_exit(a, b):
       os.system("amixer sset Master 0%")
       encoder_channel.destroy()
       encoder_volume.destroy()
       GPIO.cleanup()
       os.system("sudo systemctl stop bluetooth")
       os.system("sudo systemctl stop bt_speaker")
       os.system("mpc stop")
       sys.exit(0)
   
   #stop the bt_speaker service
   os.system("sudo systemctl stop bluetooth")
   os.system("sudo systemctl stop bt_speaker")
  
   #setup potentiometers
   encoder_channel = RotaryEncoder_channel(GPIO_CLK, GPIO_CS, GPIO_MISO, GPIO_MOSI, MCP3008_CHANNEL)
   encoder_volume = RotaryEncoder_volume(GPIO_CLK, GPIO_CS, GPIO_MISO, GPIO_MOSI, MCP3008_VOLUME)
   signal.signal(signal.SIGINT, on_exit)
   os.system("amixer sset Master 60%")
   os.system("mplayer /home/pi/connect_sound.wav")
   

   while True:
         if GPIO.input(InetRadio_Pin):
            if not inet_first_pressed:
               print "Internet Radio Pin pressed"

               os.system("sudo systemctl stop bt_speaker")
               os.system("sudo systemctl stop  bluetooth")
               os.system("sudo ifconfig wlan0 up")

               os.system("mpc play")
               inet_first_pressed = True
               power_first_pressed = False
               dab_first_pressed = False
               ble_first_pressed = False

            encoder_channel.read()
            time.sleep(0.05)
            encoder_volume.read()
            time.sleep(0.05)

         if not GPIO.input(Power_Pin):
            if not power_first_pressed:
               print "Power Pin Pressed"
               os.system("mpc stop")
               os.system("sudo systemctl stop bt_speaker")
               os.system("sudo systemctl stop bluetooth")
               os.system("sudo ifconfig wlan0 up")
               inet_first_pressed = False
               dab_first_pressed = False
               power_first_pressed = True
               ble_first_pressed = False
              
            if (comp_time() and alarm_started == False):
               alarm_started = True
               os.system("mpc play")

            time.sleep(0.5)


                       
         if not GPIO.input(DAB_Pin):
            if not dab_first_pressed:
               print "DAB Pin Pressed"
               
               os.system("mpc stop")
               os.system("sudo systemctl stop bt_speaker")
               os.system("sudo systemctl stop bluetooth")
               os.system("sudo ifconfig wlan0 up")

               inet_first_pressed = False
               power_first_pressed = False
               ble_first_pressed = False
               dab_first_pressed = True    

            encoder_volume.read()
            time.sleep(0.1)
    
         
         if not GPIO.input(BLE_Pin):
             if not ble_first_pressed:
                print "BLE Pin Pressed"

                os.system("mpc stop")
                os.system("sudo ifconfig wlan0 down")
                os.system("sudo systemctl start bluetooth")
                subprocess.call('/home/pi/bl_start', shell=True)
                os.system("sudo systemctl start bt_speaker")

                inet_first_pressed = False
                power_first_pressed = False
                ble_first_pressed = True
                dab_first_pressed = False

             encoder_volume.read()
             time.sleep(0.1)
