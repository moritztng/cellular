https://github.com/moritztng/cellular/assets/19519902/1691bc6e-8c36-4df9-abc0-2f034b71038f

Full Video on [YouTube](https://youtu.be/AwLMmECtJqI)

## Installation
```bash
git clone https://github.com/moritztng/cellular.git
cd cellular
pip3 install -r requirements.txt
```

## Quickstart
### Local URL
```bash
> python3 cellular.py

success! open http://127.0.0.1:8080/index.html
```
### Public ngrok URL
```bash
> python3 cellular.py --public --ngrok_token <AUTHTOKEN>

success! open https://8a24-2a02-2455-18a7-5000-216-3eff-fe06-1216.ngrok-free.app/index.html
```
The token is optional and only to use your personal ngrok account.
### Complex Example
```bash
> python3 cellular.py --port 8080 --public --ngrok_token <AUTHTOKEN> --device cuda --universe_frequency 30 --universe_size 500  --video_size 500 --video_bitrate 5000000 --logging_debug
```

## Parameters
```
  -h, --help            show this help message and exit
  --port                set port (default: 8080)
  --public              get a public url (default: False)
  --ngrok_token         set ngrok authtoken to use your personal ngrok account. https://dashboard.ngrok.com/get-started/your-authtoken (default: None)
  --device              set cpu, cuda or auto. (default: auto)
  --universe_frequency  number of universe steps per second (default: 30)
  --universe_size       length of sides of the quadratic universe in pixels (default: 500)
  --video_size          length of sides of the quadratic video stream in pixels (default: 500)
  --video_bitrate       bitrate of the video stream (default: 5000000)
  --logging_debug       set logging level to debug (default: False)
```
