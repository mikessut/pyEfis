#  Copyright (c) 2016 Phil Birkelbach
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.

# This module is a FIX-Net client used primarily to get the flight data
# from FIX-Gateway.

import socket
import threading
import Queue
import logging
import time

class SendThread(threading.Thread):
    def __init__(self, sock):
        super(SendThread, self).__init__()
        self.sock = sock
        self.queue = Queue.Queue()
        self.getout = False

    def run(self):
        self.running = True
        log.debug("SendThread - Starting")
        while True:
            data = self.queue.get()
            if data == 'exit': break
            try:
                self.sock.sendall(data)
            except Exception as e:
                log.debug("SendThread: {0}".format(e))
        self.running = False
        log.debug("SendThread - Stopping")

    def stop(self):
        self.queue.put('exit')



class ClientThread(threading.Thread):
    def __init__(self, host, port, db):
        super(ClientThread, self).__init__()
        global log
        log = logging.getLogger(__name__)
        self.host = host
        self.port = port
        self.db = db  # Main FIX database
        self.getout = False
        self.timeout = 1.0

    def handle_request(self, d):
        if d[0] == '@': # It's a command response frame
            x = d[2:].split(';')
            if d[1] == 'l':
                if len(x) != 3:
                    log.debug("Problem with ID list message")
                else:
                    y = x[2].split(',')  # break up the list of Ids
                    for each in y:
                        log.debug("Requesting a report for {0}".format(each))
                        self.sendthread.queue.put("@q{0}\n".format(each).encode())
                #print("List ID's")
                return
            else:
                id = x[0].strip()
            if d[1] == 's':
                log.debug("Subscription Acknowledged for {0}".format(id))
            elif d[1] == 'q':
                self.db.define_item(id, x[1], x[2], x[3], x[4], x[5], x[6], x[7])
                self.sendthread.queue.put("@r{0}\n".format(id).encode())
                self.sendthread.queue.put("@s{0}\n".format(id).encode())

        else:  # If no '@' then it must be a value update
            try:
                x = d.strip().split(';')
                if len(x) != 3:
                    self.log.debug("Bad Frame {0} from {1}".format(d.strip(), self.addr[0]))
                item = self.db.get_item(x[0])
                try:
                    item.annunciate = True if x[2][0] == '1' else False
                except:
                    pass
                try:
                    item.old = True if x[2][1] == '1' else False
                except:
                    pass
                try:
                    item.bad = True if x[2][2] == '1' else False
                except:
                    pass
                try:
                    item.fail = True if x[2][3] == '1' else False
                except:
                    pass
                #try:
                #    item.secondary_fail = True if x[2][4] == '1' else False
                #except:
                #    pass
                # if x[2] != '00000' or x[2] != '0000':
                item.value = x[1]
            except Exception as e:
                # We pretty much ignore this stuff for now
                log.debug("Problem with input {0}: {1}".format(d.strip, e))


    def run(self):
        while True:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.settimeout(self.timeout)

            try:
                s.connect((self.host, self.port))
            except Exception as e:
                log.debug("Failed to connect {0}".format(e))
            else:
                log.info("Connected to {0}:{1}".format(self.host, self.port))
                self.sendthread = SendThread(s)
                self.sendthread.queue.put("@l\n".encode())
                self.sendthread.start()

                buff = ""
                while True:
                    try:
                        data = s.recv(1024)
                    except socket.timeout:
                        if self.getout:
                            self.sendthread.stop()
                            self.sendthread.join()
                            break;
                    except Exception as e:
                        log.debug("Receive Failure {0}".format(e))
                    else:
                        if not data:
                            log.debug("No Data, Bailing Out")
                            self.sendthread.stop()
                            self.sendthread.join()
                            self.db.mark_all_fail()
                            break
                        else:
                            try:
                                dstring = data.decode("utf-8")
                            except UnicodeDecodeError:
                                self.log.debug("Bad Message from {0}".format(self.addr[0]))
                            for d in dstring:
                                if d=='\n':
                                    #try:
                                    self.handle_request(buff)
                                    #except Exception as e:
                                    #    log.debug("Error handling request {0}".format(buff))
                                    buff = ""
                                else:
                                    buff += d
            if self.getout:
                break
            else:
                # TODO: Replace with configuration time
                time.sleep(2)
                log.info("Attempting to Reconnect to {0}:{1}".format(self.host, self.port))

    def stop(self):
        self.getout = True
