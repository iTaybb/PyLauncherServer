My project for defensive programming seminarion of my BSC degree in the Open University of Israel.
The server gets python scripts to launch. The servers runs the scripts in a secure manner, inside a docker container built specifically for the execution. After the execution is done, the output it transferred out and the container is destroyed.

This repo, PyLauncherServer, contains the server implementation. It exposed a REST api.
An example C++ GUI client is provided in a different repo - PyLauncherClient.