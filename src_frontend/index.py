from datetime import UTC, datetime, timedelta
import logging
import json
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

# Initialise logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

from .database.database import Database
from .messages.messages import ConvertingFilesMessage, ConvertingFileData, ConvertedFilesMessage, StatisticsMessage, MessageTypes, Message
from .utils.utils import calculate_time_remaining

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

    # Variable to store the last converted files message
    last_converted_files_message: ConvertedFilesMessage | None = None

    # Variable to store the last statistics message
    last_statistics_message: StatisticsMessage | None = None

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
                    current_conversion_status_db_list = await database.get_converting_files()

                    if current_conversion_status_db_list is not None:
                        # Create a ConvertingFilesMessage list
                        current_conversion_status_list: list[ConvertingFileData] = []

                        for current_conversion_status_db in current_conversion_status_db_list:
                            # Get the time since the conversion started
                            if current_conversion_status_db.start_conversion_time is not None:
                                time_since_start = datetime.now().astimezone(UTC) - current_conversion_status_db.start_conversion_time
                            else:
                                time_since_start = timedelta(seconds=0)

                            # Convert the time since the conversion started to a string discarding the microseconds
                            time_since_start_str = str(time_since_start).split('.')[0]

                            # Get the conversion time remaining
                            time_remaining = calculate_time_remaining(
                                start_time=current_conversion_status_db.start_conversion_time,
                                progress=current_conversion_status_db.percentage_complete
                            )

                            # Create a ConvertingFileMessage from the database object
                            current_conversion_status = ConvertingFileData(
                                filename=Path(current_conversion_status_db.filename).name,
                                progress=current_conversion_status_db.percentage_complete,
                                time_since_start=time_since_start_str,
                                time_remaining=time_remaining,
                                backend_name=current_conversion_status_db.backend_name
                            )

                            # Add the ConvertingFileMessage to the list
                            current_conversion_status_list.append(current_conversion_status)

                        # Create a ConvertingFilesMessage from the list
                        current_conversion_status = ConvertingFilesMessage(
                            converting_files=current_conversion_status_list
                        )

                        # Create a Message from the ConvertingFileMessage
                        message = Message(
                            messageType=MessageTypes.CONVERTING_FILES,
                            messageBody=current_conversion_status
                        )

                        # Log the conversion status
                        logging.debug(f'Current conversion status: {message}')

                        # Send the conversion status
                        await websocket.send_json(message.dict())
                    else:
                        # Send the conversion status as None
                        await websocket.send_json(Message(
                            messageType=MessageTypes.CONVERTING_FILES,
                            messageBody=None
                        ).dict())

                    # Get the files converted
                    converted_files = await database.get_converted_files()

                    # Create a ConvertedFilesMessage from the database objects
                    files_converted_message = ConvertedFilesMessage(
                        converted_files=converted_files
                    )

                    # If the files converted message has changed send an update
                    if files_converted_message != last_converted_files_message:
                        # Create a Message from the ConvertedFilesMessage
                        message = Message(
                            messageType=MessageTypes.CONVERTED_FILES,
                            messageBody=files_converted_message
                        )

                        # Log the files converted
                        logging.debug(f'Files converted: {message}')

                        # Send the files converted
                        await websocket.send_json(message.dict())

                        # Set the last converted files message
                        last_converted_files_message = files_converted_message

                    # Get the statistics
                    statistics = await database.get_statistics()

                    # If the statistics have changed send an update
                    if statistics != last_statistics_message:
                        # Create a Message from the StatisticsMessage
                        message = Message(
                            messageType=MessageTypes.STATISTICS,
                            messageBody=statistics
                        )

                        # Log the statistics
                        logging.debug(f'Statistics: {message}')

                        # Send the statistics
                        await websocket.send_json(message.dict())

                        # Set the last statistics message
                        last_statistics_message = statistics

                case _:
                    # Log an error
                    logging.error(f'Unknown message type: {msg["messageType"]}')


    except WebSocketDisconnect:
        # Log the disconnection
        logging.info('Websocket Closed')
