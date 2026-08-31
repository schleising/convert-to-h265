# Start with the Linuxserver ffmpeg image as the build image
FROM python:alpine AS build

# Add Python, Pip, and git (needed for media-cover-art git+https install)
RUN apk update && apk upgrade && apk add --no-cache build-base libffi-dev git

# Install packages to a prefix so any non-root UID can use them
COPY ./requirements.txt /requirements.txt
RUN pip install --no-cache-dir --prefix=/install -r /requirements.txt

# Create a new image with the required packages
FROM python:alpine

# Install ffmpeg and create a non-root user matching the macOS host
# (uid 501 / gid 20). Reuse the existing dialout group instead of creating gid 20.
RUN apk update && apk upgrade && apk add --no-cache ffmpeg \
    && adduser -u 501 -G dialout -h /home/app -D app

# Copy installed packages from the build image
COPY --from=build /install /usr/local

ENV HOME=/home/app \
    PATH=/usr/local/bin:$PATH

USER app

# Set the entrypoint to run the walker
ENTRYPOINT [ "python3",  "/src/main.py"]
