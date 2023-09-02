import logging, json, uuid, time, asyncio, threading, aiohttp_cors, torch
from argparse import ArgumentParser, ArgumentDefaultsHelpFormatter
from pyngrok import ngrok
from aiohttp import web
from aiortc import RTCPeerConnection, RTCIceServer, RTCConfiguration, RTCSessionDescription, VideoStreamTrack
from aiortc.codecs import vpx
from av import VideoFrame
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
import torch.nn.functional as torch_functions

from rules import GameOfLife, FallingSand, Growth

class Universe:
    def __init__(self, name, state, rule, colors):
        self.name = name
        self.state = state
        self.rule = rule
        self.colors = colors

    def step(self):
        self.state = self.rule(self.state)

class VideoTransformTrack(VideoStreamTrack):
    def __init__(self, universe,  size):
        super().__init__()
        self.universe = universe
        self.size = size
        self.position = [0, 0]
        self.zoom = 1

    async def recv(self):
        video_state_size = int(self.universe[0].state.size(2) * self.zoom)
        frame = self.universe[0].state[:, :, 
                                       self.position[0]:self.position[0] + video_state_size, 
                                       self.position[1]:self.position[1] + video_state_size]
        frame = frame.reshape((frame.size(1), -1)).T[...,None]
        frame = self.universe[0].colors.T @ frame
        frame = frame.permute(1, 2, 0)
        frame = frame.view((1, 3, video_state_size, video_state_size))
        frame = torch_functions.interpolate(frame, (self.size, self.size), mode="nearest-exact").clamp(min=0, max=255)
        frame = frame[0].permute(1, 2, 0).to(dtype=torch.uint8, device="cpu")
        frame = VideoFrame.from_ndarray(frame.numpy(), format="bgr24")
        pts, time_base = await self.next_timestamp()
        frame.pts = pts
        frame.time_base = time_base
        return frame

def run_universe(stop_event, universe, universe_frequency, device, input_queue):
    while not stop_event.is_set():
        while not input_queue.empty():
            input = input_queue.get()
            top = max(input[0] - input[2], 0)
            bottom = min(input[0] + input[2] + 1, universe[0].state.size(2))
            left = max(input[1] - input[2], 0)
            right = min(input[1] + input[2] + 1, universe[0].state.size(3))
            one_hot = torch.zeros(universe[0].state.size(1), dtype=torch.float32, device=device)
            one_hot[input[3]] = 1
            universe[0].state[0, :, top:bottom, left:right] = one_hot[:, None, None]
        universe[0].step()
        time.sleep(1 / universe_frequency)

async def offer(request):
    connection_config = RTCConfiguration([RTCIceServer("stun:stun.l.google.com:19302")]) if app["state"]["public"] else None
    connection = RTCPeerConnection(connection_config)
    connection_id = uuid.uuid4()
    
    agent = {"connection": connection, "data_channel": None, "video_track": None, "position": [0, 0], "zoom": 1.}
    agents = app["state"]["agents"]
    agents[connection_id] = agent
    universes = app["state"]["universes"]
    universe = app["state"]["universe"]

    def log_connection(msg):
        app["state"]["logger"].info("connection %s: %s", connection_id, msg)
    log_connection(f"connecting to {request.remote}")

    def send_number_players():
        for current_agent in agents.values():
            if current_agent["data_channel"]:
                try:
                    current_agent["data_channel"].send(json.dumps({"type": "players", "value": len(agents)}))
                except:
                    pass

    @connection.on("connectionstatechange")
    async def on_connectionstatechange():
        log_connection(f"connection state is {connection.connectionState}")

        if connection.connectionState == "failed":
            await connection.close()
            agents.pop(connection_id)
            send_number_players()

    @connection.on("datachannel")
    def on_datachannel(channel):
        log_connection("add datachannel")

        agent["data_channel"] = channel

        def send_initial_state(channel):
            cellStates = []
            for value, color in enumerate(universe[0].colors[:,[2,1,0]].to(dtype=torch.uint8, device="cpu").tolist()):
                cellStates.append({"value": value, "color": color})
            channel.send(json.dumps({"type": "init", "value": {"universe": universe[0].name, "cellStates": cellStates}}))
        send_initial_state(channel)
        send_number_players()
        
        @channel.on("message")
        def on_message(message):
            message = json.loads(message)
            value = message["value"]
            
            if message["type"] == "universe":
                universe[0] = universes[value]()
                for current_agent in agents.values():
                    try:
                        send_initial_state(current_agent["data_channel"])
                    except:
                        pass

            elif message["type"] == "draw":
                scale = agent["zoom"] * app["state"]["universe_size"]
                y = int(value["y"] * scale + agent["position"][0])
                x = int(value["x"] * scale + agent["position"][1])
                app["state"]["input_queue"].put([y, x, value["size"], value["cellState"]])

            elif message["type"] == "color":
                colors = universe[0].colors 
                colors[value["cellState"], :] = torch.tensor(value["color"], dtype=torch.float32, 
                                                             device=colors.device)[[2,1,0]]
                for current_agent in agents.values():
                    try:
                        current_agent["data_channel"].send(
                            json.dumps({"type": "color","value": {"cellState": value["cellState"], "color": value["color"]}}))
                    except:
                        pass

            elif message["type"] == "video":
                universe_size = app["state"]["universe_size"]
                agent["position"] = [int(value["position"]["y"] * universe_size), int(value["position"]["x"] * universe_size)]
                agent["zoom"] = value["zoom"]
                agent["video_track"].position = agent["position"]
                agent["video_track"].zoom = value["zoom"]

    offer = await request.json()
    offer = RTCSessionDescription(sdp=offer["sdp"], type=offer["type"])
    await connection.setRemoteDescription(offer)
    agent["video_track"] = VideoTransformTrack(universe, app["state"]["video_size"])
    connection.addTrack(agent["video_track"])
    answer = await connection.createAnswer()
    await connection.setLocalDescription(answer)
    return web.Response(content_type="application/json", 
                        text=json.dumps({"sdp": connection.localDescription.sdp, "type": connection.localDescription.type}))

