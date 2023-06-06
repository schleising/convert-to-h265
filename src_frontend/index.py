import logging

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

# Initialise logging
logging.basicConfig(format='Website: %(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

# Set the base template location
TEMPLATES = Jinja2Templates('/src/templates')

# Instantiate the application object, ensure every request sets the user into Request.state.user
app = FastAPI()

# Gets the homepage
@app.get('/', response_class=HTMLResponse)
async def root(request: Request):
    logging.info('Homepage requested')
    return TEMPLATES.TemplateResponse('index.html', {'request': request})

# Close the connection when the app shuts down
# @app.on_event('shutdown')
# def close_db_connection() -> None:
#     print('Closing DB Connection')
#     MONGODB.client.close()
#     print('Closed DB Connection')
