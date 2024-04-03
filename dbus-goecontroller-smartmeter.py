#!/usr/bin/env python
# vim: ts=2 sw=2 et

# import normal packages
import platform 
import logging
import logging.handlers
import sys
import os
import sys
if sys.version_info.major == 2:
    import gobject
else:
    from gi.repository import GLib as gobject
import sys
import time
import requests # for http GET
import configparser # for config/ini file
 
# our own packages from victron
sys.path.insert(1, os.path.join(os.path.dirname(__file__), '/opt/victronenergy/dbus-systemcalc-py/ext/velib_python'))
from vedbus import VeDbusService

class DbusGoeControllerService:
  def __init__(self, paths, productname='go-eController', connection='go-eController HTTP JSON service'):
    config = self._getConfig()
    deviceinstance = int(config['DEFAULT']['DeviceInstance'])
    customname = config['DEFAULT']['CustomName']
    serial = config['ONPREMISE']['Serial']
    role = 'grid'
    servicename = 'com.victronenergy.' + role

    self._dbusservice = VeDbusService("{}.http_{:02d}".format(servicename, deviceinstance))
    self._paths = paths
 
    logging.debug("%s /DeviceInstance = %d" % (servicename, deviceinstance))
 
    # Create the management objects, as specified in the ccgx dbus-api document
    self._dbusservice.add_path('/Mgmt/ProcessName', __file__)
    self._dbusservice.add_path('/Mgmt/ProcessVersion', 'Unkown version, and running on Python ' + platform.python_version())
    self._dbusservice.add_path('/Mgmt/Connection', connection)
 
    # Create the mandatory objects
    self._dbusservice.add_path('/DeviceInstance', deviceinstance)
    self._dbusservice.add_path('/ProductId', 0xFFFF)
    self._dbusservice.add_path('/DeviceType', 345) # found on https://www.sascha-curth.de/projekte/005_Color_Control_GX.html#experiment - should be an ET340 Engerie Meter
    self._dbusservice.add_path('/ProductName', productname)
    self._dbusservice.add_path('/CustomName', customname)
    self._dbusservice.add_path('/Latency', None)
    self._dbusservice.add_path('/FirmwareVersion', "1.0") # http://192.168.3.216/api/status?filter=fwv
    self._dbusservice.add_path('/HardwareVersion', '')
    self._dbusservice.add_path('/Connected', 1)
    self._dbusservice.add_path('/Role', role)
    self._dbusservice.add_path('/Serial', serial)
    self._dbusservice.add_path('/UpdateIndex', 0)
 
    # add path values to dbus
    for path, settings in self._paths.items():
      self._dbusservice.add_path(
        path, settings['initial'], gettextcallback=settings['textformat'], writeable=True, onchangecallback=self._handlechangedvalue)
 
    # last update
    self._lastUpdate = 0
 
    # add _update function 'timer'
    gobject.timeout_add(500, self._update) # pause 500ms before the next request
    
    # add _signOfLife 'timer' to get feedback in log every 5minutes
    gobject.timeout_add(self._getSignOfLifeInterval()*60*1000, self._signOfLife)
 
  def _getConfig(self):
    config = configparser.ConfigParser()
    config.read("%s/config.ini" % (os.path.dirname(os.path.realpath(__file__))))
    return config;
 
 
  def _getSignOfLifeInterval(self):
    config = self._getConfig()
    value = config['DEFAULT']['SignOfLifeLog']
    
    if not value: 
        value = 0
    
    return int(value)

 
  def _getControllerData(self):
    config = self._getConfig()

    # local HTTP API V2    
    URL = "http://0%s@%s/api/status?filter=ccp,isv,usv,cec,cpc" % (config['ONPREMISE']['Serial'], config['ONPREMISE']['Host'])
    #URL = URL.replace(":@", "")

    meter_r = requests.get(url = URL, timeout=5)
    
    # check for response
    if not meter_r:
        raise ConnectionError("No response from Controller - %s" % (URL))
    
    meter_data = meter_r.json()
    
    # check for Json
    if not meter_data:
        raise ValueError("Converting response to JSON failed")
    
    
    return meter_data
 
 
  def _signOfLife(self):
    logging.info("--- Start: sign of life ---")
    logging.info("Last _update() call: %s" % (self._lastUpdate))
    logging.info("Last '/Ac/Power': %s" % (self._dbusservice['/Ac/Power']))
    logging.info("--- End: sign of life ---")
    return True
 
  def _update(self):   
    try:
      #get data from Controller
      meter_data = self._getControllerData()

      config = self._getConfig()
     
      # https://github.com/victronenergy/venus/wiki/dbus#grid-and-genset-meter
      # http://192.168.3.216/api/status?filter=ccp,isv,usv,cec

      #CCP - controller category powers
      #0 "Home"
      #1 "Grid"
      #2 "Car"
      #3 "Relais"
      #4 "Solar"
      #5 "Akku"
      #..
      #15 "Custom 10"

      #ISV - current sensor values (use isn for sensors names), ratio of W to VA is known as the Power Factor f
      #0[i,p,f] "Internal 1"
      #1[i,p,f] "Internal 2"
      #2[i,p,f] "Internal 3"
      #3[i,p,f] "Internal 4"
      #4[i,p,f] "Internal 5"
      #5[i,p,f] "Internal 6"

      #CEC - controller energy counters [in,out]
      #0[0,1]  "Home"
      #1[0,1]  "Grid"
      #2[0,1]  "Car"
      #3[0,1]  "Relais"
      #4[0,1]  "Solar"
      #5[0,1]  "Akku"
      #6[0,1]  "HP-Comp"
      #..
      #15[0,1] "Custom 10"

      #CPC - controller category phase currents	
      #0[0,1,2,3] "Home"	
      #1[0,1,2,3] "Grid" <
      #2[0,1,2,3] "Car"	 
      #3[0,1,2,3] "Relais"	
      #4[0,1,2,3] "Solar"	
      #5[0,1,2,3] "Akku"	
      #..
      #15[0,1,2,3]

      #USV - voltage sensor values
      #0[u1,u2,u3,uN] <

      #CCF - Controller category factors
      #IPS - current phase selections
      #IIM - invert current measurement
	
      #send data to DBus
      #https://github.com/victronenergy/venus/wiki/dbus#grid-and-genset-meter
      #https://github.com/supermihi/goe

      # controller category phase currents
      grid_L1_i = meter_data['cpc'][1][0] 
      grid_L2_i = meter_data['cpc'][1][1] 
      grid_L3_i = meter_data['cpc'][1][2] 

      grid_L1_u = meter_data['usv'][0]['u1'] 
      grid_L2_u = meter_data['usv'][0]['u2'] 
      grid_L3_u = meter_data['usv'][0]['u3'] 

      grid_L1_p = meter_data['isv'][0]['p'] 
      grid_L2_p = meter_data['isv'][1]['p'] 
      grid_L3_p = meter_data['isv'][2]['p'] 

      self._dbusservice['/Ac/L1/Power'] = grid_L1_p # W, real power (wirkleistung) 
      self._dbusservice['/Ac/L2/Power'] = grid_L2_p # W, real power (wirkleistung) 
      self._dbusservice['/Ac/L3/Power'] = grid_L3_p # W, real power (wirkleistung)
      self._dbusservice['/Ac/Power'] = grid_L1_p +   grid_L2_p +  grid_L3_p
      #self._dbusservice['/Ac/Power'] = meter_data['ccp'][1] # W - total of all phases, real power

      self._dbusservice['/Ac/L1/Voltage'] = grid_L1_u # V AC
      self._dbusservice['/Ac/L2/Voltage'] = grid_L2_u # V AC
      self._dbusservice['/Ac/L3/Voltage'] = grid_L3_u # V AC

      self._dbusservice['/Ac/L1/Current'] = grid_L1_i # A AC
      self._dbusservice['/Ac/L2/Current'] = grid_L2_i # A AC
      self._dbusservice['/Ac/L3/Current'] = grid_L3_i # A AC

      self._dbusservice['/Ac/Energy/Forward'] = (meter_data['cec'][1][0]/1000) # kWh - bought - IN
      self._dbusservice['/Ac/Energy/Reverse'] = (meter_data['cec'][1][1]/1000) # kWh - sold - OUT
      
      #logging
      logging.debug("House Consumption (/Ac/Power): %s" % (self._dbusservice['/Ac/Power']))
      logging.debug("House Forward (/Ac/Energy/Forward): %s" % (self._dbusservice['/Ac/Energy/Forward']))
      logging.debug("House Reverse (/Ac/Energy/Revers): %s" % (self._dbusservice['/Ac/Energy/Reverse']))
      logging.debug("---");
      
      # increment UpdateIndex - to show that new data is available an wrap
      self._dbusservice['/UpdateIndex'] = (self._dbusservice['/UpdateIndex'] + 1 ) % 256

      #update lastupdate vars
      self._lastUpdate = time.time()
    except (ValueError, requests.exceptions.ConnectionError, requests.exceptions.Timeout, ConnectionError) as e:
       logging.critical('Error getting data from Controller - check network or Controller status. Setting power values to 0. Details: %s', e, exc_info=e)       
       self._dbusservice['/Ac/L1/Power'] = 0                                       
       self._dbusservice['/Ac/L2/Power'] = 0                                       
       self._dbusservice['/Ac/L3/Power'] = 0
       self._dbusservice['/Ac/Power'] = 0
       self._dbusservice['/UpdateIndex'] = (self._dbusservice['/UpdateIndex'] + 1 ) % 256        
    except Exception as e:
       logging.critical('Error at %s', '_update', exc_info=e)
       
    # return true, otherwise add_timeout will be removed from GObject - see docs http://library.isr.ist.utl.pt/docs/pygtk2reference/gobject-functions.html#function-gobject--timeout-add
    return True
 
  def _handlechangedvalue(self, path, value):
    logging.debug("someone else updated %s to %s" % (path, value))
    return True # accept the change