async def on_startup(app):
    loop = asyncio.get_event_loop()
    loop.run_in_executor(app["state"]["executer"], run_universe, app["state"]["stop_event"], 
                         app["state"]["universe"], app["state"]["universe_frequency"], 
                         app["state"]["device"], app["state"]["input_queue"])
    print(f"success! open \033[96m{app['state']['url']}/index.html\033[0m")

async def on_shutdown(app):
    agents = app["state"]["agents"]
    futures = [agent["connection"].close() for agent in agents.values()]
    await asyncio.gather(*futures)
    agents.clear()
    app["state"]["stop_event"].set()
    app["state"]["executer"].shutdown()

if __name__ == "__main__":
    parser = ArgumentParser(prog='Cellular', 
                            description='Cellular Automata in PyTorch with Multiplayer Mode in Browser via WebRTC', 
                            formatter_class=ArgumentDefaultsHelpFormatter)
    
    parser.add_argument('--port', default=8080, type=int, help='set port')
    parser.add_argument('--public', action='store_true', help='get a public url')
    parser.add_argument('--ngrok_token', help='set ngrok authtoken to use your personal ngrok account. https://dashboard.ngrok.com/get-started/your-authtoken')
    parser.add_argument('--device', choices=["cpu", "cuda", "auto"], default='auto', help='set cpu, cuda or auto.')
    parser.add_argument('--universe_frequency', default=30, type=int, help='number of universe steps per second')
    parser.add_argument('--universe_size', default=500, type=int, help='length of sides of the quadratic universe in pixels')
    parser.add_argument('--video_size', default=500, type=int, help='length of sides of the quadratic video stream in pixels')
    parser.add_argument('--video_bitrate', default=5000000, type=int, help='bitrate of the video stream')
    parser.add_argument('--logging_debug', action='store_true', help='set logging level to debug')
    args = parser.parse_args()
    
    url = f"http://127.0.0.1:{args.port}"
    if args.public:
        if args.ngrok_token:
            ngrok.set_auth_token(args.ngrok_token)
        tunnel = ngrok.connect(args.port, bind_tls=True)
        url = tunnel.public_url
    
    app = web.Application()
    cors = aiohttp_cors.setup(app, defaults={"*": aiohttp_cors.ResourceOptions(
        allow_credentials=True, 
        expose_headers="*", 
        allow_headers="*")})
    
    vpx.DEFAULT_BITRATE = vpx.MIN_BITRATE = vpx.MAX_BITRATE = args.video_bitrate
    device = args.device if args.device != "auto"  else "cuda" if torch.cuda.is_available() else "cpu"
    universe_size = args.universe_size
    
    universes = {"game_of_life": {"rule": GameOfLife, "state_colors": [[0, 0, 0], [0, 255, 0]]},
                 "falling_sand": {"rule": FallingSand, "state_colors": [[0, 75, 173], [255, 218, 148], [255, 218, 148]]},
                 "growth": {"rule": Growth, "state_colors": [[0, 0, 0], [255, 0, 255], [0, 255, 255]]}}
    
    for name, params in universes.items():
        universes[name] = (lambda name=name, params=params: 
                                Universe(name, torch.zeros((1, len(params["state_colors"]), universe_size, universe_size), 
                                         dtype=torch.float32, device=device), params["rule"](device), 
                                         torch.tensor(params["state_colors"], dtype=torch.float32, device=device)[:, [2, 1, 0]]))

    app_state = {
        "agents": {},
        "video_size": args.video_size,
        "universes": universes,
        "universe": [universes["game_of_life"]()],
        "universe_size": universe_size,
        "universe_frequency": args.universe_frequency,
        "device": device,
        "executer": ThreadPoolExecutor(max_workers=3),
        "input_queue": Queue(),
        "stop_event": threading.Event(),
        "logger": logging.getLogger(),
        "public": args.public,
        "url": url
    }

    app["state"] = app_state

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)    
    app.router.add_static("/", "./frontend/dist")
    cors.add(app.router.add_post("/offer", offer))

    app_print = None
    if args.logging_debug:
        logging.basicConfig(level=logging.DEBUG)
        app_print = print

    web.run_app(app, port=args.port, print=app_print)
