# Using a rotary encoder as a volume control

This describes how to use a potentiometer with a MCP3008 chip.

## Hardware

Potentiometer from Ebay: http://www.ebay.com/itm/10PCS-6mm-3pin-Knurled-Shaft-Single-Linear-B-Type-B10K-ohm-Rotary-Potentiometer-/222445944546

MCP3008 from Adafruit: https://www.adafruit.com/products/856

Connecting the MCP3008: https://learn.adafruit.com/raspberry-pi-analog-to-digital-converters/mcp3008

## Volume daemon

Since the GPIO pins are just for arbitrary signals, you need a script on the Pi that knows what to do with them. The builtin GPIO library for the Pi will do nicely for this.
 
We increase or decrease the system volume using the command-line program `amixer`.

First, make sure `amixer` is present and install it if it isn’t.

```sh
which amixer || sudo apt-get install alsa-utils
```

Also install Adafruit Python MCP3008:

```sh
pip install adafruit-mcp3008
```

Create a `bin` directory in your `pi` folder if it doesn't exist already, then drop the script below into it.

```
mkdir ~/bin
```

If it's not there yet, I'd also put `/home/pi/bin` somewhere in your `PATH`:

```
echo $PATH
# don't see "/home/pi/bin" there? then run...
echo "export PATH=$HOME/bin:$PATH" >> ~/.bashrc
# ...and restart your shell
```

Then drop the script into the `/home/pi/bin` folder:

```
nano ~/bin/monitor-volume # (or however you do it)
chmod +x ~/bin/monitor-volume
```

You can run this script in the foreground just to test it out. Edit the script and temporarily change `DEBUG` to `True` so that you can see what's going on, then simply run it with `monitor-volume`. When you turn the knob, the script should report what it's doing.

You should also play around with the constants defined at the top of the script. Naturally, if you picked other pins, you'll want to tell the script which GPIO pins to use. You may also want to change the minimum and maximum volumes (they're percentages, so they should be between 1 and 100) and the increment (how many percentage points the volume increases/decreases with each "click" of the knob).

If it's working the way you want, you can proceed to the next step: running `monitor-volume` automatically in the background whenever your Pi starts.

## Creating a systemd service

_NOTE: If you're on a version of Raspbian before Jessie, these instructions won't work for you. Hopefully someone can pipe up with a version of this for `init.d` in the comments._

`systemd` is the new way of managing startup daemons in Raspbian Jessie. Because it's new, there's not much RPi-specific documentation on it, and to find out how to use it you have to sift through a bunch of Google results from people who hate `systemd` and wish it didn't exist. After much trial and error, here's what worked for me:

```
nano ~/monitor-volume.service
# paste in the contents of monitor-volume.service, save/exit nano
chmod +x ~/monitor-volume.service
sudo mv ~/monitor-volume.service /etc/systemd/system
sudo systemctl enable monitor-volume
sudo systemctl start monitor-volume
```

If that worked right, then you just told Raspbian to start up that script in the background on every boot (`enable`), and also to start it right now (`start`). At this point, and on every boot after this, your volume knob should Just Work.

##  FAQ

**This didn't work!**

I got this working on an RPi3 running RetroPie 3.x, so all I can say is “works on my machine.” Some things to try:

* You might not have Python 3; if `which python3` turns up nothing, try this:

  ```
  sudo apt-get install python3
  ```
* I've heard that in earlier versions of Raspbian, the `pi` user isn't automatically allowed to access the GPIO pins, so you need to run scripts like this as root.  If you're running into permissions errors when you try to run the script from your shell, then that's your problem, most likely. There's no particular reason why you _shouldn't_ run this script as root, except on the general principle that you shouldn't really trust code that you didn't write. Make good choices and have backups.
* I might have made a typo in the gist. Wouldn't be the first time.

If you run into trouble, leave a comment and the internet can help you figure it out.