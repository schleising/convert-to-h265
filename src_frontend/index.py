import logging
import json

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

# Initialise logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

from .database.database import Database
from .messages.messages import ConvertingFileMessage, FilesToConvertMessage, ConvertedFilesMessage, StatisticsMessage, MessageTypes, Message

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

                    if current_conversion_status_db is not None:
                        # Create a ConvertingFileMessage from the database object
                        current_conversion_status = ConvertingFileMessage(
                            filename=current_conversion_status_db.filename,
                            progress=int(current_conversion_status_db.percentage_complete)
                        )

                        # Create a Message from the ConvertingFileMessage
                        message = Message(
                            messageType=MessageTypes.CONVERTING_FILE,
                            messageBody=current_conversion_status
                        )

                        # Log the conversion status
                        logging.debug(f'Current conversion status: {message}')

                        # Send the conversion status
                        await websocket.send_json(message.dict())
                    else:
                        # Send the conversion status as None
                        await websocket.send_json(Message(
                            messageType=MessageTypes.CONVERTING_FILE,
                            messageBody=None
                        ).dict())

                    # Get the files to convert
                    files_to_convert = await database.get_files_to_convert()

                    # Create a FilesToConvertMessage from the database objects
                    files_to_convert_message = FilesToConvertMessage(
                        filenames=files_to_convert
                    )

                    # Create a Message from the FilesToConvertMessage
                    message = Message(
                        messageType=MessageTypes.FILES_TO_CONVERT,
                        messageBody=files_to_convert_message
                    )

                    # Log the files to convert
                    logging.debug(f'Files to convert: {message}')

                    # Send the files to convert
                    await websocket.send_json(message.dict())

                    # Get the files converted
                    files_converted = await database.get_converted_files()

                    # Create a ConvertedFilesMessage from the database objects
                    files_converted_message = ConvertedFilesMessage(
                        filenames=files_converted
                    )

                    # Create a Message from the ConvertedFilesMessage
                    message = Message(
                        messageType=MessageTypes.CONVERTED_FILES,
                        messageBody=files_converted_message
                    )

                    # Log the files converted
                    logging.debug(f'Files converted: {message}')

                    # Send the files converted
                    await websocket.send_json(message.dict())

                    # Get the statistics
                    statistics = await database.get_statistics()

                    # Create a Message from the StatisticsMessage
                    message = Message(
                        messageType=MessageTypes.STATISTICS,
                        messageBody=statistics
                    )

                    # Log the statistics
                    logging.debug(f'Statistics: {message}')

                    # Send the statistics
                    await websocket.send_json(message.dict())

                case _:
                    # Log an error
                    logging.error(f'Unknown message type: {msg["messageType"]}')


    except WebSocketDisconnect:
        # Log the disconnection
        logging.info('Websocket Closed')
