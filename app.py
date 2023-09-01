import logging, json, uuid, time, asyncio, threading, aiohttp_cors, torch
from argparse import ArgumentParser
from pyngrok import ngrok
from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
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
        video_state_size = int(size * self.zoom)
        frame = self.universe[0].state[:, :, self.position[0]:self.position[0] + video_state_size, self.position[1]:self.position[1] + video_state_size]
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

def run_universe(loop, event, universe, universe_frequency, device, input_queue):
    while not event.is_set():
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
    params = await request.json()
    offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])
    connection = RTCPeerConnection()
    connection_id = uuid.uuid4()
    
    agent = {"connection": connection, "data_channel": None, "video_track": None, "position": [0, 0], "zoom": 1.}
    agents = app["state"]["agents"]
    agents[connection_id] = agent
    universes = app["state"]["universes"]
    universe = app["state"]["universe"]

    def log_info(msg, *args):
        app["state"]["logger"].info(str(connection_id) + " " + msg, *args)

    log_info("Connection to %s", request.remote)

    @connection.on("connectionstatechange")
    async def on_connectionstatechange():
        log_info("Connection state is %s", connection.connectionState)
        if connection.connectionState == "failed":
            await connection.close()
            agents.pop(connection_id)

    @connection.on("datachannel")
    def on_datachannel(channel):
        def send_initial_state(channel):
            cellStates = []
            for i, color in enumerate(universe[0].colors[:,[2,1,0]].to(dtype=torch.uint8, device="cpu").tolist()):
                cellStates.append({"value": i, "color": color})
            channel.send(json.dumps({
                "type": "init",
                "value": {
                    "universe": universe[0].name,
                    "cellStates": cellStates
                }
            }))
        agent["data_channel"] = channel
        send_initial_state(channel)
        
        @channel.on("message")
        def on_message(message):
            message = json.loads(message)
            value = message["value"]
            if message["type"] == "draw":
                app["state"]["input_queue"].put([int(value["y"] * agent["zoom"] * app["state"]["size"] + agent["position"][0]), 
                                 int(value["x"] * agent["zoom"] * app["state"]["size"] + agent["position"][1]), 
                                 value["size"], value["cellState"]])
            elif message["type"] == "color":
                universe[0].colors[value["cellState"], :] = torch.tensor(value["color"], dtype=torch.float32, device=app["state"]["device"])[[2,1,0]]
                for current_agent in agents.values():
                    current_agent["data_channel"].send(json.dumps({
                        "type": "color",
                        "value": {
                            "cellState": value["cellState"],
                            "color": value["color"]
                        }
                    }))
            elif message["type"] == "universe":
                universe[0] = universes[value]()
                for current_agent in agents.values():
                    send_initial_state(current_agent["data_channel"])
            elif message["type"] == "video":
                size = app["state"]["size"]
                agent["position"] = [int(value["position"]["y"] * size), int(value["position"]["x"] * size)]
                agent["zoom"] = value["zoom"]
                agent["video_track"].position = agent["position"]
                agent["video_track"].zoom = value["zoom"]

    await connection.setRemoteDescription(offer)
    video_track = VideoTransformTrack(universe, app["state"]["video_size"])
    connection.addTrack(video_track)
    agent["video_track"] = video_track
    answer = await connection.createAnswer()
    await connection.setLocalDescription(answer)
    return web.Response(
        content_type="application/json",
        text=json.dumps(
            {"sdp": connection.localDescription.sdp, "type": connection.localDescription.type}
        ),
    )

async def on_startup(app):
    loop = asyncio.get_event_loop()
    loop.run_in_executor(app["state"]["executer"], run_universe, loop, app["state"]["event"], app["state"]["universe"], app["state"]["universe_frequency"], app["state"]["device"], app["state"]["input_queue"])
    print(f"success! open \033[96m{app['state']['url']}/index.html\033[0m and explore the cellular automata!")

async def on_shutdown(app):
    agents = app["state"]["agents"]
    coros = [agent["connection"].close() for agent in agents.values()]
    await asyncio.gather(*coros)
    agents.clear()
    app["state"]["event"].set()
    app["state"]["executer"].shutdown()

if __name__ == "__main__":
    parser = ArgumentParser(
                    prog='Cellular',
                    description='Cellular Automata in PyTorch streamed to the Browser via WebRTC')
    parser.add_argument('--port', default=8080, type=int)
    parser.add_argument('--public', action='store_true', help='get a public url')
    parser.add_argument('--ngrok_token', help='set ngrok authtoken to use personal ngrok account. https://dashboard.ngrok.com/get-started/your-authtoken')
    parser.add_argument('--device', choices=["cpu", "cuda", "auto"], default='auto', help='set cpu, cuda or auto.')
    parser.add_argument('--universe_frequency', default=30, type=int, help='number of universe steps per second')
    parser.add_argument('--universe_size', default=500, type=int, help='length of sides of the quadratic universe in pixels')
    parser.add_argument('--video_size', default=500, type=int, help='length of sides of the quadratic video stream in pixels')

    args = parser.parse_args()
    
    url = f"http://127.0.0.1:{args.port}"
    if args.public:
        if args.ngrok_token:
            ngrok.set_auth_token(args.ngrok_token)
        tunnel = ngrok.connect(args.port, bind_tls=True)
        url = tunnel.public_url
    
    app = web.Application()
    cors = aiohttp_cors.setup(app, defaults={
    "*": aiohttp_cors.ResourceOptions(
            allow_credentials=True,
            expose_headers="*",
            allow_headers="*",
        )
    })
    
    vpx.DEFAULT_BITRATE = vpx.MIN_BITRATE = vpx.MAX_BITRATE = 5000000
    device = args.device if args.device != "auto"  else "cuda" if torch.cuda.is_available() else "cpu"
    size = args.universe_size
    universes = {"falling_sand": lambda : Universe("falling_sand", torch.zeros((1, 3, size, size), dtype=torch.float32, device=device), FallingSand(device), torch.tensor([[0, 0, 0], [0, 255, 0], [0, 0, 255]], dtype=torch.float32, device=device)),
                    "growth": lambda : Universe("growth", torch.zeros((1, 3, size, size), dtype=torch.float32, device=device), Growth(device), torch.tensor([[0, 0, 0], [0, 255, 0], [0, 0, 255]], dtype=torch.float32, device=device)),
                    "game_of_life": lambda : Universe("game_of_life", torch.zeros((1, 2, size, size), dtype=torch.float32, device=device), GameOfLife(device), torch.tensor([[0, 0, 0], [0, 255, 0]], dtype=torch.float32, device=device))}

    app_state = {
        "logger": logging.getLogger("connection"),
        "executer": ThreadPoolExecutor(max_workers=3),
        "input_queue": Queue(),
        "event": threading.Event(),
        "size": size,
        "video_size": args.video_size,
        "universe_frequency": args.universe_frequency,
        "device": device,
        "agents": {},
        "universes": universes,
        "universe": [universes["falling_sand"]()],
        "url": url
    }

    app["state"] = app_state

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)    
    app.router.add_static("/", "./frontend/dist")
    cors.add(app.router.add_post("/offer", offer))

    logging.basicConfig(level=logging.DEBUG)

    web.run_app(
        app, access_log=None, port=args.port, print=None
    )