def getLogLevel():
  config = configparser.ConfigParser()
  config.read("%s/config.ini" % (os.path.dirname(os.path.realpath(__file__))))
  logLevelString = config['DEFAULT']['LogLevel']
  
  if logLevelString:
    level = logging.getLevelName(logLevelString)
  else:
    level = logging.INFO
    
  return level


def main():
  #configure logging
  logging.basicConfig(      format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s',
                            datefmt='%Y-%m-%d %H:%M:%S',
                            level=getLogLevel(),
                            handlers=[
                                logging.FileHandler("%s/current.log" % (os.path.dirname(os.path.realpath(__file__)))),
                                logging.StreamHandler()
                            ])
 
  try:
      logging.info("Start");
  
      from dbus.mainloop.glib import DBusGMainLoop
      # Have a mainloop, so we can send/receive asynchronous calls to and from dbus
      DBusGMainLoop(set_as_default=True)
     
      #formatting 
      _kwh = lambda p, v: (str(round(v, 2)) + ' kWh')
      _a = lambda p, v: (str(round(v, 1)) + ' A')
      _w = lambda p, v: (str(round(v, 1)) + ' W')
      _v = lambda p, v: (str(round(v, 1)) + ' V')   
     
      #start our main-service
      pvac_output = DbusGoeControllerService(
        paths={
          '/Ac/Energy/Forward': {'initial': 0, 'textformat': _kwh},
          '/Ac/Energy/Reverse': {'initial': 0, 'textformat': _kwh},
          '/Ac/Power': {'initial': 0, 'textformat': _w},
          '/Ac/L1/Voltage': {'initial': 0, 'textformat': _v},
          '/Ac/L2/Voltage': {'initial': 0, 'textformat': _v},
          '/Ac/L3/Voltage': {'initial': 0, 'textformat': _v},
          '/Ac/L1/Current': {'initial': 0, 'textformat': _a},
          '/Ac/L2/Current': {'initial': 0, 'textformat': _a},
          '/Ac/L3/Current': {'initial': 0, 'textformat': _a},
          '/Ac/L1/Power': {'initial': 0, 'textformat': _w},
          '/Ac/L2/Power': {'initial': 0, 'textformat': _w},
          '/Ac/L3/Power': {'initial': 0, 'textformat': _w}
        })
     
      logging.info('Connected to dbus, and switching over to gobject.MainLoop() (= event based)')
      mainloop = gobject.MainLoop()
      mainloop.run()            
  except (ValueError, requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
    logging.critical('Error in main type %s', str(e))
  except Exception as e:
    logging.critical('Error at %s', 'main', exc_info=e)
if __name__ == "__main__":
  main()
