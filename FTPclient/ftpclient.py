import argparse
import os
from urllib.parse import urlparse
import re
import socket

#Helper method that checks for FTP errors and prints if verbose is true
def handleresponse(ftpresponse):
    codedigit = ftpresponse[0]
    if codedigit == '4' or codedigit == '5' or codedigit == '6':
        raise Exception(ftpresponse)
    elif verbose:
        print(ftpresponse)


#Helper method that collects and decodes a response from the given socket
def listenforresponse(cursocket):
    response = ""
    while not response.endswith("\r\n"):
        data = cursocket.recv(1024)
        if not data:
            return response
        response += data.decode()

    return response


#Function to handle opening the data channel
def opendatachannel(controlsocket):  # TODO: REMEMBER to close this if you're sending data
    response = sendandrcv(controlsocket, "PASV\r\n")
    handleresponse(response)

    splitdata = re.split("\(|,|\)", response)

    datahostname = ""
    for i in range(1, 5):
        datahostname += "." + splitdata[i]
    datahostname = datahostname[1:]

    dataport = (int(splitdata[5]) << 8) + int(splitdata[6])

    datasocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    datasocket.connect((datahostname, dataport))

    return datasocket


#Helper method that encodes and sends a message, then calls listenforresponse
def sendandrcv(cursocket, msg):
    cursocket.send(msg.encode())
    return listenforresponse(cursocket)


#Function handling ls command. Prints files that exist on the ftp server at the given path
def listfiles(path, controlsocket):
    datasocket = opendatachannel(controlsocket)
    controlsocket.send(("LIST " + path + "\r\n").encode())
    print(listenforresponse(datasocket))


#Function handling the mkdir command. Makes a directory at the given path
def makedir(path, cursocket):
    handleresponse(sendandrcv(cursocket, "MKD " + path + "\r\n"))


#Function handling the rm command. Removes the file at the given path
def remove(path, cursocket):
    handleresponse(sendandrcv(cursocket, "DELE " + path + "\r\n"))


#Function handling the rmdir command. Removes a directory at the given path
def removedir(path, cursocket):
    handleresponse(sendandrcv(cursocket, "RMD " + path + "\r\n"))

#Function handling the cp command. Copies a file from the first path given to the second path
def copyfile(copyfrom, copyto, controlsocket):
    datasocket = opendatachannel(controlsocket)
    if copyfrom.scheme == "ftp":  # copy to computer from ftp
        localpath = copyto.path
        remotepath = copyfrom.path[1:]

        handleresponse(sendandrcv(controlsocket, "RETR " + remotepath + "\r\n"))

        file = open(localpath, 'wb')

        while True:
            data = datasocket.recv(1024)
            if not data:
                break
            file.write(data)
        file.close()

    else:  # copy to ftp from computer
        remotepathexceptfile = '/'.join(copyto.path.split("/")[:-1])
        remotepath = copyto.path[1:]

        if len(remotepathexceptfile) != 0:
            handleresponse(sendandrcv(controlsocket, "CWD {}\r\n".format(remotepath)))

        handleresponse(sendandrcv(controlsocket, "STOR {}\r\n".format(remotepath)))

        binaryfilecontent = open(copyfrom.path, 'rb').read()
        datasocket.send(binaryfilecontent)
        datasocket.close()
        handleresponse(listenforresponse(controlsocket))


#Function handling the mv command. Calls copy and then deletes the spare file
def movefile(movefrom, moveto, controlsocket):
    copyfile(movefrom, moveto, controlsocket)

    if movefrom.scheme == 'ftp': #move from server to computer
        remove(movefrom.path[1:], controlsocket)
    else:
        os.remove(movefrom.path)



#Returns username, password, hostname, port from a url tuple
def parseftpTuple(urlTuple):
    urlchunk = urlTuple.netloc
    port = 21
    if '@' in urlchunk:
        splitstring = re.split(":|@", urlchunk)
        if len(splitstring) == 4:
            port = int(splitstring[3])
        return splitstring[0], splitstring[1], splitstring[2], port
    else:
        hostname = urlchunk
        if ':' in urlchunk:
            splitstring = urlchunk.split(':')
            hostname = splitstring[0]
            port = splitstring[1]
        return "anonymous", "", hostname, port


argParser = argparse.ArgumentParser()
argParser.add_argument("-v", "--verbose", action="store_true", help="Print all messages to and from the FTP server")
argParser.add_argument("operation",
                       help="The operation to execute. Valid operations are 'ls', 'rm', 'rmdir', 'mkdir', 'cp', and 'mv'")
argParser.add_argument("params", nargs='+',
                       help="Parameters for the given operation. Will be one or two paths and/or URLs.")

args = vars(argParser.parse_args())
verbose = args["verbose"]

operation = args["operation"]
param1 = urlparse(args["params"][0])
ftpurl = param1
if operation == "cp" or operation == "mv":
    if len(args["params"]) != 2:
        raise ValueError("Copy and move require two urls")
    param2 = urlparse(args["params"][1])
    ftpurl = param2 if param2.scheme == "ftp" else param1

if ftpurl.scheme != "ftp":
    i = 0
    raise ValueError("One url must refer to the ftp server")

username, password, hostname, port = parseftpTuple(ftpurl)

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.connect((hostname, port))
    handleresponse(listenforresponse(s))  # wait for welcome

    handleresponse(sendandrcv(s, "USER " + username + "\r\n"))

    handleresponse(sendandrcv(s, "PASS " + password + "\r\n"))

    handleresponse(sendandrcv(s, "TYPE I\r\n"))

    handleresponse(sendandrcv(s, "MODE S\r\n"))

    handleresponse(sendandrcv(s, "STRU F\r\n"))

    if operation == "cp":
        copyfile(param1, param2, s)
    elif operation == "mv":
        movefile(param1, param2, s)
    elif operation == "ls":
        listfiles(param1.path[1:], s)
    elif operation == "mkdir":
        makedir(param1.path[1:], s)
    elif operation == "rm":
        remove(param1.path[1:], s)
    elif operation == "rmdir":
        removedir(param1.path[1:], s)
    else:
        raise ValueError("Operation not supported")

    sendandrcv(s, "QUIT\r\n")
