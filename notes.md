ffplay -rtsp_transport tcp rtsp://172.26.14.238:8554/stream=1 , for seeing the stream. 

rtsp://ip:port?address

ffmpeg -rtsp_transport tcp \
-i "rtsp://192.168.144.108:554/stream=1" \
-c copy \
-f rtsp \
-rtsp_transport tcp \
rtsp://0.0.0.0:8554/c12

forwards the stream.


we are using gstream to relay the stream. 



 ffplay -rtsp_transport tcp rtsp://10.42.0.45:8554/c12
 to play the stream on laptop.

 ffplay -rtsp_transport tcp rtsp://10.192.15.160:8554/c12


IMP::::
ips : 1---> 10.42.0.45
    : 2--> 10.192.15.160


start the mediamtx before try to fetch the stream. 
for start go cd ~ , cd mediamtx , ./mediamtx




!!!!!
you must add the entry in routing table to access the stream .

!!!
used port Forwarder to make the android os work as router , or to transmite the drone pkts to camera and sending back the replies. 

it won't work without it , as android devices turn of nat and pat when using wifi client . 

!!!!
use UDPCL ,and port no. as 14500 and host ip .  to connect the mission planner , to controller, 
turned on the hotspot from the controller and used laptop as client . 


