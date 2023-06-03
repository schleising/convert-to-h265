# Start with the Python Alpine image as the build image
FROM python:3.11-alpine

# Install ffmpeg
RUN apk update && \
    apk add ffmpeg

# Add the required packages, disabling cache to reduce the size of the image
COPY ./requirements.txt /requirements.txt
RUN pip install --user --no-cache-dir -r /requirements.txt

# Set the entrypoint to run uvicorn with a socket connection
CMD [ "python",  "/src/main.py"]
