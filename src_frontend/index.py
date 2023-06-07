from datetime import datetime, timedelta
import logging
import json

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

# Initialise logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

from .database.database import Database
from .messages.messages import ConvertingFileMessage, FilesToConvertMessage, ConvertedFilesMessage, MessageTypes, Message

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
    # Accept the websocket connection
    await websocket.accept()

    # Log the connection
    logging.info('Websocket Opened')

    # Initialise a variable to store the last time the files to convert was updated
    last_files_to_convert_update: datetime | None = None

    # Initialise a variable to store the last time the files converted was updated
    last_files_converted_update: datetime | None = None

    try:
        # Loop forever
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

                    # Get the current conversion status
                    current_conversion_status_db = await database.get_converting_file()

                    # logging.debug(f'Current conversion status: {current_conversion_status_db}')

                    if current_conversion_status_db is not None:
                        # Create a ConvertingFileMessage from the database object
                        current_conversion_status = ConvertingFileMessage(
                            filename=current_conversion_status_db.filename,
                            progress=int(current_conversion_status_db.percentage_complete)
                        )

                        message = Message(
                            messageType=MessageTypes.CONVERTING_FILE,
                            messageBody=current_conversion_status
                        )

                        logging.debug(f'Current conversion status: {message}')

                        # Send the conversion status
                        await websocket.send_json(message.dict())
                    else:
                        # Send the conversion status
                        await websocket.send_text(json.dumps({
                            'messageType': 'conversionStatus',
                            'messageBody': None
                        }))

                case _:
                    # Log an error
                    logging.error(f'Unknown message type: {msg["messageType"]}')


    except WebSocketDisconnect:
        # Log the disconnection
        logging.info('Websocket Closed')
