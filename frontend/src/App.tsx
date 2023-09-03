// @ts-nocheck

import { useState, useEffect, useRef } from 'react'
import Container from 'react-bootstrap/Container'
import Row from 'react-bootstrap/Row'
import Col from 'react-bootstrap/Col'
import Form from 'react-bootstrap/Form'
import Spinner from 'react-bootstrap/Spinner'

function connect(
  connectionCallback,
  dataChannelCallback,
  videoCallback,
  messageCallback
) {
  let iceServers = []
  if (!['localhost', '127.0.0.1'].includes(location.hostname)) {
    iceServers = [
      {
        urls: 'stun:stun.l.google.com:19302',
      },
      {
        urls: 'stun:global.stun.twilio.com:3478',
      },
    ]
  }
  const pc = new RTCPeerConnection({
    sdpSemantics: 'unified-plan',
    iceServers: iceServers,
  })
  pc.addEventListener('track', function (e) {
    videoCallback(e.streams[0])
  })

  const dataChannel = pc.createDataChannel('datachannel')
  dataChannel.addEventListener('message', messageCallback)

  async function start() {
    let offer = await pc.createOffer({
      offerToReceiveVideo: true,
    })

    await pc.setLocalDescription(offer)
    if (pc.iceGatheringState !== 'complete') {
      await new Promise((resolve) => {
        function checkState() {
          if (pc.iceGatheringState === 'complete') {
            pc.removeEventListener('icegatheringstatechange', checkState)
            resolve()
          }
        }
        pc.addEventListener('icegatheringstatechange', checkState)
      })
    }
    offer = pc.localDescription

    const response = await fetch(import.meta.env.VITE_WEBRTC_OFFER_URL, {
      body: JSON.stringify({
        sdp: offer.sdp,
        type: offer.type,
      }),
      headers: {
        'Content-Type': 'application/json',
      },
      method: 'POST',
    })
    const answer = await response.json()
    await pc.setRemoteDescription(answer)

    connectionCallback(pc)
    dataChannelCallback(dataChannel)
  }
  start()
}

function rgbToHex(rgb) {
  return (
    '#' +
    ((1 << 24) | (rgb[0] << 16) | (rgb[1] << 8) | rgb[2]).toString(16).slice(1)
  )
}

