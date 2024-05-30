# Start with the Linuxserver ffmpeg image as the build image
FROM python:alpine as build

# Add Python and Pip
RUN apk update && apk upgrade && apk add --no-cache build-base libffi-dev

# Add the required packages, disabling cache to reduce the size of the image
COPY ./requirements.txt /requirements.txt
RUN pip install --user --no-cache-dir --break-system-packages -r /requirements.txt

# Create a new image with the required packages
FROM python:alpine

# Install Python 3 Minimal
RUN apk update && apk upgrade && apk add --no-cache ffmpeg

# Copy the required packages from the build image
COPY --from=build /root/.local /root/.local

# Set the entrypoint to run uvicorn with a socket connection
ENTRYPOINT [ "python3",  "/src/main.py"]
