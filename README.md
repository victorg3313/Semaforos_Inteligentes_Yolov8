# Semaforos_Inteligentes_Yolov8
Proyecto de semaforo inteligente
Este proyecto utiliza la computadora como cerebro principal del nuestro semaforo, el codigo principal Yolo.py es el algoritmo que analiza y detecta el numero de personas por via y da las indicaciones requeridas al Esp32, como girar los servos para que gire la camara, activar los relevadores que encienden las luces del semaforo. El esp32 se conecto al computadora por el puerto serial y se le ingreso un codigo para que este solo fuera un exclavo serial e hiciera lo que le codigo Yolo.py le indica.
todo esto funciona con python usando opencv y Yolo en su version numero 8 ademas de que el esp32 tambien se programo con python es micropython.