function App() {
  const maxDrawSize = 75,
    drawFrequency = 60,
    zoomVelocity = 0.1,
    minZoom = 0.05,
    moveVelocity = 0.1

  const [connection, setConnection] = useState(null)
  const [dataChannel, setDataChannel] = useState(null)
  const [numberPlayers, setNumberPlayers] = useState(1)
  const [cellStates, setCellStates] = useState([])
  const [selectedCellState, setSelectedCellState] = useState(1)
  const [draw, setDraw] = useState(false)
  const [drawSize, setDrawSize] = useState(15)
  const [universe, setUniverse] = useState(null)
  const [zoom, setZoom] = useState(1)
  const [position, setPosition] = useState({ x: 0, y: 0 })
  const connectionState = useRef(0)
  const mousePosition = useRef({ x: 0, y: 0 })
  const refVideo = useRef<HTMLVideoElement>(null)

  function handleMessages(e) {
    const message = JSON.parse(e.data)
    const value = message['value']
    switch (message['type']) {
      case 'init':
        setUniverse(value['universe'])
        setCellStates(value['cellStates'])
        setSelectedCellState(1)
        break
      case 'color':
        setCellStates((prevCellStates) => {
          return prevCellStates.map((cellState) =>
            cellState.value === value['cellState']
              ? { value: cellState.value, color: value['color'] }
              : cellState
          )
        })
        break
      case 'players':
        setNumberPlayers(value)
        break
    }
  }

  function handleMouseMove(e) {
    const rect = e.target.getBoundingClientRect()
    mousePosition.current = {
      x: (e.clientX - rect.left) / refVideo.current.clientWidth,
      y: (e.clientY - rect.top) / refVideo.current.clientHeight,
    }
  }

  function handleColorChange(e) {
    const hex = e.target.value
    const rgb = hex.match(/[A-Za-z0-9]{2}/g).map((c) => parseInt(c, 16))
    dataChannel.send(
      JSON.stringify({
        type: 'color',
        value: { cellState: selectedCellState, color: rgb },
      })
    )
  }

  useEffect(() => {
    if (connectionState.current !== 0) return

    connectionState.current = 1
    connect(
      (connection) => {
        setConnection(connection)
        connectionState.current = 2
      },
      setDataChannel,
      (videoStream) => (refVideo.current.srcObject = videoStream),
      handleMessages
    )

    return () => {
      if (connection) connection.close()
      if (dataChannel) dataChannel.close()
    }
  }, [])

  useEffect(() => {
    if (!draw) return
    const drawInterval = setInterval(() => {
      dataChannel.send(
        JSON.stringify({
          type: 'draw',
          value: {
            x: mousePosition.current.x,
            y: mousePosition.current.y,
            size: drawSize,
            cellState: selectedCellState,
          },
        })
      )
    }, 1000 / drawFrequency)
    return () => clearInterval(drawInterval)
  }, [draw])

  useEffect(() => {
    function handleKeyDown(e) {
      const value = { zoom: zoom, position: position }
      const positionDelta = moveVelocity * zoom

      switch (e.keyCode) {
        case 81:
          value.zoom += zoomVelocity
          break
        case 69:
          value.zoom -= zoomVelocity
          break
        case 83:
          value.position.y += positionDelta
          break
        case 87:
          value.position.y -= positionDelta
          break
        case 68:
          value.position.x += positionDelta
          break
        case 65:
          value.position.x -= positionDelta
          break
      }

      value.zoom = Math.min(Math.max(value.zoom, minZoom), 1)
      value.position.x = Math.min(Math.max(value.position.x, 0), 1 - value.zoom)
      value.position.y = Math.min(Math.max(value.position.y, 0), 1 - value.zoom)

      dataChannel.send(
        JSON.stringify({
          type: 'video',
          value: value,
        })
      )
      setZoom(value.zoom)
      setPosition(value.position)
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [dataChannel, zoom, position, zoomVelocity, moveVelocity, minZoom])

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        height: '100%',
        width: '100%',
        backgroundColor: 'black',
      }}
    >
      <video
        ref={refVideo}
        autoPlay
        muted
        style={{
          position: 'absolute',
          top: '50%',
          left: '50%',
          transform: 'translate(-50%, -50%)',
          width: 'min(100vw, 100vh)',
          height: 'min(100vw, 100vh)',
        }}
        draggable="false"
        onMouseMove={handleMouseMove}
        onMouseDown={() => setDraw(true)}
        onMouseUp={() => setDraw(false)}
        onMouseLeave={() => setDraw(false)}
      />
      <div
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          height: '100%',
          width: '250px',
          paddingTop: '40px',
          backgroundColor: 'rgb(15, 15, 15)',
        }}
      >
        {cellStates.length == 0 ? (
          <div style={{ textAlign: 'center' }}>
            <Spinner animation="border" variant="light" role="status" />
            <p className="text-white">
              Connecting...
              <br />
              This can take a minute
            </p>
          </div>
        ) : (
          <Container>
            <Row className="mb-4">
              {cellStates.map((cellState) => (
                <Col style={{ textAlign: 'center' }}>
                  <span
                    style={{
                      backgroundColor: `rgb(${cellState.color.join(',')})`,
                      height: '30px',
                      width: '30px',
                      borderRadius: '50%',
                      display: 'inline-block',
                      border:
                        cellState.value === selectedCellState
                          ? '3px solid white'
                          : '3px solid rgb(100,100,100)',
                    }}
                    onClick={(e) => setSelectedCellState(cellState.value)}
                  ></span>
                </Col>
              ))}
            </Row>
            <Row className="mb-4">
              <Col>
                <Form.Control
                  type="color"
                  style={{
                    padding: '0px',
                    width: '100%',
                    border: '1px solid white',
                  }}
                  value={rgbToHex(cellStates[selectedCellState].color)}
                  onChange={handleColorChange}
                />
              </Col>
            </Row>
            <Row className="mb-4">
              <Col>
                <Form.Range
                  min={1}
                  max={maxDrawSize}
                  value={drawSize}
                  onChange={(e) => {
                    setDrawSize(parseInt(e.target.value))
                  }}
                />
              </Col>
            </Row>
            <Row className="mb-4">
              <Col>
                <Form.Select
                  value={universe}
                  onChange={(e) => {
                    dataChannel.send(
                      JSON.stringify({
                        type: 'universe',
                        value: e.target.value,
                      })
                    )
                  }}
                >
                  <option value={'game_of_life'}>Game of Life</option>
                  <option value={'falling_sand'}>Falling Sand</option>
                  <option value={'growth'}>Growth</option>
                </Form.Select>
              </Col>
            </Row>
            <Row>
              <Col>
                <p className="text-white">
                  Move Keys: <b>w</b>, <b>a</b>, <b>s</b>, <b>d</b>
                </p>
                <p className="text-white">
                  Zoom Keys: <b>q</b>, <b>e</b>
                </p>
                <p className="text-white">
                  Players Online: <b>{numberPlayers}</b>
                </p>
              </Col>
            </Row>
          </Container>
        )}
      </div>
    </div>
  )
}

export default App
