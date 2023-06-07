import logging
import json

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

# Initialise logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

from .database.database import Database

# Initialise the database
database = Database()

# Set the base template location
TEMPLATES = Jinja2Templates('/src/templates')

# Instantiate the application object, ensure every request sets the user into Request.state.user
app = FastAPI()

# Mount the static files
app.mount('/static', StaticFiles(directory='/src/static'), name='static')

# Gets the homepage
@app.get('/', response_class=HTMLResponse)
async def root(request: Request):
    logging.info('Homepage requested')
    return TEMPLATES.TemplateResponse('index.html', {'request': request})

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    logging.info('Websocket Opened')

    try:
        while True:
            # Wait for a message from the client
            recv = await websocket.receive_text()

            # Load the json
            msg = json.loads(recv)

            # Get the type of message
            match msg['messageType']:
                case 'ping':
                    # Log the ping
                    logging.debug('Ping received')

                    # Send a pong message
                    await websocket.send_text(json.dumps({'messageType': 'pong'}))
                
                case _:
                    # Send an error message
                    logging.error(f'Unknown message type: {msg["messageType"]}')


    except WebSocketDisconnect:
        logging.info('Websocket Closed')
